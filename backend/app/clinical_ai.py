"""Internal OpenMed adapter. Clinical inputs and outputs are never persisted here."""
import asyncio
import json
import math
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urlsplit

import httpx
from .ai_errors import ClinicalAIError

MAX_INPUT_CHARS = 20000
MAX_INPUT_BYTES = 80000
MAX_OUTPUT_BYTES = 524288
MAX_ENTITIES = 1000


def model_metadata(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid model metadata")
    ident, revision = value.get("id"), value.get("revision")
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,199}", ident):
        raise ValueError("Invalid model id")
    if not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}", revision):
        raise ValueError("Invalid model revision")
    return {"id": ident, "revision": revision}


def project_review(payload, operation, source_text, duration_ms):
    """Allowlist response fields and validate offsets against the exact saved input."""
    if not isinstance(payload, dict) or payload.get("operation") != operation:
        raise ValueError("Unexpected operation")
    result = {
        "operation": operation,
        "provider": "openmed",
        "location": "local",
        "model": model_metadata(payload.get("model")),
        "durationMs": duration_ms,
        "reviewRequired": True,
        "entities": [],
        "warnings": ["AI output requires clinician review. No changes have been made to the patient record."],
    }
    if operation == "deidentify":
        redacted = payload.get("redactedText")
        if not isinstance(redacted, str) or not redacted.strip() or len(redacted) > MAX_INPUT_CHARS * 4:
            raise ValueError("Invalid redacted text")
        result["redactedText"] = redacted
        # Do not forward entity spans or raw PII from a de-identification response.
        count = payload.get("redactionCount")
        if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= MAX_ENTITIES:
            result["redactionCount"] = count
        result["warnings"].append("De-identification may miss identifiers. Verify the entire output before sharing.")
    else:
        entities = payload.get("entities")
        if not isinstance(entities, list) or len(entities) > MAX_ENTITIES:
            raise ValueError("Invalid entities")
        for entity in entities:
            if not isinstance(entity, dict):
                raise ValueError("Invalid entity")
            start, end = entity.get("start"), entity.get("end")
            text, label, confidence = entity.get("text"), entity.get("label"), entity.get("confidence")
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source_text):
                raise ValueError("Invalid entity span")
            if not isinstance(text, str) or text != source_text[start:end] or len(text) > 2000:
                raise ValueError("Entity text does not match saved input")
            if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ /\-]{0,79}", label):
                raise ValueError("Invalid entity label")
            if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Invalid confidence")
            projected = {"text": text, "label": label, "start": start, "end": end, "confidence": confidence}
            assertion = entity.get("assertion")
            if assertion is not None:
                if not isinstance(assertion, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ /\-]{0,79}", assertion):
                    raise ValueError("Invalid assertion")
                projected["assertion"] = assertion
            result["entities"].append(projected)
        result["warnings"].append("Extracted entities are suggestions and do not establish diagnoses or clinical facts.")
        result["warnings"].append("The local model extracts disease mentions only; it does not determine negation, temporality, or experiencer.")
    # Worker diagnostics are untrusted and may echo text. Replace with a generic signal.
    if payload.get("warnings"):
        result["warnings"].append("The model reported limitations; review its output carefully.")
    return result


class ClinicalAIClient:
    def __init__(self, settings, *, transport=None):
        from .utility_medium import UtilityMediumClient
        if settings.clinical_entities_provider not in {"openmed", "utility-medium"}:
            raise ValueError("CLINICAL_ENTITIES_PROVIDER must be openmed or utility-medium")
        self.entities_provider = settings.clinical_entities_provider
        self.utility = UtilityMediumClient(settings)
        self.url = settings.ai_service_url.rstrip("/")
        self.token_file = settings.ai_service_token_file
        configured_timeout = settings.ai_timeout_seconds if math.isfinite(settings.ai_timeout_seconds) else 120.0
        self.timeout = min(max(configured_timeout, 1.0), 120.0)
        self.transport = transport
        parsed = urlsplit(self.url)
        self.configured = bool(
            self.url and self.token_file and parsed.scheme in {"http", "https"}
            and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path in {"", "/"}
        )

    def token(self):
        if not self.configured:
            raise ClinicalAIError(503, "Clinical AI is not configured.", "unconfigured")
        try:
            token = Path(self.token_file).read_text(encoding="utf-8-sig").strip()
            if not 20 <= len(token) <= 4096 or any(c.isspace() for c in token):
                raise ValueError("Invalid worker credential")
            return token
        except (OSError, ValueError):
            raise ClinicalAIError(503, "Clinical AI is unavailable.", "credential") from None

    async def request(self, method, path, *, body=None, timeout=None):
        token = self.token()
        budget = timeout or self.timeout
        try:
            async with asyncio.timeout(budget):
                async with httpx.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False,
                                            timeout=httpx.Timeout(budget, connect=min(5.0, budget))) as client:
                    async with client.stream(method, self.url + path, json=body,
                                             headers={"Authorization": "Bearer " + token, "Accept": "application/json"}) as response:
                        if response.status_code == 504:
                            raise ClinicalAIError(504, "Clinical AI timed out. The patient record was not changed.", "timeout")
                        if response.status_code == 429:
                            raise ClinicalAIError(429, "Clinical AI is busy. Try again shortly.", "busy")
                        if response.status_code != 200:
                            raise ClinicalAIError(503, "Clinical AI is unavailable. Try again when the local model is ready.", "unavailable")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_OUTPUT_BYTES:
                                raise ClinicalAIError(502, "Clinical AI returned an invalid response.", "invalid_output")
                        return json.loads(raw)
        except (TimeoutError, httpx.TimeoutException):
            raise ClinicalAIError(504, "Clinical AI timed out. The patient record was not changed.", "timeout") from None
        except (httpx.HTTPError, OSError):
            raise ClinicalAIError(503, "Clinical AI is unavailable. Try again when the local model is ready.", "unavailable") from None
        except (ValueError, UnicodeError):
            raise ClinicalAIError(502, "Clinical AI returned an invalid response.", "invalid_output") from None

    async def local_status(self):
        status = {"configured": self.configured, "ready": False, "models": {}, "warnings": [], "reviewRequired": True}
        if not self.configured:
            status["warnings"] = ["Clinical AI is not configured."]
            return status
        try:
            payload = await self.request("GET", "/readyz", timeout=3.0)
            if not isinstance(payload, dict) or not isinstance(payload.get("ready"), bool) or not isinstance(payload.get("models"), dict):
                raise ValueError("Invalid health response")
            status["models"] = {operation: model_metadata(value) for operation, value in payload["models"].items() if operation in {"deidentify", "entities"}}
            status["ready"] = payload["ready"] and bool(status["models"])
            if not status["ready"]:
                status["warnings"] = ["Local clinical models are still loading or unavailable."]
        except (ClinicalAIError, ValueError):
            status["warnings"] = ["Local clinical AI is unavailable."]
        return status

    async def status(self):
        local = await self.local_status()
        operations = {}
        for operation in ("deidentify", "entities"):
            if operation == "entities" and self.entities_provider == "utility-medium":
                operations[operation] = await self.utility.status()
                continue
            ready = local["ready"] and operation in local["models"]
            operations[operation] = {"configured": self.configured, "ready": ready,
                "state": "ready" if ready else "unavailable" if self.configured else "awaiting-credentials",
                "provider": "openmed", "location": "local", "model": local["models"].get(operation),
                "warnings": [] if ready else local["warnings"] or ["The local model is unavailable."]}
        return {"configured": any(value["configured"] for value in operations.values()),
            "ready": all(value["ready"] for value in operations.values()),
            "models": {key: value["model"] for key, value in operations.items() if value["model"] is not None},
            "warnings": list(dict.fromkeys(warning for value in operations.values() for warning in value["warnings"])),
            "operations": operations, "reviewRequired": True}

    async def verify(self):
        if self.entities_provider != "utility-medium":
            raise ClinicalAIError(422, "Remote entity review is not selected.", "unconfigured")
        await self.utility.verify()
        return await self.status()

    async def review(self, text, operation):
        if not text.strip() or len(text) > MAX_INPUT_CHARS or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ClinicalAIError(422, "The saved note is empty or exceeds the clinical AI input limit.", "input_limit")
        if operation == "entities" and self.entities_provider == "utility-medium":
            return await self.utility.review(text)
        start = monotonic()
        payload = await self.request("POST", "/review", body={"text": text, "operation": operation})
        try:
            return project_review(payload, operation, text, round((monotonic() - start) * 1000))
        except (ValueError, TypeError):
            raise ClinicalAIError(502, "Clinical AI returned an invalid response.", "invalid_output") from None
