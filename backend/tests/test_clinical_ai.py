from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import Principal
from app.clinical_ai import ClinicalAIClient, MAX_INPUT_CHARS, MAX_OUTPUT_BYTES
from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import SchemaVersion
from app.schemas import EncounterCreate, NoteUpdate, PatientCreate
from app.service import EHRService

MODEL = {"id": "OpenMed/test-disease-model", "revision": "abcdef1234567890"}
WORKER_TOKEN = "test-only-internal-worker-credential"


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    stack = ExitStack()
    secret = tmp_path / "worker-token"
    secret.write_text(WORKER_TOKEN)

    def factory(handler=None, *, configured=True, production=False, principals=None):
        settings = Settings(database_url="sqlite:///:memory:", demo_mode=not production,
            ai_service_url="http://openmed:8081" if configured else "", ai_service_token_file=str(secret) if configured else "")
        if production:
            # Only replace the PostgreSQL configuration guard in this SQLite test.
            monkeypatch.setattr(Settings, "load_principals", lambda _: principals or {})
        app = create_app(settings)
        if production:
            Base.metadata.create_all(app.state.database.engine)
            with app.state.database.session() as session:
                session.add(SchemaVersion(version=1))
        if handler:
            app.state.clinical_ai.transport = httpx.MockTransport(handler)
        return stack.enter_context(TestClient(app))

    yield factory
    stack.close()


def test_review_projects_entities_uses_saved_note_and_does_not_mutate(client_factory):
    requests = []

    def worker(request):
        assert str(request.url) == "http://openmed:8081/review"
        assert request.headers["Authorization"] == "Bearer " + WORKER_TOKEN
        payload = json.loads(request.content)
        assert set(payload) == {"text", "operation"}
        assert payload["text"].startswith("Subjective:\nSynthetic demonstration")
        requests.append(payload)
        start = payload["text"].index("routine follow-up")
        return httpx.Response(200, json={"operation": "entities", "model": MODEL,
            "entities": [{"text": "routine follow-up", "label": "DISEASE", "start": start, "end": start + len("routine follow-up"), "confidence": 0.7, "debug": "SENSITIVE_WORKER_DIAGNOSTIC"}],
            "warnings": ["SENSITIVE_WORKER_DIAGNOSTIC"], "rawNote": payload["text"], "durationMs": 1234})

    client = client_factory(worker)
    before = client.get("/api/encounters/demo-encounter-1").json()
    before_history = client.get("/api/encounters/demo-encounter-1/history").json()
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"})
    assert response.status_code == 200
    result = response.json()
    assert result["encounterVersion"] == 1 and result["reviewRequired"] is True
    assert result["model"] == MODEL
    assert result["entities"][0]["text"] == "routine follow-up"
    assert "assertion" not in result["entities"][0]
    assert "rawNote" not in result and "SENSITIVE_WORKER_DIAGNOSTIC" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/encounters/demo-encounter-1").json() == before
    assert client.get("/api/encounters/demo-encounter-1/history").json() == before_history
    audit = client.get("/api/audit")
    assert "routine follow-up" not in audit.text and "SENSITIVE_WORKER_DIAGNOSTIC" not in audit.text
    actions = {event["action"] for event in audit.json()}
    assert {"clinical_ai.entities.requested", "clinical_ai.entities.completed", "clinical_ai.entities.model"} <= actions
    fingerprint = hashlib.sha256(json.dumps(MODEL, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert any(event["resourceId"] == fingerprint and event["outcome"] == "review_required" for event in audit.json())


def test_deidentify_drops_raw_entities_and_extra_fields(client_factory):
    def worker(_):
        return httpx.Response(200, json={"operation": "deidentify", "model": MODEL, "redactedText": "Subjective:\n[NAME] reports a symptom.",
            "redactionCount": 1, "entities": [{"text": "RAW_PATIENT_IDENTIFIER"}], "rawText": "RAW_PATIENT_IDENTIFIER", "warnings": []})
    client = client_factory(worker)
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "deidentify"})
    assert response.status_code == 200
    assert response.json()["entities"] == []
    assert response.json()["redactionCount"] == 1
    assert "RAW_PATIENT_IDENTIFIER" not in response.text
    assert any("miss identifiers" in warning for warning in response.json()["warnings"])


def test_stale_empty_invalid_and_missing_notes_never_reach_worker(client_factory):
    def never_called(_):
        pytest.fail("Rejected note must never be sent to worker")
    client = client_factory(never_called)
    url = "/api/encounters/demo-encounter-1/review"
    assert client.post(url, json={"expectedVersion": 999, "operation": "entities"}).status_code == 409
    assert client.post(url, json={"operation": "entities"}).status_code == 422
    assert client.post(url, json={"expectedVersion": 1, "operation": "prescribe"}).status_code == 422
    assert client.post(url, json={"expectedVersion": 1, "operation": "entities", "text": "caller override"}).status_code == 422
    assert client.post("/api/encounters/missing/review", json={"expectedVersion": 1, "operation": "entities"}).status_code == 404
    empty = client.post("/api/encounters", json={"patientId": "demo-patient-1"}).json()
    assert client.post(f"/api/encounters/{empty['id']}/review", json={"expectedVersion": 1, "operation": "entities"}).status_code == 422


def test_unauthenticated_scope_and_tenant_boundaries(client_factory):
    def never_called(_):
        pytest.fail("Unauthorized record must not reach worker")
    def credential(token, tenant, scopes):
        return hashlib.sha256(token.encode()).hexdigest(), {"tenant_id": tenant, "actor_id": token, "scopes": scopes}
    principals = dict([credential("tenant-a-token", "clinic-a", ["ehr:read"]), credential("tenant-b-token", "clinic-b", ["ehr:read"]), credential("write-only-token", "clinic-a", ["ehr:write"])])
    client = client_factory(never_called, production=True, principals=principals)
    service = EHRService(client.app.state.database, Principal("clinic-a", "setup", frozenset({"ehr:read", "ehr:write"})))
    patient = service.create_patient(PatientCreate(firstName="Synthetic", lastName="Isolation", dateOfBirth="1990-01-01", sex="unknown"))
    encounter = service.create_encounter(EncounterCreate(patientId=patient["id"]))
    url = f"/api/encounters/{encounter['id']}/review"
    payload = {"expectedVersion": 1, "operation": "entities"}
    assert client.post(url, json=payload).status_code == 401
    assert client.get("/api/ai/status").status_code == 401
    assert client.post(url, headers={"Authorization": "Bearer wrong"}, json=payload).status_code == 401
    assert client.post(url, headers={"Authorization": "Bearer tenant-b-token"}, json=payload).status_code == 404
    assert client.post(url, headers={"Authorization": "Bearer write-only-token"}, json=payload).status_code == 403


def test_unconfigured_and_unavailable_errors_are_sanitized_and_audited(client_factory):
    unconfigured = client_factory(configured=False)
    assert unconfigured.get("/api/ai/status").json()["configured"] is False
    response = unconfigured.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"})
    assert response.status_code == 503

    def unavailable(_):
        return httpx.Response(500, text="SECRET_STACK_WITH_PATIENT_TEXT")
    client = client_factory(unavailable)
    status = client.get("/api/ai/status")
    assert status.status_code == 200 and status.json()["ready"] is False
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"})
    assert response.status_code == 503
    assert "SECRET_STACK" not in response.text and "SECRET_STACK" not in status.text
    audit = client.get("/api/audit")
    assert "SECRET_STACK" not in audit.text
    assert any(event["action"] == "clinical_ai.entities.failed.unavailable" for event in audit.json())


def test_worker_connection_failure_preserves_ehr_readiness_and_note(client_factory):
    def disconnected(request):
        raise httpx.ConnectError("INTERNAL_CONNECTION_DIAGNOSTIC", request=request)

    client = client_factory(disconnected)
    before = client.get("/api/encounters/demo-encounter-1").json()
    before_history = client.get("/api/encounters/demo-encounter-1/history").json()
    status = client.get("/api/ai/status")
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert status.json()["ready"] is False
    review = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"})
    assert review.status_code == 503
    assert "INTERNAL_CONNECTION_DIAGNOSTIC" not in status.text + review.text
    assert client.get("/readyz").status_code == 200
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["stats"]["totalPatients"] == 8
    assert client.get("/api/encounters/demo-encounter-1").json() == before
    assert client.get("/api/encounters/demo-encounter-1/history").json() == before_history
    audit = client.get("/api/audit")
    assert "INTERNAL_CONNECTION_DIAGNOSTIC" not in audit.text
    assert any(event["action"] == "clinical_ai.entities.failed.unavailable" for event in audit.json())


@pytest.mark.parametrize("fault", ["timeout", "upstream-timeout", "busy", "wrong-span", "too-large", "invalid-json", "redirect"])
def test_worker_failure_modes_are_bounded_and_sanitized(client_factory, fault):
    def worker(request):
        if fault == "timeout":
            raise httpx.ReadTimeout("PRIVATE_WORKER_ERROR", request=request)
        if fault == "upstream-timeout":
            return httpx.Response(504, text="PRIVATE_WORKER_ERROR")
        if fault == "busy":
            return httpx.Response(429, text="PRIVATE_WORKER_ERROR")
        if fault == "too-large":
            return httpx.Response(200, content=b"x" * (MAX_OUTPUT_BYTES + 1))
        if fault == "invalid-json":
            return httpx.Response(200, text="PRIVATE_WORKER_ERROR")
        if fault == "redirect":
            return httpx.Response(307, headers={"Location": "https://external.invalid/collect"})
        return httpx.Response(200, json={"operation": "entities", "model": MODEL,
            "entities": [{"text": "PRIVATE_WORKER_ERROR", "label": "DISEASE", "start": 0, "end": 1, "confidence": 0.9}]})
    client = client_factory(worker)
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"})
    assert response.status_code == (504 if fault in {"timeout", "upstream-timeout"} else 429 if fault == "busy" else 503 if fault == "redirect" else 502)
    assert "PRIVATE_WORKER_ERROR" not in response.text
    if fault == "busy":
        assert response.headers["Retry-After"] == "5"
    if fault in {"timeout", "upstream-timeout", "busy"}:
        category = "busy" if fault == "busy" else "timeout"
        assert any(event["action"] == f"clinical_ai.entities.failed.{category}" for event in client.get("/api/audit").json())


def test_input_bound_and_status_metadata_projection(client_factory):
    requests = []
    def worker(request):
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json={"status": "ok", "ready": True, "models": {"deidentify": MODEL, "entities": MODEL}, "secret": WORKER_TOKEN})
    client = client_factory(worker)
    status = client.get("/api/ai/status")
    assert status.json()["ready"] is True and set(status.json()["models"]) == {"deidentify", "entities"}
    assert WORKER_TOKEN not in status.text
    # SOAP headings plus a maximal individual section exceed the worker total.
    result = client.patch("/api/encounters/demo-encounter-1/note", json={"expectedVersion": 1, "subjective": "x" * MAX_INPUT_CHARS})
    assert result.status_code == 200
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 2, "operation": "entities"})
    assert response.status_code == 422 and len(requests) == 1


def test_worker_configuration_rejects_credentials_and_redirectable_paths(tmp_path):
    base = Settings(ai_service_url="http://openmed:8081", ai_service_token_file=str(tmp_path / "token"))
    assert ClinicalAIClient(base).configured is True
    for url in ["http://user:password@openmed:8081", "https://openmed:8081/review", "https://openmed:8081?redirect=elsewhere", "file:///tmp/worker"]:
        assert ClinicalAIClient(replace(base, ai_service_url=url)).configured is False
    assert ClinicalAIClient(replace(base, ai_timeout_seconds=9999)).timeout == 120


def test_results_discarded_if_note_changes_during_inference(client_factory):
    client = None
    def worker(_):
        service = EHRService(client.app.state.database, Principal("demo-clinic", "concurrent-editor", frozenset({"ehr:write"})))
        service.update_note("demo-encounter-1", NoteUpdate(expectedVersion=1, plan="Concurrent saved revision"))
        return httpx.Response(200, json={"operation": "deidentify", "model": MODEL, "redactedText": "STALE_RESULT_MUST_NOT_RETURN", "entities": [], "warnings": []})
    client = client_factory(worker)
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "deidentify"})
    assert response.status_code == 409
    assert "STALE_RESULT_MUST_NOT_RETURN" not in response.text
    actions = {event["action"] for event in client.get("/api/audit").json()}
    assert "clinical_ai.deidentify.stale-after-review" in actions
    assert "clinical_ai.deidentify.completed" not in actions
