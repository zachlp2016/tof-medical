import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai_errors import ClinicalAIError
from app.clinical_ai import ClinicalAIClient, project_review
from app.config import Settings
from app.main import create_app
from app.utility_medium import COMPUTE_URL, INFERENCE_URL, SYNTHETIC_TEXT, UtilityMediumClient, grounded_entities

INFERENCE_KEY = "test-only-inference-credential-12345"
COMPUTE_KEY = "test-only-compute-credential-67890"
LEASE_TOKEN = "test-only-fenced-lease-token"
LOCAL_TOKEN = "test-only-openmed-worker-token"


def expiry(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def catalog():
    return {"api_version": "compute-registry/v1", "profile_catalog_version": "test-version",
        "observed_at": expiry(-1), "valid_until": expiry(300), "stale": False,
        "data": [{"kind": "chat", "selectable": True, "configured": True,
            "key": "dynamic-utility-profile", "route_lane": "utility-medium", "request_model": "utility-medium",
            "lane": "internal-utility-lane", "reservation_model": "internal-utility-model", "required_slots": 1,
            "exclusive_resource": False, "stream_required": False, "capabilities": ["chat_completions"],
            "implementations": [{"resource_id": "resource-a", "selectable": True, "configured": True}]}]}


def committed(intent, **overrides):
    return {"id": "reservation-a", "token": LEASE_TOKEN, "resource_id": "resource-a",
        "profile_key": intent["profile_key"], "lane": "internal-utility-lane", "model": "internal-utility-model",
        "required_slots": 1, "exclusive_resource": False, "expires_at": expiry(180),
        "dispatch_enforcement": {"enforced": True, "resource_pinning": True, "header": "X-TOF-Compute-Lease"}, **overrides}


def completion(text, mentions=None, **overrides):
    return {"model": "served-model-tag", "choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"mentions": mentions if mentions is not None else ([{"text": "asthma", "occurrence": 1}] if "asthma" in text else [])}),
        "reasoning_content": "MUST_NOT_SURFACE_REASONING"}}], **overrides}


class Router:
    def __init__(self):
        self.calls = []
        self.intents = []
        self.catalog_override = None
        self.reservation_override = None
        self.completion_override = None
        self.release_status = 204
        self.pending_count = 0
        self.pending_payload_override = None
        self.failure = None

    def __call__(self, request):
        url = str(request.url)
        body = json.loads(request.content) if request.content else None
        self.calls.append((request, body))
        if url.startswith(COMPUTE_URL):
            assert request.headers["Authorization"] == "Bearer " + COMPUTE_KEY
            assert INFERENCE_KEY not in str(request.headers)
        elif url == INFERENCE_URL:
            assert request.headers["Authorization"] == "Bearer " + INFERENCE_KEY
            assert request.headers["X-TOF-Compute-Lease"] == LEASE_TOKEN
            assert "X-TOF-Reservation-Token" not in request.headers
            assert COMPUTE_KEY not in str(request.headers)
        else:
            pytest.fail("Unexpected URL or hidden fallback")
        if request.method == "GET" and url == COMPUTE_URL + "/profiles":
            return httpx.Response(200, json=self.catalog_override or catalog())
        if request.method == "POST" and url == COMPUTE_URL + "/reservations":
            assert set(body) == {"profile_key", "owner", "request_id", "ttl_seconds"}
            assert body["profile_key"] == "dynamic-utility-profile" and body["owner"] == "tof-clinical"
            assert body["ttl_seconds"] == 180
            self.intents.append(body)
            if len(self.intents) <= self.pending_count:
                pending = committed(body)
                pending.pop("token")
                pending.pop("dispatch_enforcement")
                pending.update(state="pending", owner=body["owner"], request_id=body["request_id"])
                pending.update(self.pending_payload_override or {})
                return httpx.Response(202, json=pending, headers={"Retry-After": "1"})
            return httpx.Response(201, json=self.reservation_override or committed(body))
        if request.method == "POST" and url == INFERENCE_URL:
            assert body["model"] == "utility-medium" and body["stream"] is False and body["temperature"] == 0
            assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["reasoning_format"] == "none"
            assert [message["role"] for message in body["messages"]] == ["system", "user"]
            if self.failure == "timeout":
                raise httpx.ReadTimeout("PRIVATE_UPSTREAM_DETAIL " + INFERENCE_KEY, request=request)
            if self.failure == "unauthorized":
                return httpx.Response(401, text="PRIVATE_UPSTREAM_DETAIL " + INFERENCE_KEY)
            if self.failure == "redirect":
                return httpx.Response(307, headers={"Location": "https://other.invalid/collect"})
            return httpx.Response(200, json=self.completion_override or completion(body["messages"][1]["content"]))
        if request.method == "DELETE":
            assert url == COMPUTE_URL + "/reservations/reservation-a"
            assert request.headers["X-TOF-Reservation-Token"] == LEASE_TOKEN
            assert "X-TOF-Compute-Lease" not in request.headers
            return httpx.Response(self.release_status)
        pytest.fail("Unexpected request")


@pytest.fixture
def setup(tmp_path):
    inference, compute, local = (tmp_path / name for name in ("inference", "compute", "local"))
    inference.write_text(INFERENCE_KEY)
    compute.write_text(COMPUTE_KEY)
    local.write_text(LOCAL_TOKEN)
    settings = Settings(database_url="sqlite:///:memory:", demo_mode=True,
        ai_service_url="http://openmed:8081", ai_service_token_file=str(local),
        clinical_entities_provider="utility-medium", utility_inference_token_file=str(inference), utility_compute_token_file=str(compute),
        utility_state_dir=str(tmp_path / "utility-state"),
        principals={hashlib.sha256(b"read-only-credential").hexdigest(): {"tenant_id": "demo-clinic", "actor_id": "reader", "scopes": ["ehr:read"]}})
    router = Router()
    app = create_app(settings)
    app.state.clinical_ai.utility.transport = httpx.MockTransport(router)
    local_calls = []
    def local_worker(request):
        local_calls.append(request)
        assert str(request.url) == "http://openmed:8081/readyz", "Entities must never fall back to OpenMed"
        return httpx.Response(200, json={"ready": True, "models": {"deidentify": {"id": "OpenMed/test-pii", "revision": "pinned-test-revision"}}})
    app.state.clinical_ai.transport = httpx.MockTransport(local_worker)
    with TestClient(app) as client:
        yield client, router, settings, local_calls


def test_missing_keys_leave_deidentify_ready_and_never_call_remote(setup):
    client, router, settings, _ = setup
    Path(settings.utility_compute_token_file).write_text("")
    status = client.get("/api/ai/status").json()
    assert status["operations"]["deidentify"]["ready"] is True
    assert status["operations"]["entities"]["state"] == "awaiting-credentials"
    assert status["operations"]["entities"]["model"] == {"id": "utility-medium", "revision": None}
    assert client.post("/api/ai/verify").status_code == 503
    assert client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"}).status_code == 503
    assert not router.calls


def test_verify_requires_write_and_rejects_caller_input(setup):
    client, router, _, _ = setup
    assert client.post("/api/ai/verify", headers={"Authorization": "Bearer read-only-credential"}).status_code == 403
    assert client.post("/api/ai/verify", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post("/api/ai/verify", json={"text": "Caller content", "url": "https://other.invalid"}).status_code == 422
    assert not router.calls


def test_synthetic_verification_cached_per_credentials_and_restart(setup):
    client, router, settings, _ = setup
    assert client.get("/api/ai/status").json()["operations"]["entities"]["state"] == "unverified"
    assert not router.calls
    assert client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"}).status_code == 503
    verified = client.post("/api/ai/verify", json={})
    assert verified.status_code == 200 and verified.json()["operations"]["entities"]["ready"] is True
    inference_calls = [body for request, body in router.calls if str(request.url) == INFERENCE_URL]
    assert [body["messages"][1]["content"] for body in inference_calls] == [SYNTHETIC_TEXT]
    assert client.post("/api/ai/verify").status_code == 200
    assert len([1 for request, _ in router.calls if str(request.url) == INFERENCE_URL]) == 1
    assert len([1 for request, _ in router.calls if request.method == "DELETE"]) == 1
    Path(settings.utility_inference_token_file).write_text("changed-inference-credential-123456")
    assert client.get("/api/ai/status").json()["operations"]["entities"]["state"] == "unverified"
    restarted = UtilityMediumClient(settings)
    assert restarted.verified_fingerprint is None


def test_inference_uses_deployed_request_shape_without_unsupported_grammar(setup):
    client, router, _, _ = setup
    assert client.post("/api/ai/verify").status_code == 200
    body = next(body for request, body in router.calls if str(request.url) == INFERENCE_URL)
    # The deployed service rejects schema-generated grammars at sampler setup.
    # Strict local parsing and source grounding remain mandatory on its response.
    assert not {"response_format", "json_schema", "grammar"}.intersection(body)
    assert set(body) == {
        "model", "messages", "temperature", "top_p", "max_tokens", "stream",
        "chat_template_kwargs", "reasoning_format",
    }


def test_observed_empty_thinking_wrapper_accepts_only_grounded_json(setup):
    client, router, _, _ = setup
    router.completion_override = completion(SYNTHETIC_TEXT)
    router.completion_override["choices"][0]["message"]["content"] = '<think>\n\n</think>\n\n{"mentions":[{"text":"asthma","occurrence":1}]}'
    assert client.post("/api/ai/verify").status_code == 200
    router.completion_override["choices"][0]["message"]["content"] = '<think>\n</think>\n{"mentions":[{"text":"invented disease","occurrence":1}]}'
    # Wrapper handling never bypasses local exact-source grounding.
    with pytest.raises(ValueError, match="Ungrounded mention"):
        grounded_entities(router.completion_override, SYNTHETIC_TEXT)


@pytest.mark.parametrize("content", [
    "The disease mentioned is asthma.",
    '```json\n{"mentions":[{"text":"asthma","occurrence":1}]}\n```',
    '<think>Reasoning that must not be accepted.</think>{"mentions":[]}',
    '<think></think><think></think>{"mentions":[]}',
    'Introductory prose <think></think>{"mentions":[]}',
    '<think></think>```json\n{"mentions":[]}\n```',
    '<think></think>{"mentions":[]} trailing prose',
    '<think></think>{"mentions":[}',
])
def test_non_json_completion_still_fails_closed_with_lease_cleanup(setup, content):
    client, router, _, _ = setup
    router.completion_override = completion(SYNTHETIC_TEXT)
    router.completion_override["choices"][0]["message"]["content"] = content
    response = client.post("/api/ai/verify")
    assert response.status_code == 502
    assert content not in response.text
    assert client.app.state.clinical_ai.utility.verified_fingerprint is None
    assert len([1 for request, _ in router.calls if request.method == "DELETE"]) == 1


def test_successful_review_is_grounded_nullable_and_does_not_mutate_record(setup):
    client, router, _, local_calls = setup
    assert client.post("/api/ai/verify").status_code == 200
    saved = client.patch("/api/encounters/demo-encounter-1/note", json={"expectedVersion": 1, "assessmentPlan": "Synthetic asthma mention."}).json()
    before_history = client.get("/api/encounters/demo-encounter-1/history").json()
    result = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 2, "operation": "entities"})
    assert result.status_code == 200
    output = result.json()
    assert output["provider"] == "utility-medium" and output["location"] == "remote"
    assert output["model"] == {"id": "utility-medium", "revision": None, "servedModel": "served-model-tag"}
    assert output["entities"][0]["confidence"] is None
    assert "assertion" not in output["entities"][0]
    source = [body for request, body in router.calls if str(request.url) == INFERENCE_URL][-1]["messages"][1]["content"]
    entity = output["entities"][0]
    assert source[entity["start"]:entity["end"]] == entity["text"] == "asthma"
    assert "MUST_NOT_SURFACE_REASONING" not in result.text
    assert client.get("/api/encounters/demo-encounter-1").json() == saved
    assert client.get("/api/encounters/demo-encounter-1/history").json() == before_history
    audit = client.get("/api/audit").text
    assert "Synthetic asthma" not in audit and INFERENCE_KEY not in audit and LEASE_TOKEN not in audit
    assert all(str(request.url).endswith("/readyz") for request in local_calls)


def test_pending_reservation_replays_same_identity_before_dispatch(setup):
    client, router, _, _ = setup
    router.pending_count = 1
    assert client.post("/api/ai/verify").status_code == 200
    assert len(router.intents) == 2 and router.intents[0] == router.intents[1]
    assert len([1 for request, _ in router.calls if str(request.url) == INFERENCE_URL]) == 1
    assert len([1 for request, _ in router.calls if request.method == "DELETE"]) == 1


@pytest.mark.parametrize("change", [
    {"lane": "other-lane"}, {"model": "other-model"}, {"resource_id": "other-resource"},
    {"required_slots": True}, {"exclusive_resource": True}, {"expires_at": "2000-01-01T00:00:00Z"},
    {"expires_at": "2099-01-01T00:00:00Z"}, {"expires_at": "2026-10-22T12:00:00"},
    {"dispatch_enforcement": {"enforced": False, "resource_pinning": True, "header": "X-TOF-Compute-Lease"}},
])
def test_invalid_committed_binding_never_dispatches_and_releases(setup, change):
    client, router, _, _ = setup
    router.reservation_override = committed({"profile_key": "dynamic-utility-profile"}, **change)
    result = client.post("/api/ai/verify")
    assert result.status_code == 502
    assert not any(str(request.url) == INFERENCE_URL for request, _ in router.calls)
    assert len([1 for request, _ in router.calls if request.method == "DELETE"]) == 1


@pytest.mark.parametrize("change", [{"request_id": "another-request"}, {"owner": "another-owner"}, {"token": LEASE_TOKEN}])
def test_invalid_pending_intent_never_dispatches(setup, change):
    client, router, _, _ = setup
    router.pending_count = 1
    router.pending_payload_override = change
    assert client.post("/api/ai/verify").status_code == 502
    assert not any(str(request.url) == INFERENCE_URL for request, _ in router.calls)
    assert len(router.intents) == 1


def test_stale_catalog_and_changed_pending_id_fail_closed(setup):
    client, router, settings, _ = setup
    router.catalog_override = {**catalog(), "valid_until": "2000-01-01T00:00:00Z"}
    assert client.post("/api/ai/verify").status_code == 502 and not router.intents
    router.catalog_override = None
    router.pending_count = 1
    router.reservation_override = committed({"profile_key": "dynamic-utility-profile"}, id="reservation-other")
    # Release must still use only the fixed control origin and the returned safe id.
    original = router.__call__
    def changed_id_transport(request):
        if request.method == "DELETE":
            assert str(request.url) == COMPUTE_URL + "/reservations/reservation-other"
            assert request.headers["Authorization"] == "Bearer " + COMPUTE_KEY
            return httpx.Response(204)
        return original(request)
    client.app.state.clinical_ai.utility.transport = httpx.MockTransport(changed_id_transport)
    assert client.post("/api/ai/verify").status_code == 502
    assert not any(str(request.url) == INFERENCE_URL for request, _ in router.calls)
    journal = json.loads((Path(settings.utility_state_dir) / "reservation.json").read_text())
    assert journal["pendingReservationId"] == "reservation-a"
    attempts = len(router.intents)
    assert client.post("/api/ai/verify").status_code == 503
    assert len(router.intents) == attempts


@pytest.mark.parametrize("failure,expected", [("timeout", 504), ("unauthorized", 503), ("redirect", 503)])
def test_inference_failure_releases_without_secret_leak_or_fallback(setup, failure, expected):
    client, router, _, local_calls = setup
    router.failure = failure
    response = client.post("/api/ai/verify")
    assert response.status_code == expected
    assert "PRIVATE_UPSTREAM_DETAIL" not in response.text and INFERENCE_KEY not in response.text
    assert len([1 for request, _ in router.calls if request.method == "DELETE"]) == 1
    assert not local_calls
    assert client.get("/readyz").status_code == 200


@pytest.mark.parametrize("mentions", [
    [{"text": "hallucinated disease", "occurrence": 1}],
    [{"text": "asthma", "occurrence": 2}],
    [{"text": "asthma", "occurrence": 1, "confidence": 0.99}],
    [{"text": "asthma", "occurrence": True}],
    [{"text": "asthma", "occurrence": 1}, {"text": "asthma", "occurrence": 1}],
])
def test_ungrounded_or_unexpected_extraction_rejected_and_lease_released(setup, mentions):
    client, router, _, _ = setup
    router.completion_override = completion(SYNTHETIC_TEXT, mentions=mentions)
    assert client.post("/api/ai/verify").status_code == 502
    assert len([1 for request, _ in router.calls if request.method == "DELETE"]) == 1


def test_occurrence_offsets_and_incomplete_output_validation():
    source = "asthma then asthma"
    entities, _ = grounded_entities(completion(source, mentions=[{"text": "asthma", "occurrence": 2}]), source)
    assert entities[0]["start"] == 12 and entities[0]["end"] == 18
    incomplete = completion(source)
    incomplete["choices"][0]["finish_reason"] = "length"
    with pytest.raises(ValueError):
        grounded_entities(incomplete, source)
    # Nullable metadata is allowed only in the remote path. Local validation stays strict.
    with pytest.raises(ValueError):
        project_review({"operation": "entities", "model": {"id": "local", "revision": None}, "entities": []}, "entities", source, 1)


def test_release_failure_prevents_ready_and_verification_singleflight(setup):
    client, router, settings, _ = setup
    router.release_status = 500
    assert client.post("/api/ai/verify").status_code == 503
    assert client.app.state.clinical_ai.utility.verified_fingerprint is None
    journal_path = Path(settings.utility_state_dir) / "reservation.json"
    assert journal_path.exists()
    assert INFERENCE_KEY not in journal_path.read_text() and LEASE_TOKEN not in journal_path.read_text()
    before_hold = len(router.intents)
    assert client.post("/api/ai/verify").status_code == 503
    assert len(router.intents) == before_hold
    # Simulate expiry of this test's private journal before independent verification.
    record = json.loads(journal_path.read_text())
    record["admittedAt"] = expiry(-400)
    record["holdUntil"] = expiry(-95)
    journal_path.write_text(json.dumps(record))
    router.release_status = 204
    fresh = UtilityMediumClient(settings, transport=httpx.MockTransport(router))
    async def verify_twice():
        await asyncio.gather(fresh.verify(), fresh.verify())
    before = len(router.intents)
    asyncio.run(verify_twice())
    assert len(router.intents) - before == 1


def test_lost_admission_response_holds_across_client_restart_without_new_claim(setup):
    client, router, settings, _ = setup
    original = router.__call__
    def uncertain(request):
        if request.method == "POST" and str(request.url) == COMPUTE_URL + "/reservations":
            router.intents.append(json.loads(request.content))
            raise httpx.ReadTimeout("UNCERTAIN_PRIVATE_DIAGNOSTIC", request=request)
        return original(request)
    client.app.state.clinical_ai.utility.transport = httpx.MockTransport(uncertain)
    response = client.post("/api/ai/verify")
    assert response.status_code == 504
    assert "UNCERTAIN_PRIVATE_DIAGNOSTIC" not in response.text
    journal = Path(settings.utility_state_dir) / "reservation.json"
    record = json.loads(journal.read_text())
    assert record["requestId"] == router.intents[0]["request_id"]
    assert set(record) == {"version", "requestId", "profileKey", "admittedAt", "holdUntil", "pendingReservationId"}
    restarted = UtilityMediumClient(settings, transport=httpx.MockTransport(router))
    with pytest.raises(ClinicalAIError) as held:
        asyncio.run(restarted.verify())
    assert held.value.category == "pending_claim"
    assert len(router.intents) == 1


def test_corrupt_or_unwritable_journal_fails_before_admission(setup):
    client, router, settings, _ = setup
    folder = Path(settings.utility_state_dir)
    folder.mkdir()
    (folder / "reservation.json").write_text("corrupt")
    assert client.post("/api/ai/verify").status_code == 502
    assert not router.calls
    (folder / "reservation.json").unlink()
    folder.rmdir()
    folder.write_text("not-a-directory")
    assert client.post("/api/ai/verify").status_code == 503
    assert not router.calls


def test_failed_clinical_inference_invalidates_successful_verification(setup):
    client, router, _, _ = setup
    assert client.post("/api/ai/verify").status_code == 200
    router.failure = "unauthorized"
    response = client.post("/api/encounters/demo-encounter-1/review", json={"expectedVersion": 1, "operation": "entities"})
    assert response.status_code == 503
    assert client.get("/api/ai/status").json()["operations"]["entities"]["state"] == "unverified"
    before = len(router.intents)
    assert client.post("/api/ai/verify").status_code == 503
    assert len(router.intents) == before + 1


def test_cancelled_journal_mutation_retains_run_lock_until_thread_finishes(setup):
    from threading import Event
    _, router, settings, _ = setup
    utility = UtilityMediumClient(settings, transport=httpx.MockTransport(router))
    utility.state_dir.mkdir()
    utility.journal_write({"version": 1, "requestId": "00000000-0000-0000-0000-000000000000",
        "profileKey": "dynamic-utility-profile", "admittedAt": expiry(-400), "holdUntil": expiry(-95), "pendingReservationId": None})
    began, finish = Event(), Event()
    original_clear = utility.journal_clear
    def delayed_clear():
        began.set()
        assert finish.wait(timeout=5)
        original_clear()
    utility.journal_clear = delayed_clear
    async def scenario():
        credentials = utility.credentials()
        first = asyncio.create_task(utility.run(SYNTHETIC_TEXT, credentials))
        assert await asyncio.to_thread(began.wait, 5)
        first.cancel()
        await asyncio.sleep(0)
        assert utility.run_lock.locked()
        with pytest.raises(ClinicalAIError) as concurrent:
            await utility.run(SYNTHETIC_TEXT, credentials)
        assert concurrent.value.status_code == 429
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not utility.run_lock.locked()
    asyncio.run(scenario())
    assert not router.calls
