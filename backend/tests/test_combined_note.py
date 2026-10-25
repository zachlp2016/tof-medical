"""Regression tests for explicit Assessment & Plan conversion and provenance."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.service import note_hash


@pytest.fixture
def client():
    with TestClient(create_app(Settings(database_url="sqlite:///:memory:", demo_mode=True))) as client:
        yield client


BASE = "/api/encounters/demo-encounter-1"


def test_explicit_conversion_preserves_legacy_reads_history_and_hashes(client):
    legacy = client.patch(BASE + "/note", json={"expectedVersion": 1,
        "assessment": "Legacy assessment has distinct findings.", "plan": "Legacy plan has distinct follow-up."}).json()
    history_before = client.get(BASE + "/history").json()
    assert client.get(BASE).json()["note"] == legacy["note"]
    assert client.get("/api/patients/demo-patient-1").json()["encounters"][0]["note"] == legacy["note"]
    assert "assessmentPlan" not in client.get(BASE).json()["note"]
    assert client.get(BASE + "/history").json() == history_before
    combined = "Assessment:\n" + legacy["note"]["assessment"] + "\n\nPlan:\n" + legacy["note"]["plan"]
    response = client.patch(BASE + "/note", json={"expectedVersion": 2, "assessmentPlan": combined})
    assert response.status_code == 200
    canonical = response.json()
    assert canonical["note"]["assessmentPlan"] == combined
    assert set(canonical["note"]) == {"subjective", "objective", "assessmentPlan"}
    assert client.get(BASE).json()["note"] == canonical["note"]
    history = client.get(BASE + "/history").json()
    assert history[:2] == history_before
    assert history[-1]["note"] == canonical["note"]
    assert history[-1]["contentHash"] == note_hash(canonical["note"])


def test_canonical_save_reload_sign_and_immutable(client):
    empty = client.patch(BASE + "/note", json={"expectedVersion": 1, "assessmentPlan": ""})
    assert empty.status_code == 200
    assert client.patch(BASE + "/note", json={"expectedVersion": 2, "status": "signed"}).status_code == 422
    signed = client.patch(BASE + "/note", json={"expectedVersion": 2,
        "assessmentPlan": "Synthetic assessment with an explicit follow-up plan.", "status": "signed"})
    assert signed.status_code == 200
    record = signed.json()
    assert record["status"] == "signed" and record["version"] == 3
    assert record["signatureHash"] == note_hash(record["note"])
    history_before = client.get(BASE + "/history").json()
    assert client.patch(BASE + "/note", json={"expectedVersion": 3, "assessmentPlan": "Attempted replacement"}).status_code == 409
    assert client.get(BASE).json() == record
    assert client.get(BASE + "/history").json() == history_before


def test_signed_legacy_note_is_never_rewritten_on_read_or_conversion_attempt(client):
    signed = client.patch(BASE + "/note", json={"expectedVersion": 1,
        "assessment": "Signed legacy assessment", "plan": "Signed legacy plan", "status": "signed"}).json()
    history = client.get(BASE + "/history").json()
    assert "assessmentPlan" not in signed["note"]
    assert client.get(BASE).json() == signed
    assert client.patch(BASE + "/note", json={"expectedVersion": 2, "assessmentPlan": "Attempted conversion"}).status_code == 409
    assert client.get(BASE).json()["signatureHash"] == signed["signatureHash"]
    assert client.get(BASE + "/history").json() == history


@pytest.mark.parametrize("payload", [
    {"assessmentPlan": "Combined", "assessment": "Legacy"},
    {"assessmentPlan": "Combined", "plan": "Legacy"},
    {"assessmentPlan": "Combined", "plan": None},
    {"assessmentPlan": None},
])
def test_ambiguous_payload_never_changes_note(client, payload):
    original = client.get(BASE).json()
    assert client.patch(BASE + "/note", json={"expectedVersion": 1, **payload}).status_code == 422
    assert client.get(BASE).json() == original
    assert len(client.get(BASE + "/history").json()) == 1


def test_legacy_patch_on_canonical_note_is_denied_without_lost_content(client):
    canonical = client.patch(BASE + "/note", json={"expectedVersion": 1, "assessmentPlan": "Combined text retained"}).json()
    for payload in ({"assessment": "Ambiguous assessment"}, {"plan": "Ambiguous plan"}, {"plan": None}):
        result = client.patch(BASE + "/note", json={"expectedVersion": 2, **payload})
        assert result.status_code == 422 and "assessmentPlan" in result.json()["detail"]
        assert client.get(BASE).json() == canonical
    allowed = client.patch(BASE + "/note", json={"expectedVersion": 2, "subjective": "Updated subjective only"}).json()
    assert allowed["note"]["assessmentPlan"] == "Combined text retained"
    assert allowed["version"] == 3
    assert any(event["action"] == "encounter.legacy-fields.denied" for event in client.get("/api/audit").json())


def test_maximum_legacy_sections_convert_losslessly_with_headings(client):
    assessment, plan = "a" * 20000, "p" * 20000
    legacy = client.patch(BASE + "/note", json={"expectedVersion": 1, "assessment": assessment, "plan": plan})
    assert legacy.status_code == 200
    combined = f"Assessment:\n{assessment}\n\nPlan:\n{plan}"
    converted = client.patch(BASE + "/note", json={"expectedVersion": 2, "assessmentPlan": combined})
    assert converted.status_code == 200
    assert converted.json()["note"]["assessmentPlan"] == combined
    assert client.patch(BASE + "/note", json={"expectedVersion": 3, "assessmentPlan": "x" * 40961}).status_code == 422
    assert client.get(BASE).json()["note"]["assessmentPlan"] == combined


def test_ai_receives_combined_section_once_and_preserves_legacy_sections(tmp_path):
    token_file = tmp_path / "worker-token"
    token_file.write_text("test-only-worker-token-for-combined-notes")
    app = create_app(Settings(database_url="sqlite:///:memory:", demo_mode=True,
        ai_service_url="http://openmed:8081", ai_service_token_file=str(token_file)))
    received = []
    def worker(request):
        received.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"operation": "entities", "model": {"id": "OpenMed/test-disease", "revision": "test-revision"}, "entities": [], "warnings": []})
    app.state.clinical_ai.transport = httpx.MockTransport(worker)
    with TestClient(app) as client:
        legacy = client.patch(BASE + "/note", json={"expectedVersion": 1, "assessment": "LEGACY_FINDING", "plan": "LEGACY_FOLLOWUP"})
        assert legacy.status_code == 200
        assert client.post(BASE + "/review", json={"expectedVersion": 2, "operation": "entities"}).status_code == 200
        assert "Assessment:\nLEGACY_FINDING\n\nPlan:\nLEGACY_FOLLOWUP" in received[-1]
        assert received[-1].count("LEGACY_FINDING") == received[-1].count("LEGACY_FOLLOWUP") == 1
        canonical = client.patch(BASE + "/note", json={"expectedVersion": 2, "assessmentPlan": "COMBINED_FINDING_AND_FOLLOWUP"})
        assert canonical.status_code == 200
        assert client.post(BASE + "/review", json={"expectedVersion": 3, "operation": "entities"}).status_code == 200
        assert received[-1].count("Assessment & Plan:\n") == 1
        assert received[-1].count("COMBINED_FINDING_AND_FOLLOWUP") == 1
        assert "\n\nAssessment:\n" not in received[-1] and "\n\nPlan:\n" not in received[-1]
        assert "LEGACY_FINDING" not in received[-1] and "LEGACY_FOLLOWUP" not in received[-1]
