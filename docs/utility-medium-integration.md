# TOF utility-medium disease extraction

The EHR selects `utility-medium` for the saved-note `entities` operation and
keeps `deidentify` on the offline OpenMed worker. No new local model is downloaded.
The change is confined to TOF-Medical. `tof-ai-app` is a read-only architecture
reference and is neither modified nor required as a running dependency.

## Verified service contract

The reference checkout is `5b515a0a41741f209f0a388af6652483ba719b00`.

| Role | Fixed destination | Authentication |
| --- | --- | --- |
| Inference | `https://ai.techoverfl.com/utility-medium/v1/chat/completions` | Inference Bearer plus `X-TOF-Compute-Lease` |
| Compute catalog and reservations | `https://ops.ai.techoverfl.com/api/compute/v1` | Separate compute Bearer for reservations |
| Reservation release | `DELETE /reservations/{id}` on the compute service | Compute Bearer plus `X-TOF-Reservation-Token` |

The inference body selects model alias `utility-medium` with nonstreaming chat
completions. The provider seed (`db/seeds/providers.rb:209`) and
`app/services/llm/chat_completion.rb:469` establish the inference URL. The compute
workflow is defined by `app/services/compute/tof_router/client.rb`,
`dispatch_binding.rb`, `reservation.rb`, and `app/models/router_compute_lease.rb`.
The fresh catalog supplies the profile rather than hardcoding a physical model.
Pending acquisition reuses the same opaque request identity. Failed reservations
must not fall back to unfenced inference. Reservation tokens never enter the UI.
An unresolved reservation puts new admission on hold until its bounded lifetime
has elapsed. The metadata-only admission journal survives EHR restarts in the
`utility-state` Docker volume (`UTILITY_STATE_DIR`); it contains no patient text
or credentials. Successful confirmed release clears the hold. This initial
adapter admits one utility review at a time in one EHR process.

The public profile catalog was readable without authentication on 2026-10-22;
that proves neither compute authorization nor inference access. The alias has
multiple eligible model implementations. Hosting by TOF does not imply that TOF
trained or owns the underlying weights. Exact deployed model provenance requires
the service operator's deployment metadata; this adapter does not fabricate it.

## Provision and verify

Compose selects `CLINICAL_ENTITIES_PROVIDER=utility-medium` and mounts only
`.secrets/utility/` read-only into the EHR at `/run/secrets/utility/`:

- `inference-key.txt`, selected by `UTILITY_INFERENCE_TOKEN_FILE`.
- `compute-key.txt`, selected by `UTILITY_COMPUTE_TOKEN_FILE`.

Run `./scripts/setup-utility.ps1` in PowerShell 7 to enter the two credentials in
masked prompts. If an issued key has both roles, it can be entered twice. The
script only saves credentials by default. Invoke it with `-VerifyOnly` to call
authenticated `POST /api/ai/verify`; this accepts no clinical text and uses only
a fixed synthetic sentence. It requires `ehr:write`. Verification
must validate the fenced inference output and successful reservation cleanup.
Credentials are not sent through the browser or supplied on the command line.

Missing files show **awaiting credentials**. Present but unverified credentials
show **unverified**. Successful verification is bound to the current credentials
in the running EHR process. Restarting the EHR or rotating keys requires another
verification, using Connections or `./scripts/setup-utility.ps1 -VerifyOnly`.
`GET /api/ai/status` does not initiate paid inference. Neither a public catalog
response nor the existence of a key file is sufficient to report ready.

Live authenticated verification passed on 2026-10-22 using the same provisioned
key for inference and compute. The deployed EHR reserved fenced compute,
extracted the expected exact `asthma` mention from its fixed synthetic sentence,
and confirmed reservation release. Mock transport tests also cover validation
and failure paths. This establishes connection readiness, not clinical accuracy;
evaluation with representative notes remains pending.

## Clinical boundary

The clinician explicitly invokes disease extraction on a saved note. The EHR
resolves the tenant and saved version before sending its note sections to TOF AI.
The route extracts quoted disease mentions, validates them against the original
input, and does not generate diagnoses or an Assessment & Plan. Model-generated
confidence or weights revision is not invented. The UI describes the remote
destination and separates its availability from local de-identification.
The prompt requests a fixed JSON shape, which the adapter strictly validates.
The deployed service rejected schema-constrained generation with a grammar
initialization error, so the request does not set `response_format`. The adapter
tolerates a single empty leading `<think>...</think>` protocol wrapper observed
from this service; substantive reasoning text, prose, malformed JSON, and
ungrounded quotes remain rejected.

Note edits during inference invalidate the returned result. Model output never
changes or signs a note. It is transient and requires clinician review. Metadata
audits contain the operation, outcome, and model fingerprint, not note text or
inference output. Upstream error bodies are not forwarded to the UI or logs.
The EHR's logging controls do not establish the remote provider's retention
policy; that service's configuration remains under its operator's control.

The existing five read-only MCP tools are unchanged. No AI results are admitted
into records or automatically published through MCP. Local de-identification is
not an automatic preprocessing step for the remote extraction operation.

## Kubernetes

The optional `tof-clinical-utility` Secret supplies the two filenames above.
The EHR Deployment mounts it read-only; an absent secret leaves remote extraction
unavailable. Configure destination-restricted HTTPS egress to both fixed TOF
hosts using the cluster CNI's FQDN rules or an approved gateway. Standard
NetworkPolicy cannot select DNS names, so the base manifest intentionally has
no all-Internet egress exception. The OpenMed worker still denies all egress.
The `tof-clinical-utility-state` ReadWriteOnce PVC retains admission metadata
across rollouts. Keep that volume when recreating the EHR.

Run synthetic verification after each EHR rollout. The current starter uses one
replica; additional replicas require coordinated admission state and an operator
verification strategy per process before remote extraction is ready everywhere.
