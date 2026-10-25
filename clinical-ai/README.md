# Local OpenMed worker

This internal CPU inference worker uses the released OpenMed 3.0.0 SDK and two
official Apache-2.0 ONNX INT8 models. It adds PII-redaction candidates and disease
mention extraction to TOF Clinical. It is not an EHR, diagnostic system, or
comprehensive medication/laboratory extractor. It does not modify clinical
records, sign notes, or expose an MCP endpoint. TOF Clinical owns authorization,
note version checks, read audits, and clinician review.

## Pinned artifacts

| Operation | Official model | Revision |
| --- | --- | --- |
| `deidentify` | [ClinicalE5 PII 33M](https://huggingface.co/OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1-onnx-android/tree/79f7db205869b1be4be23ac4f42aa95bdedc5aee) | `79f7db205869b1be4be23ac4f42aa95bdedc5aee` |
| `entities` | [DiseaseDetect ElectraMed 33M](https://huggingface.co/OpenMed/OpenMed-NER-DiseaseDetect-ElectraMed-33M-v1-onnx-android/tree/54c9cc119d325ddad23300a1e9108bafa9643a06) | `54c9cc119d325ddad23300a1e9108bafa9643a06` |

`models.lock.json` pins the graph, configuration, tokenizer, labels, metadata, and
model card by exact revision, size, and SHA-256. The two graphs total 139,236,068
bytes. `provision_models.py` downloads only those files, verifies each, and writes
the completion manifest only after the entire bundle verifies. Runtime verifies
the complete manifest and every hash before loading. No unpinned custom model
code or pickle weights are executed. Files are world-readable, directories
traversable, and runtime runs as UID 10001 with a read-only model mount.

## Setup

The root project's `scripts/setup-openmed.ps1` builds the image and provisions
the named model volume in a separate online container. Then start the offline
service with `docker compose up --build -d`. Individual provisioning/test commands,
run from the project root:

```powershell
docker build --tag tof-clinical-openmed:local clinical-ai
docker volume create tof-clinical_openmed-models
docker run --rm --user 0 --network bridge --mount src=tof-clinical_openmed-models,dst=/models tof-clinical-openmed:local python /app/provision_models.py
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --memory 3g --cpus 2 --mount src=tof-clinical_openmed-models,dst=/models,readonly tof-clinical-openmed:local python /app/smoke_test.py
```

The runtime exposes port 8081 **only to the EHR's internal network**. It requires
`AI_SERVICE_TOKEN_FILE` with a unique ASCII secret of 32–512 characters. There is
no default credential. `MODEL_ROOT` defaults to `/models`. The Docker image and
service force OpenMed/Hugging Face/Transformers offline flags. Docker's internal
network or Kubernetes NetworkPolicy supplies the actual egress restriction;
offline flags alone are not a network firewall.

`OPENMED_ALLOWED_HOSTS` is a comma-separated exact hostname allowlist, defaulting
to `openmed,localhost,127.0.0.1,testserver`. Set Kubernetes service DNS names in
that variable and use the `localhost` Host header for probes. Browser Origin
headers are rejected for review requests. Credentials belong in mounted secrets.
The worker reads its credential at startup. Rotate the shared secret and restart
the EHR and worker together; hot secret rotation is not implemented.

## HTTP contract

`GET /healthz` always responds 200 once the HTTP process starts; `GET /readyz`
responds 200 only after credential and model verification, otherwise 503. Both
contain only `status`, `ready`, `artifactsVerified`, `sdkVersion`, and
`models.{deidentify,entities}.{id,revision}`. Provenance in an unready response
describes the expected lock, not a successfully loaded model.

`POST /review` requires `Authorization: Bearer <service secret>` and
`Content-Type: application/json`:

```json
{"text":"Synthetic clinical text for review.","operation":"entities"}
```

Both operations return `operation`, `model: {id,revision}`, fixed `warnings`, and
`durationMs`. Entity extraction returns an `entities` array with exactly
`text`, `label`, `start`, `end`, `confidence`. Offsets are Python Unicode code
point indices into the original input. The current model extracts **disease and
condition mentions only**. Negation, temporality, and experiencer are not
assessed; no `assertion` value is invented.
Touching fragments of the same label are joined only across an alphanumeric
boundary within a word, preserving source offsets and the lower confidence.
This repairs outputs such as `hyper` + `tension` without combining separate
words or joining across punctuation. PII masking uses its existing span union.

De-identification returns `redactedText`, `redactionCount`, and an empty
`entities` array. It masks the union of every model-predicted PII span and a
deterministic pattern for complete ASCII email addresses using `[REDACTED]`,
including low-confidence model candidates. The email pattern covers dotted
domains such as `eleanor@example.test`, retains surrounding sentence punctuation,
and supplements models that detect only the mailbox portion. It is not a
comprehensive international email/identifier detector. It never returns the original
input field, raw PII entity list, mappings, or OpenMed's complete result object.
Unrecognized identifiers can remain in `redactedText`: the result is a candidate
for review, not evidence of anonymization or legal de-identification.

Inputs are limited to 20,000 characters and 128 KiB of JSON. OpenMed's
[`predict_batch_detailed`](https://github.com/maziyarpanahi/openmed/blob/v3.0.0/openmed/onnx/inference.py)
uses overlapping 512-token windows with a 96-token overlap, verifies full
coverage, and rejects incomplete results. One window is inferred at a time;
the request has a 128-window limit and a 100-second cooperative ONNX deadline.
The worker has one concurrent inference slot and responds 429 when busy.

Errors are generic `{"error":"code"}` responses (401/403/413/415/422/429/503/504).
Validation does not echo the submitted text. This worker has no database,
request cache, content logs, output logs, audit store, or telemetry exporter.
Access logs and Python logging are disabled; ONNX diagnostics are restricted to
fatal severity. Input and output exist in request-local memory until released.
Memory erasure is not guaranteed by Python, and crash/core dumps should remain
disabled in deployment.

## Verification

`smoke_test.py` runs actual pinned models on synthetic data inside Docker. It
checks redaction, disease spans, source alignment, content well beyond
the first 512 tokens, safe output projection, missing credentials, validation
without input echo, request limits, concurrency, and origin/host handling.
Run with `--network none`, a read-only root filesystem and read-only model volume
to establish that inference neither downloads models nor needs writable state.
The shared secret written during this test is synthetic and temporary; test
input/output is not persisted or printed. No clinical performance benchmark or
real patient data evaluation is claimed by this smoke suite.

Verified on 2026-10-22: all 12 smoke tests passed in Docker with network disabled,
a read-only root/model mount, 3 GiB memory limit, and 2 CPU limit. The suite ran
in 11.036 seconds with the updated application mounted read-only into the existing
image. The regressions include whole-word `hypertension`, fragment boundaries,
and removal of the entire `eleanor@example.test` address while retaining prose.
Both official graph hashes and
all tokenizer/metadata files matched the lock. This establishes integration
behavior on synthetic examples, not general extraction accuracy.
