# TOF Clinical

A standalone EHR foundation for the TOF ecosystem: a white and soft-green
clinical workspace, PostgreSQL persistence, local OpenMed de-identification,
TOF utility-medium disease extraction, and a credential-scoped read-only MCP
service. It runs independently of `tof-ai-app`; that repository was used only
as a read-only integration reference and is not a runtime dependency.

This build contains synthetic patient data. It is a development foundation,
not a certified EHR or a deployment approved for real patient records.

## Fresh Docker installation

Requirements: Git with GitHub SSH access, Docker Desktop using Linux
containers, and PowerShell 7 (`pwsh`).

```powershell
git clone git@github.com:zachlp2016/tof-medical.git
Set-Location tof-medical
./scripts/bootstrap.ps1
./scripts/setup-openmed.ps1
docker compose up --build -d
```

Open http://localhost:8090. Demo API documentation is at
http://localhost:8090/api/docs.

`bootstrap.ps1` creates unique database and bearer credentials in ignored local
files without printing them. It refuses to overwrite an existing setup.
`setup-openmed.ps1` builds the isolated worker and downloads the pinned public
model files into the external `tof-clinical_openmed-models` Docker volume.
Allow several minutes for the first model download and image build. Later starts
reuse that volume.

If Windows blocks local scripts, run them in a one-time PowerShell 7 process;
this does not change the machine-wide execution policy:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-openmed.ps1
```

Useful operations:

```powershell
docker compose ps
./scripts/smoke.ps1
./scripts/smoke-openmed.ps1
docker compose logs --tail 50 ehr
docker compose stop
docker compose up --build -d
```

The browser uses the synthetic demo identity. MCP always requires a bearer
credential. PostgreSQL and OpenMed have no published ports. Clinical data,
OpenMed models, and utility admission state survive container restarts in Docker
volumes. Do not delete those volumes during an upgrade.

## Repository deployment files

- `Dockerfile`: React build plus the FastAPI EHR/API/MCP runtime.
- `clinical-ai/Dockerfile`: isolated offline OpenMed CPU worker.
- `compose.yaml`: EHR, PostgreSQL, OpenMed, networks, mounts, health checks, and
  persistent volumes for a local installation.
- `deploy/kubernetes/`: namespace, ConfigMap, EHR and OpenMed Deployments,
  ClusterIP Service, utility-state PVC, NetworkPolicies, migration Job, and
  Kustomize configuration.
- `scripts/`: bootstrap, model provisioning, utility credential setup, LAN
  firewall setup, and smoke checks.
- `docs/`: TOF integration research and AI integration boundaries.

Local `.env`, `.secrets/`, downloaded models, database files, build output, and
dependency directories are excluded from Git and Docker build contexts.

## LAN access

The Compose port defaults to `127.0.0.1:8090`. To reach the app from another
laptop on the same LAN, set exact values in the ignored `.env` file:

```dotenv
EHR_BIND_ADDRESS=0.0.0.0
EHR_ALLOWED_HOSTS=localhost,127.0.0.1,ehr,host.docker.internal,<LAN-IP>
EHR_ALLOWED_ORIGINS=http://localhost:8090,http://127.0.0.1:8090,http://<LAN-IP>:8090
```

Then recreate only the EHR container:

```powershell
docker compose up -d --no-deps ehr
```

Windows Firewall may require an inbound TCP 8090 rule restricted to the Wi-Fi
interface and local subnet. Run the following in an administrator PowerShell,
replacing the address when necessary:

```powershell
./scripts/allow-lan.ps1 -LocalAddress <LAN-IP>
```

Only the EHR port is published. Guest Wi-Fi client isolation can prevent LAN
access. Restore `EHR_BIND_ADDRESS=127.0.0.1` and recreate `ehr` to return to
local-only access.

## Clinical workspace

The initial workspace includes the daily schedule, patients, appointments,
encounters, care tasks, audit history, and connection status. Encounter notes
use Subjective, Objective, and one combined Assessment & Plan text area.
Historical and signed records remain preserved, and signed notes are immutable.

Medication, condition, and allergy lists are chart snapshots in this release.
An empty allergy list means unknown. No model sends orders, prescribes, signs a
note, or changes the record automatically.

## Clinical AI

Open an encounter, save edits, then use **Find clinical entities** or
**Preview de-identified text**. Both operations analyze the saved note version
and return temporary review results without changing the record.

Disease-mention extraction uses TOF `utility-medium` remotely at
`https://ai.techoverfl.com/utility-medium`. De-identification uses the pinned
OpenMed model in the local offline worker. Connections reports readiness for the
two operations independently.

To configure utility-medium, use masked prompts:

```powershell
./scripts/setup-utility.ps1
docker compose up -d --no-deps ehr
./scripts/setup-utility.ps1 -VerifyOnly
```

If scripts are blocked:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-utility.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-utility.ps1 -VerifyOnly
```

The utility script stores credentials only in `.secrets/utility/`. Enter the
same key twice only when the issuer has authorized it for both inference and
compute reservation. Verification uses a fixed synthetic sentence, obtains a
fenced compute reservation, validates the grounded response, and confirms lease
release. Restarting the EHR or rotating keys requires verification again.

`utility-medium` is a routing alias, not a claim about ownership or the physical
model revision. The local OpenMed worker has no database credential, published
port, or internet route at runtime. Model provisioning runs separately and has
no EHR records or credentials mounted. Details are in
[utility-medium integration](docs/utility-medium-integration.md) and
[OpenMed integration](docs/openmed-integration.md).

## Connect an MCP client

| Setting | Local value |
| --- | --- |
| Transport | Streamable HTTP, stateless JSON responses |
| Endpoint | `http://localhost:8090/mcp` |
| Authorization | `Bearer <contents of .secrets/mcp-token.txt>` |
| Protocol | `2025-11-25` |
| Tools | `search_patients`, `get_patient_chart`, `list_appointments`, `get_encounter`, `list_tasks` |

An example client shape is in `integration/mcp-client.example.json`. Supply the
token through the client's secret mechanism; never place credentials in source
control or a URL. A Docker Desktop client can use
`http://host.docker.internal:8090/mcp`. A hosted client needs an authenticated
HTTPS route because it cannot reach this machine's localhost.

To attach it through the existing TOF workflow:

1. Open TOF Settings, MCP Servers, then New.
2. Create or select the external provider and use transport `http` with the
   reachable EHR endpoint.
3. Select stored credentials and bearer authentication explicitly.
4. Run Test & Detect Transport.
5. Confirm the five exact tool schemas as `read_only` in TOF administration.
6. Grant `mcp_access` and the appropriate mapped capability to the intended
   scope, then bind the exact server in read-only mode.

This repository does not write to `tof-ai-app` or its database. See
[the integration contract](docs/integration-research.md) for the source paths,
approval flow, and identity limitations reviewed in that project.

## Kubernetes preparation

The starter manifests are not applied automatically. They require your image
registry, PostgreSQL service, secret manager, ingress, and network topology.

1. Build and push the root EHR image and `clinical-ai/` worker image. Replace
   manifest image placeholders with immutable digests.
2. Provision PostgreSQL and its backup/restore policy independently of TOF's
   database.
3. Create namespace `tof-clinical` and these Secrets:
   - `tof-clinical-database`, key `url`.
   - `tof-clinical-principals`, key `principals.json`.
   - `tof-clinical-openmed`, key `token`.
   - Optional `tof-clinical-utility`, keys `inference-key.txt` and
     `compute-key.txt`.
4. Populate the `tof-clinical-openmed-models` PVC with the pinned provisioning
   script in a separate operator-controlled download job before starting the
   offline worker. Do not give that job EHR data or secrets.
5. Set exact allowed hosts/origins, terminate TLS at ingress, and adapt the base
   NetworkPolicies for ingress, DNS, and database topology. Add restricted HTTPS
   egress from the EHR to `ai.techoverfl.com` and `ops.ai.techoverfl.com` through
   CNI FQDN policy or an approved gateway. Keep OpenMed egress denied.
6. Set the same release image in `migrate-job.yaml`, apply it separately, and
   wait for completion before rolling out the application:

```powershell
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/migrate-job.yaml
kubectl wait -n tof-clinical --for=condition=complete job/tof-clinical-migrate-v1 --timeout=300s
kubectl kustomize deploy/kubernetes
kubectl apply -k deploy/kubernetes
```

Review rendered YAML before applying it. The internal MCP address is
`http://tof-clinical.tof-clinical.svc.cluster.local:8080/mcp`.

The manifests use `DEMO_MODE=false`, a non-root user, a read-only root
filesystem, dropped capabilities, no service-account token, health probes,
resource limits, a ClusterIP Service, one EHR replica, and Recreate strategy.
The utility-state PVC retains reservation metadata only. The migration Job is
outside the base kustomization and runs once per schema release. The initial
migration uses `create_all`; add versioned incremental migrations before schema
changes.

## Authentication

`TOKEN_PRINCIPALS_FILE` points to JSON keyed by lowercase SHA-256 token digest:

```json
{
  "<sha256 of a unique random bearer token>": {
    "tenant_id": "your-practice",
    "actor_id": "tof-clinical-reader",
    "scopes": ["ehr:read"]
  }
}
```

Clinical writers need `ehr:read` and `ehr:write`; audit access is `ehr:audit`.
Keep MCP credentials read-only. Production startup requires provisioned
credentials and PostgreSQL. Restart the service after credential rotation. The
current token map is a bootstrap mechanism; OIDC/SSO and per-user lifecycle
management remain future work.

## Development and validation

```powershell
# Render and validate deployment configuration
docker compose config --quiet
kubectl kustomize deploy/kubernetes | Out-Null

# Frontend type check and optimized build
docker run --rm -v "${PWD}/frontend:/work" -w /work node:22-alpine sh -c 'npm ci && npm run build'

# Backend regression suite with a disposable test database
docker run --rm -v "${PWD}/backend:/work" -w /work python:3.12-slim sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -q'

# Running-container MCP and OpenMed checks
./scripts/smoke.ps1
./scripts/smoke-openmed.ps1
```

Frontend: React, TypeScript, and Vite. Backend: FastAPI, SQLAlchemy,
PostgreSQL, and the official MCP Python SDK.

## Current boundaries

This first slice establishes UI, persistence, scoped MCP, note versioning,
audit, and bounded AI review. Structured coded clinical resources, FHIR/SMART,
patient matching, consent and sensitive-record controls, per-clinician SSO,
signed-note amendments, prescribing, laboratory, billing, formal incremental
migrations, recovery exercises, and operational/clinical validation remain
future work. Preserve patient records inside the clinical authorization boundary
rather than placing them into generic TOF tasks, calendars, memory, or telemetry.
