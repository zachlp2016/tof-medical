import { useEffect, useRef, useState } from "react";
import {
  Cpu,
  FileSearch,
  LoaderCircle,
  RefreshCw,
  ScanText,
  X,
} from "lucide-react";
import { api, useApi } from "./api";
import type {
  ClinicalReviewResult,
  ClinicalAiStatus,
  ReviewOperation,
  AiOperationStatus,
} from "./types";
import { Empty, ErrorMessage, Status } from "./ui";

function AiWarnings({ warnings }: { warnings: string[] }) {
  return warnings.length ? (
    <ul className="ai-warnings">
      {warnings.map((warning, index) => (
        <li key={`${index}-${warning}`}>{warning}</li>
      ))}
    </ul>
  ) : null;
}

function providerName(provider: string) {
  return provider === "utility-medium"
    ? "TOF AI service"
    : provider === "openmed"
      ? "OpenMed"
      : provider;
}

function verificationTime(value?: string) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      });
}

function operationMessage(operation: AiOperationStatus) {
  if (operation.state === "awaiting-credentials")
    return "Awaiting service credentials from your administrator.";
  if (operation.state === "unverified")
    return "Credentials configured. Verify the connection before reviewing clinical notes.";
  if (operation.ready)
    return operation.location === "remote"
      ? "Verified and ready for saved-note reviews."
      : "Local service ready.";
  return "This service is unavailable. Refresh status after the service is restored.";
}

export function ClinicalAiConnection({
  revision,
  canVerify,
}: {
  revision: number;
  canVerify: boolean;
}) {
  const { data, error, loading, reload } = useApi<ClinicalAiStatus>(
    "/ai/status",
    revision,
  );
  const [verifying, setVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState("");
  const [verificationMessage, setVerificationMessage] = useState("");
  function refreshStatus() {
    setVerificationError("");
    setVerificationMessage("");
    reload();
  }
  async function verify() {
    setVerifying(true);
    setVerificationError("");
    setVerificationMessage("");
    try {
      const verified = await api<ClinicalAiStatus>("/ai/verify", {
        method: "POST",
      });
      setVerificationMessage(
        verified.operations.entities.ready
          ? "TOF AI connection verified."
          : "Verification did not succeed. Review the service status below.",
      );
      reload();
    } catch (failure) {
      setVerificationError((failure as Error).message);
      reload();
    } finally {
      setVerifying(false);
    }
  }
  return (
    <section className="panel section-gap clinical-ai-connection">
      <div className="section-heading">
        <div>
          <h2>
            <Cpu size={19} />
            Clinical AI
          </h2>
          <p>Providers for clinical entity review and de-identification.</p>
        </div>
        <button
          className="button"
          onClick={refreshStatus}
          disabled={loading || verifying}
        >
          <RefreshCw size={15} className={loading ? "spin" : ""} />
          Refresh AI status
        </button>
      </div>
      <div className="connection-body">
        {verificationError ? (
          <ErrorMessage message={verificationError} />
        ) : null}
        {verificationMessage ? (
          <p role="status">{verificationMessage}</p>
        ) : null}
        {loading ? (
          <p role="status">Checking clinical AI services…</p>
        ) : error ? (
          <ErrorMessage message={error} retry={reload} />
        ) : data ? (
          <>
            <div className="ai-operation-list">
              {(["entities", "deidentify"] as const).map((name) => {
                const operation = data.operations?.[name];
                if (!operation)
                  return (
                    <div key={name}>
                      <h3>
                        {name === "entities"
                          ? "Clinical entity review"
                          : "De-identification"}
                      </h3>
                      <p>Service status unavailable.</p>
                    </div>
                  );
                const needsVerification =
                  name === "entities" &&
                  operation.location === "remote" &&
                  operation.configured &&
                  !operation.ready &&
                  operation.state !== "awaiting-credentials";
                const verifiedTime = verificationTime(operation.verifiedAt);
                return (
                  <div key={name}>
                    <div className="ai-operation-heading">
                      <h3>
                        {name === "entities"
                          ? "Clinical entity review"
                          : "De-identification"}
                      </h3>
                      <Status value={operation.state} />
                    </div>
                    <p className="ai-provider-name">
                      {providerName(operation.provider)} ·{" "}
                      {operation.location === "remote"
                        ? "Remote service"
                        : "Local service"}
                    </p>
                    <dl className="ai-model-list">
                      <div>
                        <dt>
                          {operation.location === "remote"
                            ? "Model alias"
                            : "Model"}
                        </dt>
                        <dd>
                          {operation.model ? (
                            <code>{operation.model.id}</code>
                          ) : (
                            "Model metadata unavailable"
                          )}
                          {operation.model?.revision ? (
                            <span>
                              Revision <code>{operation.model.revision}</code>
                            </span>
                          ) : null}
                          {operation.model?.servedModel && operation.model.servedModel !== operation.model.id ? (
                            <span>Reported model <code>{operation.model.servedModel}</code></span>
                          ) : null}
                        </dd>
                      </div>
                    </dl>
                    <p>{operationMessage(operation)}</p>
                    {verifiedTime ? (
                      <p className="small-text">Connection verified <time dateTime={operation.verifiedAt}>{verifiedTime}</time>.</p>
                    ) : null}
                    <AiWarnings warnings={operation.warnings} />
                    {needsVerification ? (
                      <div className="ai-verification">
                        {canVerify ? (
                          <button
                            className="button"
                            onClick={verify}
                            disabled={verifying}
                          >
                            {verifying ? (
                              <LoaderCircle size={15} className="spin" />
                            ) : (
                              <RefreshCw size={15} />
                            )}
                            {verifying
                              ? "Verifying connection…"
                              : "Verify connection"}
                          </button>
                        ) : (
                          <p>
                            A workspace user with write access must verify this
                            connection.
                          </p>
                        )}
                        <p className="small-text">
                          Verification sends a fixed synthetic check, with no
                          patient note.
                        </p>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <p className="small-text">
              {data.operations?.entities?.location === "remote"
                ? "Clinical entity review sends the saved note to the TOF AI service. "
                : "Clinical entity review uses the service shown above. "}
              Results require clinician review and do not update the chart.
            </p>
          </>
        ) : null}
      </div>
    </section>
  );
}
export function ClinicalTextReview({
  encounterId,
  version,
  dirty,
  saving,
  hasNote,
}: {
  encounterId: string;
  version: number;
  dirty: boolean;
  saving: boolean;
  hasNote: boolean;
}) {
  const status = useApi<ClinicalAiStatus>("/ai/status");
  const [operation, setOperation] = useState<ReviewOperation>();
  const [result, setResult] = useState<ClinicalReviewResult>();
  const [error, setError] = useState("");
  const request = useRef<
    { controller: AbortController; sequence: number } | undefined
  >(undefined);
  const sequence = useRef(0);

  // Results belong only to this saved snapshot. Editing, saving, switching
  // encounters, or closing the editor invalidates any in-flight request.
  useEffect(() => {
    sequence.current += 1;
    request.current?.controller.abort();
    request.current = undefined;
    setOperation(undefined);
    setResult(undefined);
    setError("");
    return () => {
      sequence.current += 1;
      request.current?.controller.abort();
      request.current = undefined;
    };
  }, [encounterId, version, dirty, saving]);

  function clear() {
    sequence.current += 1;
    request.current?.controller.abort();
    request.current = undefined;
    setOperation(undefined);
    setResult(undefined);
    setError("");
  }

  async function review(nextOperation: ReviewOperation) {
    if (
      dirty ||
      saving ||
      !hasNote ||
      !status.data?.operations?.[nextOperation]?.ready ||
      request.current
    )
      return;
    const controller = new AbortController();
    const currentSequence = ++sequence.current;
    request.current = { controller, sequence: currentSequence };
    setResult(undefined);
    setError("");
    setOperation(nextOperation);
    try {
      const reviewed = await api<ClinicalReviewResult>(
        `/encounters/${encounterId}/review`,
        {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({
            expectedVersion: version,
            operation: nextOperation,
          }),
        },
      );
      if (controller.signal.aborted || sequence.current !== currentSequence)
        return;
      if (
        reviewed.encounterId !== encounterId ||
        reviewed.encounterVersion !== version ||
        reviewed.operation !== nextOperation
      ) {
        throw new Error(
          "The response does not match this saved encounter. Run a new review.",
        );
      }
      setResult(reviewed);
    } catch (failure) {
      if (controller.signal.aborted || sequence.current !== currentSequence)
        return;
      setError((failure as Error).message);
    } finally {
      if (sequence.current === currentSequence) {
        request.current = undefined;
        setOperation(undefined);
      }
    }
  }

  const blocked =
    dirty || saving || !hasNote || status.loading || Boolean(operation);
  return (
    <section
      className="clinical-review"
      aria-labelledby="clinical-review-title"
    >
      <div className="clinical-review-heading">
        <div>
          <h3 id="clinical-review-title">
            <Cpu size={18} />
            Clinical text review
          </h3>
          <p>Review saved note version {version} with the selected service.</p>
        </div>
        <div className="ai-review-status">
          {status.loading ? (
            <span className="muted small-text">Checking services…</span>
          ) : null}
          <button
            type="button"
            className="icon-button"
            aria-label="Refresh clinical AI status"
            onClick={status.reload}
            disabled={status.loading || Boolean(operation)}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </div>
      <p className="review-context">
        Results require clinician review. Entity mentions do not establish
        diagnoses; de-identification may miss sensitive information.
      </p>
      {dirty ? (
        <p className="review-save-hint" role="status">
          Save draft before reviewing your latest changes.
        </p>
      ) : !hasNote ? (
        <p className="review-save-hint">
          Add and save clinical note text to start a review.
        </p>
      ) : null}
      {status.error ? (
        <ErrorMessage message={status.error} retry={status.reload} />
      ) : null}
      <div className="review-actions review-operation-actions">
        {(["entities", "deidentify"] as const).map((name) => {
          const service = status.data?.operations?.[name];
          const Icon = name === "entities" ? ScanText : FileSearch;
          return (
            <div className="review-operation" key={name}>
              <div className="review-operation-heading">
                <span>
                  {service ? providerName(service.provider) : "Service status"}
                </span>
                {service ? <Status value={service.state} /> : null}
              </div>
              {service ? (
                <p className="review-operation-model">
                  {service.model ? (
                    <>
                      <code>{service.model.id}</code> ·{" "}
                    </>
                  ) : null}
                  {service.location === "remote" ? "Remote" : "Local"}
                </p>
              ) : null}
              <button
                type="button"
                className="button"
                disabled={blocked || !service?.ready}
                onClick={() => review(name)}
              >
                <Icon size={16} />
                {name === "entities"
                  ? "Find clinical entities"
                  : "Preview de-identified text"}
              </button>
              {service?.location === "remote" ? (
                <p>
                  This sends the saved clinical note to{" "}
                  {providerName(service.provider)}.
                </p>
              ) : service ? (
                <p>Processed locally by {providerName(service.provider)}.</p>
              ) : null}
              {service && !service.ready ? (
                <p className="review-operation-unavailable">
                  {service.state === "unverified"
                    ? "Verify this service in Connections to enable review."
                    : operationMessage(service)}
                </p>
              ) : null}
              {service?.warnings.length ? (
                <AiWarnings warnings={service.warnings} />
              ) : null}
            </div>
          );
        })}
      </div>
      {operation ? (
        <div className="review-progress" role="status">
          <LoaderCircle size={18} className="spin" />
          <div>
            <strong>
              {operation === "entities"
                ? "Finding clinical entities…"
                : "Preparing de-identification preview…"}
            </strong>
            <span>
              {status.data?.operations?.[operation]?.location === "remote"
                ? "The saved note is being reviewed by the TOF AI service."
                : "The first local review can take up to two minutes while the model loads."}
            </span>
          </div>
          <button type="button" className="text-button" onClick={clear}>
            Cancel
          </button>
        </div>
      ) : null}
      {error ? <ErrorMessage message={error} /> : null}
      {result &&
      !dirty &&
      !saving &&
      result.encounterId === encounterId &&
      result.encounterVersion === version ? (
        <ReviewResult result={result} onClear={clear} />
      ) : null}
    </section>
  );
}

function ReviewResult({
  result,
  onClear,
}: {
  result: ClinicalReviewResult;
  onClear: () => void;
}) {
  const hasScores = result.entities.some(
    (entity) =>
      typeof entity.confidence === "number" &&
      Number.isFinite(entity.confidence),
  );
  return (
    <div className="review-result">
      <div className="review-result-heading">
        <h3>
          {result.operation === "entities"
            ? "Clinical entities to review"
            : "De-identification preview"}
        </h3>
        <button className="text-button" type="button" onClick={onClear}>
          <X size={14} />
          Clear result
        </button>
      </div>
      <p className="review-result-notice">
        Clinician review required. The chart is unchanged. This result clears
        when you edit or close the encounter.
      </p>
      <AiWarnings warnings={result.warnings} />
      {result.operation === "deidentify" ? (
        <>
          <p className="small-text muted">
            Inspect the full text for remaining identifiers before sharing or
            exporting it.
          </p>
          {result.redactedText ? (
            <pre
              className="redacted-preview"
              aria-label="De-identified text preview"
            >
              {result.redactedText}
            </pre>
          ) : (
            <Empty
              title="No text preview returned"
              detail="This result does not confirm that identifiers have been removed."
            />
          )}
        </>
      ) : result.entities.length ? (
        <>
          <div className="table-scroll">
            <table className="entity-table">
              <thead>
                <tr>
                  <th>Text</th>
                  <th>Label</th>
                  <th>Assertion</th>
                  {hasScores ? <th>Model score</th> : null}
                </tr>
              </thead>
              <tbody>
                {result.entities.map((entity, index) => (
                  <tr key={`${index}-${entity.start}-${entity.end}`}>
                    <td>{entity.text}</td>
                    <td>{entity.label}</td>
                    <td>{entity.assertion || "Not supplied"}</td>
                    {hasScores ? (
                      <td className="mono">
                        {typeof entity.confidence === "number" &&
                        Number.isFinite(entity.confidence)
                          ? `${(entity.confidence * 100).toFixed(1)}%`
                          : null}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small-text muted">
            {hasScores
              ? "Model scores do not establish clinical correctness. "
              : ""}
            Check each finding in the note's context.
          </p>
        </>
      ) : (
        <Empty
          title="No entities returned"
          detail="This does not confirm the absence of relevant clinical information."
        />
      )}
      <dl className="review-provenance">
        <div>
          <dt>Source</dt>
          <dd>Saved encounter version {result.encounterVersion}</dd>
        </div>
        <div>
          <dt>Service</dt>
          <dd>
            {providerName(result.provider)} ·{" "}
            {result.location === "remote" ? "Remote" : "Local"}
          </dd>
        </div>
        <div>
          <dt>{result.location === "remote" ? "Model alias" : "Model"}</dt>
          <dd>
            <code>{result.model.id}</code>
          </dd>
        </div>
        {result.model.revision ? (
          <div>
            <dt>Revision</dt>
            <dd>
              <code>{result.model.revision}</code>
            </dd>
          </div>
        ) : null}
        {result.model.servedModel && result.model.servedModel !== result.model.id ? (
          <div>
            <dt>Reported model</dt>
            <dd><code>{result.model.servedModel}</code></dd>
          </div>
        ) : null}
        <div>
          <dt>Processing time</dt>
          <dd>{(result.durationMs / 1000).toFixed(1)} seconds</dd>
        </div>
      </dl>
    </div>
  );
}
