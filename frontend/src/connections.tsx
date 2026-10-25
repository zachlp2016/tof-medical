import { useState } from "react";
import type { FormEvent } from "react";
import {
  Check,
  Copy,
  KeyRound,
  Link2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { displayDate, hasBearer, setBearer, time, useApi } from "./api";
import type { AuditEvent, Integration } from "./types";
import { Empty, ErrorMessage, Field, Loading, PageHeading, Status } from "./ui";
import { ClinicalAiConnection } from "./clinical-review";
export function Audit({ revision }: { revision: number }) {
  const { data, error, loading, reload } = useApi<AuditEvent[]>(
    "/audit",
    revision,
  );
  return (
    <>
      <PageHeading
        title="Audit trail"
        description="A record of access and changes in this workspace."
        action={
          <button className="button" onClick={reload}>
            <RefreshCw size={16} />
            Refresh
          </button>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : data?.length ? (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id}>
                  <td>
                    {displayDate(e.timestamp)}
                    <small className="table-subtext">{time(e.timestamp)}</small>
                  </td>
                  <td className="mono">{e.actorId}</td>
                  <td>{e.action}</td>
                  <td>
                    {e.resourceType}
                    <small className="table-subtext mono">{e.resourceId}</small>
                  </td>
                  <td>
                    <Status value={e.outcome} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <Empty
          title="No audit events"
          detail="Workspace activity will appear here."
        />
      )}
    </>
  );
}
export function Connections({
  revision,
  onSessionChange,
}: {
  revision: number;
  onSessionChange: () => void;
}) {
  const { data, error, loading, reload } = useApi<Integration>(
    "/integration",
    revision,
  );
  const [token, setToken] = useState("");
  const [sessionActive, setSessionActive] = useState(hasBearer);
  const [copied, setCopied] = useState("");
  const [copyError, setCopyError] = useState("");
  function connect(e: FormEvent) {
    e.preventDefault();
    setBearer(token);
    setToken("");
    setSessionActive(true);
    onSessionChange();
  }
  function disconnect() {
    setBearer("");
    setSessionActive(false);
    onSessionChange();
  }
  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      setCopyError("");
    } catch {
      setCopyError(
        "Clipboard access is unavailable. Select and copy the text below.",
      );
    }
  }
  const endpoint = data?.mcpEndpoint
    ? new URL(data.mcpEndpoint, window.location.origin).toString()
    : `${window.location.origin}/mcp`;
  const configuration = JSON.stringify(
    {
      mcpServers: {
        "tof-clinical": {
          type: "http",
          url: endpoint,
          headers: { Authorization: "Bearer ${TOF_EHR_MCP_TOKEN}" },
        },
      },
    },
    null,
    2,
  );
  return (
    <>
      <PageHeading
        title="Connections"
        description="A clinical workspace designed to connect with TOF."
        action={
          <button className="button" onClick={reload}>
            <RefreshCw size={16} />
            Refresh status
          </button>
        }
      />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : data ? (
        <>
          <div className="connection-status">
            <div className="connection-service-icon">
              <Link2 size={27} />
            </div>
            <div>
              <h2>TOF-AI-APP</h2>
              <p>
                {data.connectedToTof
                  ? "Connected to TOF."
                  : "Register and verify this MCP endpoint in your TOF deployment. Registration status is managed there."}
              </p>
            </div>
            <Status
              value={data.connectedToTof ? "connected" : "verify-in-tof"}
            />
          </div>
          <div className="connection-grid">
            <section className="panel connection-details">
              <div className="section-heading">
                <h2>MCP service</h2>
                <Status value={data.status} />
              </div>
              <dl className="details-list">
                <div>
                  <dt>Service</dt>
                  <dd>{data.service}</dd>
                </div>
                <div>
                  <dt>Mode</dt>
                  <dd>{data.mode}</dd>
                </div>
                <div>
                  <dt>Protocol</dt>
                  <dd className="mono">{data.protocolVersion}</dd>
                </div>
                <div>
                  <dt>Tenant</dt>
                  <dd className="mono">{data.tenantId}</dd>
                </div>
                <div>
                  <dt>Current actor</dt>
                  <dd className="mono">{data.actorId}</dd>
                </div>
                <div>
                  <dt>Data</dt>
                  <dd>
                    {data.syntheticData
                      ? "Synthetic development data"
                      : "Configured workspace data"}
                  </dd>
                </div>
              </dl>
              <div className="endpoint-block">
                <label>MCP endpoint</label>
                <div>
                  <code>{endpoint}</code>
                  <button
                    className="icon-button"
                    aria-label="Copy MCP endpoint"
                    onClick={() => copy(endpoint, "endpoint")}
                  >
                    {copied === "endpoint" ? (
                      <Check size={17} />
                    ) : (
                      <Copy size={17} />
                    )}
                  </button>
                </div>
              </div>
            </section>
            <section className="panel connection-details">
              <div className="section-heading">
                <h2>
                  <ShieldCheck size={19} />
                  Access boundary
                </h2>
              </div>
              <div className="connection-body">
                <p>
                  MCP tools expose read-only clinical context. Clinical edits
                  and signatures stay in this workspace.
                </p>
                <p>
                  The EHR runs as a separate service. Connecting it requires
                  configuration in your TOF deployment; this application does
                  not modify TOF-AI-APP.
                </p>
                <strong className="small-text">Current scopes</strong>
                <div className="scope-list">
                  {data.scopes.map((s) => (
                    <code key={s}>{s}</code>
                  ))}
                </div>
              </div>
            </section>
          </div>
          <section className="panel section-gap">
            <div className="section-heading">
              <div>
                <h2>Client configuration</h2>
                <p>
                  Adapt this example to your MCP client's connection format.
                </p>
              </div>
              <button
                className="button"
                onClick={() => copy(configuration, "config")}
              >
                {copied === "config" ? <Check size={16} /> : <Copy size={16} />}
                Copy example
              </button>
            </div>
            <div className="connection-body">
              <p>
                Use an MCP service credential supplied through your deployment's
                secret configuration. Replace the environment reference below
                using your client's supported secret mechanism.
              </p>
              <pre className="code-block">{configuration}</pre>
              <p className="muted small-text">
                The browser session token below is separate from the MCP service
                credential. Use the externally reachable endpoint when the
                client runs outside this machine.
              </p>
            </div>
          </section>
          <section className="panel section-gap">
            <div className="section-heading">
              <h2>Available tools</h2>
              <span className="muted">{data.tools.length} read-only tools</span>
            </div>
            <div className="tool-list">
              {data.tools.map((t) => (
                <div key={t.name}>
                  <code>{t.name}</code>
                  <p>{t.description}</p>
                </div>
              ))}
            </div>
          </section>
        </>
      ) : null}
      <ClinicalAiConnection
        revision={revision}
        canVerify={data?.scopes.includes("ehr:write") ?? false}
      />
      {copyError ? <ErrorMessage message={copyError} /> : null}
      <section className="panel section-gap session-panel">
        <div className="section-heading">
          <h2>
            <KeyRound size={18} />
            Browser session
          </h2>
          {sessionActive ? (
            <button className="text-button" onClick={disconnect}>
              Clear session
            </button>
          ) : null}
        </div>
        <form onSubmit={connect} className="connection-body">
          <p>
            For deployments requiring authentication, enter a bearer token
            provisioned by your administrator. It stays in memory and is cleared
            when this page reloads.
          </p>
          <div className="session-form">
            <Field label="Bearer token">
              <input
                aria-label="Browser bearer token"
                type="password"
                autoComplete="off"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Paste your session token"
                required
              />
            </Field>
            <button className="button primary" type="submit">
              Apply session
            </button>
          </div>
          {sessionActive ? (
            <p className="muted small-text" role="status">
              Session credential applied. The service status above confirms
              whether it is accepted.
            </p>
          ) : null}
        </form>
      </section>
    </>
  );
}
