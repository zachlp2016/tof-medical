# TOF EHR service

This isolated EHR starter owns its own data. No code or database belonging to tof-ai-app is changed. It supplies read-only MCP access to the existing TOF workflow harness and a separate REST workspace for EHR edits. There is no automatic outbound record synchronization. When configured and verified, an explicit entity-review request sends the saved note snapshot to the remote TOF AI utility-medium service; de-identification remains on the local OpenMed worker.

Run from the backend directory with `uvicorn app.main:app --host 0.0.0.0 --port 8080`. The root Docker setup provides the intended deployment. Run tests with `python -m pytest -q` after installing `requirements-dev.txt`.

Optional PostgreSQL race tests: set `TEST_POSTGRES_URL` to a dedicated PostgreSQL test database and run `python -m pytest -q tests/test_postgres.py`. The test role needs permission to create schemas. Every test creates a unique temporary schema and drops only that schema afterward. These tests verify simultaneous saves at the same note version, concurrent signing versus editing, immutable signed notes, version provenance, and denied-write audits against PostgreSQL row locking. Without the environment variable, these two tests skip.

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL, e.g. `postgresql+psycopg://user:password@db:5432/tof_ehr` |
| `DEMO_MODE` | Defaults false. Explicit true enables synthetic demo REST identity and idempotent synthetic seed. Never use demo mode for real records. |
| `TOKEN_PRINCIPALS_FILE` | Path to server-provisioned credential map; `EHR_PRINCIPALS_FILE` is an alias. |
| `EHR_ALLOWED_HOSTS` | Comma-separated request hostnames without ports. Include the internal service DNS name and public ingress name. |
| `EHR_ALLOWED_ORIGINS` | Comma-separated browser origins with scheme and port. Absence of Origin is permitted for backend MCP clients. |
| `FRONTEND_DIR` | Defaults `/app/frontend/dist`. |
| `AI_SERVICE_URL` | Optional internal OpenMed worker origin, e.g. `http://openmed:8081`; omitted disables local OpenMed operations. |
| `AI_SERVICE_TOKEN_FILE` | Shared worker credential file mounted into EHR and worker; never returned through the API. |
| `AI_SERVICE_TIMEOUT_SECONDS` | Total inference request timeout; default and maximum 120 seconds. |
| `CLINICAL_ENTITIES_PROVIDER` | `openmed` is the compatibility default; this deployment selects `utility-medium` for remote disease-mention review. No fallback occurs between providers. |
| `UTILITY_INFERENCE_TOKEN_FILE` | Server-mounted inference credential for the fixed `https://ai.techoverfl.com/utility-medium` service. |
| `UTILITY_COMPUTE_TOKEN_FILE` | Separate server-mounted compute credential for `https://ops.ai.techoverfl.com/api/compute/v1`. |
| `UTILITY_STATE_DIR` | Durable, writable metadata-only admission journal; default `/var/lib/tof-clinical/utility`. Mount a named volume/PVC and run one EHR process/replica for this journal design. |

Credential file format (the key must be the lowercase SHA-256 digest of the actual bearer token):

```json
{
  "<64-character-sha256-digest>": {
    "tenant_id": "demo-clinic",
    "actor_id": "tof-agent",
    "scopes": ["ehr:read"]
  }
}
```

Supported scopes are `ehr:read`, `ehr:write`, and `ehr:audit`. Provision separate credentials for separate actors/tenants/projects. The MCP credential should have only `ehr:read`. Tenant and actor identity come exclusively from that server-side map; client tenant headers and tool arguments never establish identity. Tokens remain outside frontend bundles and source control. Rotating the mounted secret requires an application restart in this starter.

Demo REST requests without Authorization bind to `demo-clinic` / `demo-clinician`; an invalid supplied token is rejected. MCP always requires a valid bearer token, including in demo mode. Demo credentials must target `demo-clinic`. Production rejects missing credentials and non-PostgreSQL storage and does not seed data. The frontend's production login/SSO flow is a future integration, not implemented by this service.

## Schema and persistence

Demo startup creates the initial schema and seeds synthetic fixtures if the demo tenant has no patients. Production startup only validates that schema version 1 exists. Run `python -m migrations.001_initial` once as a deployment migration Job before starting production app replicas. The initial migration is non-destructive and creates tables. Future upgrades need separate reviewed migrations; editing migration 001 is not an upgrade strategy. Deploy and verify database backup/restore before real record use.

`/healthz` reports process health. `/readyz` verifies database connectivity. Static frontend assets are served from the configured frontend directory.

## API contract

All API payloads are camelCase. Collection responses are arrays. Clinical responses use `Cache-Control: no-store`. The demo OpenAPI explorer is `/api/docs`.

- `GET /api/dashboard`: counts, appointments, recent patients, tasks. Clinic dates use America/Los_Angeles.
- `GET /api/patients?search=`, `POST /api/patients`, `GET /api/patients/{id}` (chart envelope).
- `GET /api/appointments?date=YYYY-MM-DD&patientId=`, `POST /api/appointments`, `PATCH /api/appointments/{id}` with status.
- `GET /api/encounters?patientId=`, `POST /api/encounters`, `GET /api/encounters/{id}`.
- `PATCH /api/encounters/{id}/note`: required `expectedVersion`, optional `subjective`, `objective`, `assessmentPlan`, and status `draft` or `signed`. The current editor displays three sections: Subjective, Objective, and one Assessment & Plan textarea. `assessmentPlan` accepts up to 40,960 characters, allowing lossless conversion of two legacy 20,000-character sections plus their headings. An explicit canonical save removes the current note's legacy `assessment` and `plan` keys; earlier version snapshots remain unchanged. Existing legacy notes still return and accept separate `assessment`/`plan` fields until explicitly converted. A PATCH mixing canonical and legacy fields returns 422; a legacy-field PATCH against a canonical note also returns 422. Reads never convert notes or rewrite signed hashes. Stale versions return 409. Signing requires all three canonical sections, or all four legacy sections for a legacy note. Signed records are immutable through this API. Each version captures actor, timestamp, hash, and note snapshot. `GET /api/encounters/{id}/history` returns version history. Amendment workflows are not yet implemented.
- `GET /api/tasks`, `PATCH /api/tasks/{id}` with status `open` or `completed`.
- `GET /api/audit`: latest 100 tenant-scoped metadata events; requires `ehr:audit`.
- `GET /api/integration`: connector readiness, five tools, scopes, and demo status. `connectedToTof:false` explicitly means external connection has not been established.
- `GET /api/ai/status`: authenticated `ehr:read` status with aggregate `configured`, `ready`, `models`, `warnings`, and `reviewRequired:true`. Additive `operations.deidentify` and `operations.entities` each report `configured`, `ready`, `state`, `provider`, `location`, `model`, and `warnings`. States include `awaiting-credentials`, `unverified`, `ready`, and `unavailable`. Gate each operation on its own ready flag: missing remote credentials do not disable local de-identification. Status checks never perform inference. Remote ready means the current credential pair passed an earlier synthetic fenced roundtrip and the current profile remains eligible; `verifiedAt` records that earlier verification, not a new authentication proof. The public profiles endpoint alone does not verify credentials.
- `POST /api/ai/verify`: requires `ehr:write` and accepts no body or an empty object only. An explicit invocation uses a fixed synthetic sentence to verify the configured remote compute/inference credential pair; no encounter data is read. The process caches a successful verification per credential fingerprint and coalesces simultaneous verification requests. A restart, key change, or actual inference/auth/lease failure invalidates the cache. Repeated calls with a still-verified pair reuse that proof and return safe operation status. This endpoint is never called by startup or GET status and is not activated without supplied credentials.
- `POST /api/encounters/{id}/review`: authenticated `ehr:read` review of the saved SOAP snapshot. Body is `{expectedVersion: 1, operation: "deidentify"}` or operation `"entities"`. Returns `encounterId`, `encounterVersion`, `operation`, `model:{id,revision}`, `entities`, optional `redactedText`/`redactionCount`, `durationMs`, `warnings`, and `reviewRequired:true`. No record mutation or result persistence occurs. A stale version before or after inference returns 409 and discards the result. Empty notes and SOAP inputs exceeding 20,000 characters / 80,000 UTF-8 bytes are rejected. Save edits before requesting review.

Appointment statuses: `scheduled`, `checked-in`, `in-progress`, `completed`, `cancelled`, `no-show`. Empty allergy arrays mean **unknown**, never no known allergies. The demo has no prescribing, lab ordering, real results, billing, or external clinical data integrations.

## Clinical AI review providers

OpenMed runs as a separate internal service for local de-identification. The selected utility-medium provider handles disease-mention extraction remotely through the existing TOF service. Only saved SOAP sections are supplied: canonical notes send one Assessment & Plan section, while legacy notes retain their separate Assessment and Plan sections. The separate total-input limit remains 20,000 characters. Request-supplied text, URLs, tokens, tenant routing, and model selection are not accepted. Requests refuse redirects and environment proxies, have bounded time and response sizes, and project only known result fields. Errors are fixed public messages. De-identification responses never return raw PII spans.

Utility-medium uses a fresh profiles catalog and requires exactly one eligible profile for the service alias. It reserves compute with `profile_key`, owner `tof-clinical`, a stable request UUID, and TTL 180 seconds; it validates profile/resource/slot/exclusivity binding, fenced dispatch enforcement, and bounded expiry before any note is sent. Pending 202 responses replay the identical intent and request UUID with validated Retry-After; there is no unleased or direct fallback. Inference uses only the inference bearer and `X-TOF-Compute-Lease`. Finally, release uses only the compute bearer and `X-TOF-Reservation-Token` against the fixed control origin. The non-streaming request disables thinking and requests strict JSON disease quotes with occurrence numbers. Quotes are resolved to exact offsets in the saved input; hallucinated, duplicate, malformed, or truncated output is rejected. Remote confidence and immutable revision are null because the service does not supply those guarantees. `model.id` remains the requested alias; an optional validated `servedModel` records returned metadata without assuming model ownership. Local OpenMed confidence/revision validation remains strict.

Before the first reservation POST, an atomic, fsynced journal stores only opaque request/profile identity and timestamps. It never contains notes, tokens, credential fingerprints, or model output. An uncertain POST outcome, tokenless pending deadline, cancellation, or failed release retains a bounded hold across process restarts; no new admission is created until that fixed window expires. The hold covers the request budget plus reservation TTL and clock tolerance (at most 305 seconds), including a late grant after a lost response. Confirmed release clears it. Corrupt/unwritable state fails closed. A process lock rejects concurrent admission attempts with 429. This implementation requires one EHR process/replica with durable state; use shared transactional admission coordination before scaling horizontally.

Clinical AI does not add MCP tools, prescribe, generate notes, sign notes, or save results. The five read-only MCP descriptors remain unchanged. Audit events capture verification metadata, review requests/completions/failures, stale versions, and a SHA-256 fingerprint of canonical sorted projected model metadata. No clinical text or inference result enters audit records. Responses identify their own provider and local/remote location and require clinician review. Exact disease quotes do not establish diagnoses, negation, temporality, or experiencer; redaction can miss identifiers. Missing configuration/availability returns sanitized 503, invalid output 502, timeouts 504, and saturation 429. Synchronous database operations run off the event loop. No live service or model verification is performed by the mock contract tests.

## MCP integration

The exact endpoint is `/mcp`, with no trailing-slash redirect. Official Python MCP SDK 1.30.0 provides stateless Streamable HTTP with JSON responses. This maintained SDK release supports the TOF runtime's `2025-11-25` protocol. Authenticated `tools/list` is accepted before initialize for TOF settings discovery. Standard initialize → initialized (HTTP 202) → tools/call is tested, along with the official SDK client over real HTTP.

Read-only tools: `search_patients`, `get_patient_chart`, `list_appointments`, `get_encounter`, `list_tasks`. Tool descriptors have read-only, non-destructive annotations. Scope is fixed by the bearer credential; no scope headers are required. Handlers use request-local identity, tested under simultaneous mixed-tenant requests. Audit metadata captures clinical reads/writes and denied note changes without copying SOAP text. Invalid/unrecognized bearer attempts are rejected before a tenant can be established; centralized ingress/security logging should capture those events without logging bearer values.

SDK references: [official SDK v1 documentation](https://py.sdk.modelcontextprotocol.io/v1/), [ASGI mounting guidance](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/stories/starlette_mount/README.md), [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

This is an initial clinical workflow implementation, not a compliance certification or a production clinical go-live claim. Production work still includes organizational identity/SSO, governed role assignment, clinical terminology and reconciliation, attested signing/amendments, hardened DB permissions and audit retention, encryption and managed keys, backup/restore exercises, operational monitoring, and organization-specific clinical/privacy review.
