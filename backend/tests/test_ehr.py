import hashlib
from datetime import date
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.auth import Principal
from app.config import Settings
from app.db import Database, Base
from app.main import create_app
from app.models import Patient, AuditEvent
from app.schemas import PatientCreate
from app.service import EHRService

READ_TOKEN = "test-only-read-token"
WRITE_TOKEN = "test-only-write-token"


def settings(path="sqlite:///:memory:"):
    return Settings(database_url=path, demo_mode=True, principals={
        hashlib.sha256(READ_TOKEN.encode()).hexdigest(): {"tenant_id": "demo-clinic", "actor_id": "reader", "scopes": ["ehr:read"]},
        hashlib.sha256(WRITE_TOKEN.encode()).hexdigest(): {"tenant_id": "demo-clinic", "actor_id": "writer", "scopes": ["ehr:read", "ehr:write", "ehr:audit"]},
    })


@pytest.fixture
def client():
    with TestClient(create_app(settings())) as client:
        yield client


def test_demo_seed_and_health(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stats"]["totalPatients"] == 8
    assert dashboard["stats"]["appointmentsToday"] == 6
    assert len(client.get("/api/patients?search=Eleanor").json()) == 1
    assert client.get("/api/patients?search=%").json() == []
    assert client.get("/api/patients/demo-patient-2").json()["patient"]["allergyStatus"] == "unknown"


def test_credential_fail_closed_and_scope_enforcement(client):
    assert client.get("/api/patients", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    assert client.post("/api/patients", headers={"Authorization": f"Bearer {READ_TOKEN}"}, json={
        "firstName": "Test", "lastName": "Patient", "dateOfBirth": "1990-01-01", "sex": "unknown"
    }).status_code == 403
    assert client.get("/api/audit", headers={"Authorization": f"Bearer {READ_TOKEN}"}).status_code == 403
    assert client.get("/api/patients", headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.get("/api/patients", headers={"Host": "attacker.invalid"}).status_code == 400
    assert client.get("/api/patients", headers={"X-Tenant-ID": "another-tenant"}).json()[0]["id"].startswith("demo-patient-")


def test_production_configuration_fails_closed():
    with pytest.raises(ValueError, match="Production requires provisioned"):
        Settings().load_principals()
    with pytest.raises(ValueError, match="SHA-256"):
        Settings(demo_mode=True, principals={"plaintext-token": {}}).load_principals()
    with pytest.raises(ValueError, match="Demo credentials"):
        Settings(demo_mode=True, principals={"a"*64: {"tenant_id": "real-clinic", "actor_id": "test", "scopes": ["ehr:read"]}}).load_principals()


def test_validation_and_durable_writes(client):
    invalid = {"firstName": "", "lastName": "Patient", "dateOfBirth": "2999-01-01", "sex": "unknown"}
    assert client.post("/api/patients", json=invalid).status_code == 422
    valid = {"firstName": "Synthetic", "lastName": "New", "dateOfBirth": "1990-01-01", "sex": "Female"}
    assert client.post("/api/patients", json={**valid, "tenant_id": "attacker"}).status_code == 422
    result = client.post("/api/patients", json=valid)
    assert result.status_code == 201
    patient = result.json()
    assert client.get(f"/api/patients/{patient['id']}").json()["patient"]["sex"] == "female"
    appointment = {"patientId": patient["id"], "startTime": "2026-10-22T09:00:00-07:00", "durationMinutes": 30}
    assert client.post("/api/appointments", json={**appointment, "startTime": "2026-10-22T09:00:00"}).status_code == 422
    result = client.post("/api/appointments", json=appointment)
    assert result.status_code == 201
    ident = result.json()["id"]
    assert any(a["id"] == ident for a in client.get("/api/appointments?date=2026-10-22").json())
    assert client.patch(f"/api/appointments/{ident}", json={"status": "checked-in"}).json()["status"] == "checked-in"
    assert client.patch(f"/api/appointments/{ident}", json={"status": "anything"}).status_code == 422
    result = client.post("/api/encounters", json={"patientId": patient["id"], "chiefComplaint": "Synthetic visit"})
    assert result.status_code == 201
    assert result.json()["version"] == 1


def test_versioned_immutable_signed_note_and_audit_privacy(client):
    base = "/api/encounters/demo-encounter-1"
    assert client.patch(base + "/note", json={"subjective": "Missing version"}).status_code == 422
    result = client.patch(base + "/note", json={"expectedVersion": 1, "subjective": "PRIVATE_TEST_NOTE"})
    assert result.status_code == 200
    assert result.json()["version"] == 2
    assert client.patch(base + "/note", json={"expectedVersion": 1, "assessment": "Stale overwrite"}).status_code == 409
    assert client.patch(base + "/note", json={"expectedVersion": 2, "status": "signed"}).status_code == 422
    result = client.patch(base + "/note", json={"expectedVersion": 2, "assessment": "Synthetic assessment", "plan": "Synthetic follow-up", "status": "signed"})
    assert result.status_code == 200
    assert result.json()["signedBy"] == "demo-clinician"
    assert len(result.json()["signatureHash"]) == 64
    assert client.patch(base + "/note", json={"expectedVersion": 3, "plan": "Mutation"}).status_code == 409
    history = client.get(base + "/history").json()
    assert [v["version"] for v in history] == [1, 2, 3]
    audit = client.get("/api/audit")
    assert "PRIVATE_TEST_NOTE" not in audit.text
    assert any(event["action"] == "encounter.sign" for event in audit.json())
    assert {"encounter.stale.denied", "encounter.incomplete-sign.denied", "encounter.immutable.denied"} <= {event["action"] for event in audit.json() if event["outcome"] == "denied"}


def test_tenant_isolation_for_reads_and_cross_tenant_references():
    db = Database("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    scopes = frozenset({"ehr:read", "ehr:write", "ehr:audit"})
    a, b = EHRService(db, Principal("clinic-a", "a", scopes)), EHRService(db, Principal("clinic-b", "b", scopes))
    patient = a.create_patient(PatientCreate(firstName="Tenant", lastName="One", dateOfBirth=date(1990, 1, 1), sex="unknown"))
    assert len(a.patients()) == 1
    assert b.patients() == []
    with pytest.raises(HTTPException) as exc:
        b.patient_chart(patient["id"])
    assert exc.value.status_code == 404
    from app.schemas import AppointmentCreate, EncounterCreate
    with pytest.raises(HTTPException):
        b.create_appointment(AppointmentCreate(patientId=patient["id"], startTime="2026-10-22T09:00:00-07:00"))
    with pytest.raises(HTTPException):
        b.create_encounter(EncounterCreate(patientId=patient["id"]))
    assert all(event["actorId"] == "b" for event in b.audit_events())
    assert any(event["outcome"] == "not_found" for event in b.audit_events())


def test_database_persists_and_seed_is_idempotent(tmp_path):
    url = "sqlite:///" + str(tmp_path / "ehr.db")
    with TestClient(create_app(settings(url))) as first:
        result = first.post("/api/patients", json={"firstName": "Persisted", "lastName": "Synthetic", "dateOfBirth": "1990-01-01", "sex": "unknown"})
        ident = result.json()["id"]
    with TestClient(create_app(settings(url))) as second:
        assert second.get(f"/api/patients/{ident}").status_code == 200
        assert second.get("/api/dashboard").json()["stats"]["totalPatients"] == 9


def test_mcp_tof_handshake_discovery_and_call(client):
    headers = {"Authorization": f"Bearer {READ_TOKEN}", "Accept": "application/json, text/event-stream"}
    discovery = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": "connection-test", "method": "tools/list"})
    assert discovery.status_code == 200
    tools = discovery.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"search_patients", "get_patient_chart", "list_appointments", "get_encounter", "list_tasks"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert all("tenant" not in t["inputSchema"]["properties"] for t in tools)
    initialize = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "TOF-compatibility-test", "version": "1.0.0"}}})
    assert initialize.status_code == 200
    assert initialize.json()["result"]["protocolVersion"] == "2025-11-25"
    headers["MCP-Protocol-Version"] = "2025-11-25"
    notification = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notification.status_code == 202
    call = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_patients", "arguments": {"query": "Eleanor"}}})
    assert call.status_code == 200
    assert call.json()["result"]["isError"] is False
    assert "Eleanor Pena" in call.text
    missing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_patient_chart", "arguments": {"patient_id": "other-tenant-id"}}})
    assert missing.json()["result"]["isError"] is True
    assert "Record not found" in missing.text
    assert client.get("/api/audit").json()[0]["actorId"] in {"reader", "demo-clinician"}


def test_dashboard_counts_are_not_truncated(client):
    from app.models import Task, Appointment, now
    from app.service import CLINIC_TZ
    today = now().astimezone(CLINIC_TZ).date()
    db = client.app.state.database
    with db.session() as s:
        for index in range(205):
            s.add(Task(tenant_id="demo-clinic", patient_id="demo-patient-1", title=f"Synthetic task {index}", status="open", due_date=today))
            s.add(Appointment(tenant_id="demo-clinic", patient_id="demo-patient-1", start_time=now(), status="checked-in", clinician="test-actor"))
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stats"]["pendingTasks"] == 209
    assert dashboard["stats"]["appointmentsToday"] == 211
    assert dashboard["stats"]["checkedIn"] == 206
    assert len(dashboard["tasks"]) == 100
    assert len(dashboard["appointments"]) == 200


def test_concurrent_mcp_credentials_do_not_share_identity(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.models import SchemaVersion
    # SQLite is a test substitute for PostgreSQL only. No runtime production bypass exists.
    principals = {
        hashlib.sha256(b"tenant-a-token").hexdigest(): {"tenant_id": "clinic-a", "actor_id": "actor-a", "scopes": ["ehr:read"]},
        hashlib.sha256(b"tenant-b-token").hexdigest(): {"tenant_id": "clinic-b", "actor_id": "actor-b", "scopes": ["ehr:read"]},
    }
    monkeypatch.setattr(Settings, "load_principals", lambda _: principals)
    app = create_app(Settings(database_url="sqlite:///" + str(tmp_path / "concurrent.db"), demo_mode=False))
    db = app.state.database
    Base.metadata.create_all(db.engine)
    with db.session() as s:
        s.add(SchemaVersion(version=1))
        for tenant in ("a", "b"):
            s.add(Patient(id=f"patient-{tenant}", tenant_id=f"clinic-{tenant}", mrn="SAME-MRN", first_name="Synthetic", last_name=tenant.upper(), date_of_birth=date(1990, 1, 1), sex="unknown"))
    with TestClient(app) as c:
        assert c.get("/api/patients").status_code == 401
        def fetch(tenant):
            headers = {"Authorization": f"Bearer tenant-{tenant}-token", "Accept": "application/json, text/event-stream"}
            response = c.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": tenant, "method": "tools/call", "params": {"name": "search_patients", "arguments": {}}})
            assert response.status_code == 200
            assert response.json()["result"]["isError"] is False
            assert f"patient-{tenant}" in response.text
            assert f"patient-{'b' if tenant == 'a' else 'a'}" not in response.text
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(fetch, ["a", "b"] * 5))
        with db.session() as s:
            events = s.scalars(select(AuditEvent).where(AuditEvent.action == "patients.search")).all()
            assert len(events) == 10
            assert all(event.actor_id == "actor-" + event.tenant_id[-1] for event in events)
