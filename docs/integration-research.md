# TOF Clinical external EHR integration research

Inspected read-only on 2026-10-22: `C:\Users\TOF\Desktop\tof-ai-app`, commit
`5b515a0a41741f209f0a388af6652483ba719b00`. Git status was clean before and after
research. No files, configuration, database records, containers, or deployments
in that application were changed. This document records the contracts present
in that local checkout; it does not assert that the live deployment has the same
commit.

## Shared project design provenance

The shared TOF Clinical project's prior conversation,
**Designing a Family Medicine EMR Overlay**
(`6ac16ce8-8b0c-83ea-923f-4493077ba127`), supplies the product design direction.
It was accessed through the connected chat reader. These are prior design
recommendations, not verified regulatory claims or already implemented host
features:

- Clinical owns the authoritative patient record; TOF provides workflow,
  reasoning, coordination, and bounded assistance.
- Keep clinical content outside generic TOF task titles, calendar descriptions,
  logs, and memory. Use opaque references such as `clinical://patient/UUID`,
  resolved only after authorization.
- AI proposes clinical drafts; a clinician reviews and admits changes.
- Signed clinical notes become immutable artifacts. Amendments create a new
  version with provenance rather than overwriting the signed version.
- Audit clinical reads as well as modifications.
- A patient chart centers an encounter and structured longitudinal problems,
  medications, allergies, observations, results, and documents, with a bounded
  TOF assistance panel.

Practice/Patient/Encounter scope types and automatic clinical job integration
were proposed future host work in that discussion. They are not present merely
because this separate MCP service exists. This implementation must honor the
current read-only host boundary and the instruction not to edit host code.

## Recommended boundary

Run TOF Clinical as its own containerized application, database, and MCP endpoint.
Register the endpoint through TOF's existing MCP configuration. Do not import
the Rails database, mount its source tree, borrow its credentials, or add a second
TOF authorization lane.

```text
TOF conversation + effective scope + approved exact tool
    → existing authenticated POST /mcp/calls
    → registered server credential
    → TOF Clinical HTTP /mcp
    → credential-bound clinic + read-only clinical tools
    → TOF Clinical database
```

The host currently permits **read-only MCP tools only**. Clinical editing can
exist inside the separately authenticated EHR application. Sending orders,
signing notes, prescribing, changing patient data, or running clinical actions
through TOF's MCP boundary requires a future action approval and receipt
contract. The initial integration must not advertise those tools as read-only.

## Exact transport contract

Source: `app/services/mcp/runtime/http_client.rb:12`.

- Transport is `http`, with an HTTP(S) endpoint such as `/mcp`.
- The runtime pins MCP protocol version `2025-11-25`.
- Each invocation initializes a connection, sends `notifications/initialized`,
  then sends `tools/call`. The initialize result must echo `2025-11-25` and
  include a `capabilities.tools` object.
- `notifications/initialized` must return HTTP **202**, with no JSON-RPC result.
- Requests accept `application/json, text/event-stream`. Plain JSON responses
  are supported and are sufficient for this initial server.
- Following initialization the client sends `MCP-Protocol-Version`. If the
  server returned `Mcp-Session-Id`, the client echoes it. Stateless operation
  avoids server session storage and supports multiple replicas.
- Results must use JSON-RPC `2.0`, preserve the exact request ID, and contain a
  `result` or `error`. A tool result must be an object. `isError: true` becomes a
  host `tool_error` rather than a successful clinical response.
- Host timeouts, maximum request bytes, and maximum response bytes come from
  Administrator Application Settings. Clinical results should be bounded and
  paginated.

### Discovery compatibility requirement

Source: `app/services/mcp/servers/test_connection.rb:139`.

The current Settings connection probe sends this request **without an earlier
initialize request**, protocol header, or session ID:

```json
{"jsonrpc":"2.0","id":"connection-test","method":"tools/list","params":{}}
```

The EHR must accept this authenticated, stateless discovery request. A strict
session-required SDK default would prevent the existing host from discovering
the tools. Discovery does not grant execution permission. Return stable tool
names, descriptions, `inputSchema` definitions, and annotations because all of
that metadata participates in TOF's approval fingerprint.

## Authentication and authorization

Sources: `app/models/mcp_server.rb:182`,
`app/services/mcp/runtime/invoke.rb:58`,
`app/services/mcp/capabilities/confirm_mapping.rb:6`, and
`app/services/mcp/runtime/server_identity.rb:9`.

TOF supports stored or environment credentials, including `Authorization:
Bearer <token>`. The MCP server must resolve the clinic and service identity from
the authenticated credential. User-supplied tool arguments, headers, identifiers,
and returned content must not create tenant authority.

The host verifies all of the following before an invocation:

1. The authenticated user can access the Conversation.
2. It is standalone or the canonical home Conversation of a Project.
3. The server and its provider are active.
4. Effective scope grants `mcp_access` and the selected canonical capability.
5. Project work has an enabled `read_only` binding to the exact provider and
   server. Campaign-owned Projects additionally obey their campaign boundary.
6. The named tool is discovered and active, and an administrator approved that
   exact server tool with `effect_kind=read_only`.
7. Its fingerprint still matches the server endpoint, transport, authentication
   configuration, tool name, description, schema, and raw discovery payload.

Discovery suggestions and `readOnlyHint` annotations do not satisfy approval.
Tool-definition or server-configuration changes require review and reapproval.
Supported canonical capabilities include `search_execution`, `query_execution`,
`extract_execution`, and generic `tool_execution`.

### Current identity limitation

The transport forwards only the registered credential and tool arguments. It
does not send authenticated TOF user, tenant, Conversation, Project, workspace,
scope, or invocation ID claims. Therefore the EHR can recognize a clinic-scoped
service account, but cannot claim delegated clinician identity or per-user TOF
patient permissions. A future authenticated identity contract is necessary for
those features. Do not trust an `actor_id` or `tenant_id` inside tool arguments
as a substitute.

## Configuration-only connection procedure

No source edits to `tof-ai-app` are needed for this connection procedure.
It is a later runtime configuration step, not something this research performed.

1. Start TOF Clinical and verify its health, authentication, discovery, and read
   calls from the TOF deployment's network.
2. Open TOF's `/settings/mcp/servers/new`. Set provider name `TOF Clinical`, a
   descriptive server name, HTTP transport, active status, and the EHR MCP URL.
   The controller creates a missing external provider automatically.
3. Set `credential_source_kind=stored`, `auth_scheme=bearer`,
   `auth_header_name=Authorization`, and the EHR's dedicated read credential.
   Alternatively use an existing environment secret reference. Merely filling
   the API Key field is insufficient if credential source remains `none`:
   the current form hides some fields and its defaults can be `none`.
4. Run **Test & Detect Transport**, save, and inspect discovered tools.
5. As administrator, review and confirm each intended tool mapping as
   `read_only`. Use the capability the mapping actually identifies; ensure the
   intended scope grants both that capability and `mcp_access`.
6. For Project use, create an enabled read-only binding to this exact provider
   and server.
7. Exercise the existing authenticated `/mcp/calls` entrance using real
   Conversation/server IDs and one approved tool.

The documented host call shape is:

```json
{
  "conversation_id": 123,
  "server_id": 456,
  "tool_name": "clinical_patients_search",
  "capability_key": "search_execution",
  "arguments": {"query": "Morgan"}
}
```

The IDs and example tool name above are illustrative, not live records. Use the
actual names in this application's discovery response.

## Result handling and workflow limits

Source: `docs/architecture/mcp/mcp_safe_expansion.md` and
`app/services/mcp/runtime/invoke.rb:32`.

The host wraps successful MCP output with `contract_version: 1`, a host-generated
`call_id`, server/tool/capability identity, `status: completed`,
`trust: external_untrusted`, and `evidence_status: not_admitted`.

This is a bounded execution endpoint; registering a server does not automatically
make its tools available to every chat provider or build an autonomous clinical
workflow. MCP content does not become formal TOF evidence. The existing
EvidenceAdmission authority still controls admission and downstream projections.

## Docker and Kubernetes deployment fit

Sources: `docs/architecture/runtime/Runtime_Ecosystems_Docker_Compose_And_Kubernetes.md`,
`docker-compose.yml`, `k8s/test/README.md`, `k8s/prod/README.md`, and root `AGENTS.md`.

- Compose owns local service lifecycle; Kubernetes owns cluster lifecycle. Rails
  calls configured service URLs and should not control EHR containers directly.
- Keep the EHR Compose project and storage separate. `localhost` inside a TOF
  container refers to that TOF container, not the EHR. Use a separately approved
  shared Docker network or a reachable host endpoint; the TOF Compose web/worker
  services already define `host.docker.internal:host-gateway`.
- A published loopback-only host port is suitable for local browser access;
  cross-container host routing must be tested on the actual Docker platform.
- For Kubernetes, give EHR test and production separate namespaces, databases,
  secrets, and persistent volumes. Prefer an internal Service DNS endpoint and
  an explicit network policy permitting the corresponding TOF namespace.
- Existing TOF namespaces are `tof-ai-app-test` and `tof-ai-app`. Keep cross-
  environment access denied and do not share their database credentials.
- Pin immutable image digests for cluster rollout; add readiness/liveness probes,
  non-root containers, resource bounds, persistent database storage, backups,
  and a deliberate migration step in the separate EHR deployment.
- The TOF application's Kubernetes operations start on
  `manatree:/home/zachlp2016/app/tof-ai-app` and follow its test-then-production
  release contract. Local desktop research does not authorize or accomplish
  that release workflow.

## Integration acceptance checks

The EHR suite should prove authenticated pre-initialize discovery, exact protocol
initialization, 202 notification handling, JSON-RPC ID preservation, successful
bounded reads, missing/invalid credential denial, token-bound tenant isolation,
unknown-tool rejection, schema rejection, and unavailable write tools. Live host
acceptance additionally requires discovery, explicit mapping approval, scope
grant, Project binding, and a successful `/mcp/calls` result in the test family.

## TOF visual language for the white and green clinical theme

The canonical typography is in `app/assets/stylesheets/typography.css:12`:
Manrope for human-facing UI/prose and IBM Plex Mono for machine identifiers and
data. The existing rhythm uses 0.95rem body text with 1.55 line height, 0.875rem
controls, 0.75rem metadata, and semibold headings with modest negative tracking.

`app/services/user_settings/theme_preferences.rb` has dark/default/warm presets;
it does not define a packaged white clinical preset. The requested white/green
design is therefore a new TOF adaptation, not an existing theme copied verbatim.
An established light palette exists in the Operator Academy area at
`app/assets/stylesheets/application.css:55`:

| Role | Existing TOF cue |
| --- | --- |
| Primary text | `#172126` |
| Secondary text | `#607078` |
| Paper surface | White |
| Green | `#18785d` |
| Amber | `#a96116` |
| Hairline separators | `rgba(23,33,38,.14)` |

Use predominantly white surfaces, restrained green actions, pale mint selection
states, clean borders, the established typography, and readable clinical tables.
The host's dark cyan default and image backgrounds need not be copied into this
requested light clinical application.
