"""Opt-in PostgreSQL locking tests, isolated in a unique temporary schema.

Run with TEST_POSTGRES_URL set to a dedicated test database URL. The role needs
CREATE SCHEMA permission. Only the schema created by this fixture is removed.
No public tables or application demo records are read or changed.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.auth import Principal
from app.db import Base, Database
from app.schemas import EncounterCreate, NoteUpdate, PatientCreate
from app.service import EHRService

pytestmark = pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL is required for PostgreSQL locking tests")


@pytest.fixture
def postgres_service():
    url = make_url(os.environ["TEST_POSTGRES_URL"])
    assert url.get_backend_name() == "postgresql", "Concurrency tests require actual PostgreSQL"
    schema = "ehr_concurrency_" + uuid4().hex
    administrator = create_engine(url)
    with administrator.begin() as connection:
        connection.execute(CreateSchema(schema))
    # Each thread obtains its own connection with the same isolated search_path.
    database = Database(url.update_query_dict({"options": "-csearch_path=" + schema}).render_as_string(hide_password=False))
    try:
        Base.metadata.create_all(database.engine)
        principal = Principal("concurrency-test-tenant", "setup-actor", frozenset({"ehr:read", "ehr:write", "ehr:audit"}))
        service = EHRService(database, principal)
        patient = service.create_patient(PatientCreate(firstName="Synthetic", lastName="Concurrency", dateOfBirth="1990-01-01", sex="unknown"))
        encounter = service.create_encounter(EncounterCreate(patientId=patient["id"], chiefComplaint="Synthetic locking test"))
        yield service, encounter
    finally:
        database.engine.dispose()
        assert schema.startswith("ehr_concurrency_") and len(schema) == len("ehr_concurrency_") + 32
        with administrator.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        administrator.dispose()


def race_note_updates(service, encounter_id, operations):
    barrier = Barrier(len(operations))

    def run(operation):
        actor, payload = operation
        worker = EHRService(service.db, Principal(service.principal.tenant_id, actor, service.principal.scopes))
        barrier.wait(timeout=10)
        try:
            result = worker.update_note(encounter_id, NoteUpdate(**payload))
            return {"actor": actor, "status": 200, "result": result}
        except HTTPException as exc:
            return {"actor": actor, "status": exc.status_code, "detail": exc.detail}

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return list(executor.map(run, operations))


def test_postgres_simultaneous_draft_saves_allow_exactly_one(postgres_service):
    service, encounter = postgres_service
    results = race_note_updates(service, encounter["id"], [
        ("writer-a", {"expectedVersion": 1, "subjective": "Synthetic draft A"}),
        ("writer-b", {"expectedVersion": 1, "subjective": "Synthetic draft B"}),
    ])
    assert sorted(result["status"] for result in results) == [200, 409]
    winner = next(result for result in results if result["status"] == 200)
    current = service.encounter(encounter["id"])
    assert current["version"] == 2
    assert current["note"] == winner["result"]["note"]
    assert current["status"] == "draft"
    history = service.note_history(encounter["id"])
    assert [entry["version"] for entry in history] == [1, 2]
    assert history[-1]["actorId"] == winner["actor"]
    audit = service.audit_events()
    assert sum(entry["action"] == "encounter.note.update" for entry in audit) == 1
    assert sum(entry["action"] == "encounter.stale.denied" and entry["outcome"] == "denied" for entry in audit) == 1


def test_postgres_simultaneous_sign_and_save_preserve_immutability(postgres_service):
    service, encounter = postgres_service
    ident = encounter["id"]
    completed = service.update_note(ident, NoteUpdate(expectedVersion=1,
        subjective="Synthetic subjective", objective="Synthetic objective",
        assessment="Synthetic assessment", plan="Synthetic plan"))
    results = race_note_updates(service, ident, [
        ("signer", {"expectedVersion": completed["version"], "status": "signed"}),
        ("editor", {"expectedVersion": completed["version"], "plan": "Synthetic concurrent revision"}),
    ])
    assert sorted(result["status"] for result in results) == [200, 409]
    winner = next(result for result in results if result["status"] == 200)
    current = service.encounter(ident)
    assert current["version"] == 3
    assert current["note"] == winner["result"]["note"]
    if current["status"] == "draft":
        # A winning edit requires the signer to reload/review before a new sign.
        assert winner["actor"] == "editor"
        with pytest.raises(HTTPException) as stale_sign:
            service.update_note(ident, NoteUpdate(expectedVersion=2, status="signed"))
        assert stale_sign.value.status_code == 409
        current = service.update_note(ident, NoteUpdate(expectedVersion=3, status="signed"))
    else:
        assert winner["actor"] == "signer"
    assert current["status"] == "signed"
    signed_version, signed_note, signed_hash = current["version"], current["note"], current["signatureHash"]
    assert signed_hash and current["signedBy"] and current["signedAt"]
    with pytest.raises(HTTPException) as immutable:
        service.update_note(ident, NoteUpdate(expectedVersion=signed_version, plan="Attempted change after sign"))
    assert immutable.value.status_code == 409
    unchanged = service.encounter(ident)
    assert (unchanged["version"], unchanged["note"], unchanged["signatureHash"]) == (signed_version, signed_note, signed_hash)
    history = service.note_history(ident)
    assert len(history) == signed_version
    assert history[-1]["status"] == "signed"
    assert history[-1]["contentHash"] == signed_hash
    assert any(event["action"] == "encounter.immutable.denied" and event["outcome"] == "denied" for event in service.audit_events())
