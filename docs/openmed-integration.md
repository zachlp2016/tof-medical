# OpenMed integration research and implemented boundary

Implementation update: the EHR includes a local OpenMed 3.0.0 ONNX worker and a
de-identification preview. Disease extraction now selects TOF utility-medium;
it waits for separate credentials and synthetic verification. The local disease
model remains installed but is not used by that route. See
`docs/utility-medium-integration.md` for the remote boundary and
`clinical-ai/models.lock.json` for the exact official artifact revisions and
SHA-256 hashes, and the root README for setup and runtime controls. The findings
below record the upstream research that informed the boundary; no clinical-brief
or automatic chart-writing capability is enabled.

Verified 2026-10-22 through the GitHub connector against the official
[OpenMed repository](https://github.com/maziyarpanahi/openmed). The latest GitHub
release returned by `/releases/latest` was
[v3.0.0, published 2026-10-07](https://github.com/maziyarpanahi/openmed/releases/tag/v3.0.0).
The tag resolved to commit `ea920f36fadd7b45935247d639f0ffa1ef493b23`, and its
`openmed/__about__.py` reports `3.0.0`. The current `master` README already refers
to later mobile versions; the API findings below are pinned to the released
`v3.0.0` source. This research did not install OpenMed, download weights, run
inference, or modify the EHR backend at the research stage. The subsequent
implementation uses the released CPU ONNX API and separately provisioned weights.

## Recommendation

OpenMed is a clinical AI SDK with local extraction, de-identification, inference,
and service interfaces. It is not a complete EHR or practice-management system.
It complements TOF Clinical's patient records, appointments, encounter lifecycle,
signatures, and audit rather than replacing those responsibilities. The upstream
package describes itself as a local-first clinical extraction/de-identification
SDK. [Package definition](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/pyproject.toml)

The implemented integration uses a **separate internal inference service**:

```text
Authorized clinician in TOF Clinical
  → EHR resolves exact tenant, patient, encounter, and note version
  → bounded note input to local OpenMed worker
  → PII review/extraction candidates with source offsets and model provenance
  → clinician reviews proposal inside EHR
  → temporary review output; no automatic record changes or import action

TOF-AI-APP
  → existing approved read-only TOF Clinical MCP tools
```

The original implementation ran both operations through the local worker; the
current Compose selection uses it for de-identification only. Neither OpenMed
inference results nor successful MCP calls authorize a clinical record change.
EHR readiness remains independent of worker readiness; unavailable inference
returns a bounded error while ordinary record workflows remain available.

## Verified upstream interfaces

### Python

The released package supports Python 3.10+. `openmed[hf]==3.0.0` selects the
PyTorch/Transformers runtime, `openmed[hf,service]==3.0.0` adds the REST service,
and `openmed[mcp]==3.0.0` adds MCP transport. The MCP extra alone is not the model
runtime. Model assets and optional dependencies must be provisioned separately.
The SDK is Apache-2.0; that does not establish the license of every model or
dataset. [Versioned package extras](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/pyproject.toml)

These public calls are present in source:

| API | Relevant verified parameters | Result |
| --- | --- | --- |
| `openmed.analyze_text(text, model_name=..., *, model_id=None, config=None, assert_context=False, cache_results=False, ...)` | Registry key or local model path; `model_id` aliases `model_name`; optional clinical context annotation | `AnalyzeResult` by default, with entity results |
| `openmed.extract_pii(text, model_name=..., confidence_threshold=0.5, config=None, use_smart_merging=True, lang="en", ...)` | PII model and language | `PredictionResult` |
| `openmed.deidentify(text, method="mask", model_name=..., confidence_threshold=0.7, keep_mapping=False, config=None, ...)` | `mask`, `remove`, `replace`, `hash`, or `shift_dates`; optional audit/policy controls | `DeidentificationResult`, or audit result when selected |

Sources: [analysis API](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/__init__.py#L405),
[PII API](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/core/pii.py#L1393),
[de-identification API](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/core/pii.py#L2620).

Illustrative adapter code using the verified API, **not executed here**:

```python
from openmed import OpenMedConfig, analyze_text, deidentify

config = OpenMedConfig(device="cpu", backend="hf", local_only=True,
                       cache_dir="/models")

# These paths must contain separately provisioned, qualified model artifacts.
redacted = deidentify(
    synthetic_note,
    method="mask",
    model_name="/models/pii",
    keep_mapping=False,
    config=config,
)
analysis = analyze_text(
    redacted.deidentified_text,
    model_id="/models/clinical-ner",
    config=config,
    assert_context=True,
    cache_results=False,
)
```

Model choice, thresholds, entity semantics, and negation/experiencer accuracy
still need evaluation. This example is an integration shape, not a validated
medical interpretation pipeline.

### REST and MCP

The service exposes `GET /health`, `GET /livez`, `GET /readyz`, `POST /analyze`,
`POST /pii/extract`, `POST /pii/deidentify`, and `POST /brief`. Its documented
entry point is `python -m openmed.service.logging --host 0.0.0.0 --port 8080`.
The EHR should use an internal allowlisted wrapper or a tightly configured
service, not pass arbitrary client model names or local filesystem paths.
[REST source](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/service/app.py),
[README service example](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/README.md)

Verified MCP tools include `openmed_analyze_text`, `openmed_extract_pii`,
`openmed_deidentify`, `openmed_list_models`, `openmed_ground`,
`openmed_ground_concepts`, `openmed_export_fhir`, and `openmed_brief`.
Their input/output schemas and effect annotations are in the versioned tool
registry. OpenMed additionally contains state-changing tools; do not expose its
whole catalog through TOF's approved read-only boundary.
[Tool registry](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/mcp/tool_registry.py)

The CLI supports `openmed-mcp --transport streamable-http --host 0.0.0.0
--port 8081 --streamable-http-path /mcp`. Source constructs the MCP server with
`stateless_http=True` and `json_response=True`. This shape is promising for TOF,
but compatibility with TOF's pre-initialize `tools/list` and pinned
`2025-11-25` handshake still needs a live conformance test before a direct
OpenMed registration is claimed. The EHR's own five-tool endpoint has a separate
tested contract. [MCP server](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/mcp/server.py#L2107)

## Critical output boundary

**Do not forward or log `DeidentificationResult.to_dict()` as a sanitized result.**
Its source includes `original_text` and the raw detected identifiers under
`pii_entities[].text`. `keep_mapping=False` does not remove those fields.
The wrapper must explicitly select `deidentified_text` plus permitted aggregate
counts/model metadata, and retain raw results only inside the EHR's authorized
clinical boundary. Even the selected redacted text requires residual-identifier
review; inference is not a guarantee that every identifier was removed.
[Result serialization](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/core/pii.py#L177)

Keep source text, extracted entity surfaces, prompts, and clinical output out of
ordinary HTTP access logs, generic TOF tasks, and diagnostic exceptions. This
implementation persists only metadata audit events, not review results. Do not
automatically replace names or dates in the authoritative chart with de-identified
variants.

## Local-only deployment

The user's requested Compose setup includes the `openmed` service. Its separate
pinned image keeps model dependencies out of the EHR container. Model weights
are provisioned explicitly before the offline worker starts.

- Mount reviewed model artifacts read-only at fixed server-owned paths. Obtain
  artifacts in a separate provisioning step; pin model revisions/checksums and
  record their licenses. No automatic downloads during a clinical request.
- Set `OPENMED_OFFLINE=1` and use `OpenMedConfig(local_only=True)`. The released
  implementation also enables `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and
  `HF_DATASETS_OFFLINE`. Missing artifacts should fail closed.
- Disable external provider integrations and outbound telemetry. Enforce a
  network policy around the container as well: application socket guards are
  not an OS-level isolation boundary for arbitrary native/subprocess code.
- Publish no public inference port. Permit only the EHR service to call the
  worker, authenticate the request, and restrict allowed operations and models.
  Give the worker no EHR database credentials, TOF credentials, or Docker socket.
- Start with CPU evaluation and explicit memory/concurrency limits. Add GPU
  deployment only after measuring the selected models. A health response alone
  is insufficient evidence that inference assets load and execute.
- In Kubernetes, use a separate Deployment/Service with the same authenticated
  internal contract, read-only model volume, bounded requests, and denied
  Internet egress. Keep EHR and inference rollouts independently reversible.

The offline variables and `local_only` flag are verified source features. The
implemented ONNX path uses `local_files_only=True`; Compose, the EHR adapter,
network policy, pinned model selection, and CPU limits are now present in this
repository. Real-model tests run with no Docker network and read-only mounts.
[Offline implementation](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/core/offline.py),
[configuration](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/core/config.py)

### Authentication requires deliberate configuration

The versioned MCP guide says its built-in server does not validate bearer tokens,
but the same release's code contains opt-in `MCPAuthorizationConfig` and token
verification. `enabled` defaults to false. Treat the guide as incomplete for that
optional path; do not infer security from a successful bind or health check.
The REST authentication configuration also defaults to disabled. Use a tested
authenticated boundary and restricted network access before connecting it to
clinical records. [MCP guide](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/docs/mcp-clients.md),
[MCP auth source](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/service/security.py#L1002),
[REST auth source](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/service/auth.py#L134)

## Clinical brief limitations

`openmed.clinical.build_clinical_brief()` exists, as do REST `/brief` and MCP
`openmed_brief`. The released guide explicitly limits the current evidence-packet
contract to synthetic data. It requires reviewed evidence, an exact review-bound
context, calibrated local NLI, and a local privacy detector. Missing assets or
review configuration produce refusal. Its initial claim alignment policy is
strict rather than general paraphrase grounding. Consequently it should be a
synthetic evaluation exercise here, not a production clinical-summary feature.
[Clinical brief contract](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/docs/clinical/clinical-brief.md)

The REST request accepts bounded `text` (maximum 16,384 characters), local model
aliases `mlx`, `extractive`, `maple`, or `maple-preview`, one of the supported
profiles, and an opaque `review_id`. The response status is `needs_review` or
`refused`; successful generation never means clinician approval. A server-owned
context provider still has to authorize the caller and supply the required
evidence. [Request/response schema](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/service/schemas.py#L1258)

## Acceptance before enabling the optional service

Use synthetic fixtures to prove successful local inference, absent-model refusal,
no network egress, no raw-text serialization in external responses/logs,
tenant-bound request authorization, immutable model provenance, bounded payloads
and deadlines, and clinician-only acceptance through the current note-version
check. Evaluate false positive/negative behavior for the actual selected
de-identification and extraction models. Keep the UI status explicit when the
optional service or model is unavailable; never substitute fabricated analysis.
