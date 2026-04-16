import type { HealthPayload } from "../types";

type HealthCardProps = {
  label: string;
  payload: HealthPayload | null;
  loading: boolean;
};

export function HealthCard({ label, payload, loading }: HealthCardProps) {
  const statusClass =
    payload?.status === "ok" && payload?.ready !== false ? "status-ok" : "status-pending";

  return (
    <section className="panel health-card">
      <div className="eyebrow">{label}</div>
      <h2>{payload?.service ?? "Waiting for service"}</h2>
      <p className={statusClass}>
        {loading ? "Checking..." : payload?.status ?? "Unavailable"}
      </p>
      {typeof payload?.ready === "boolean" ? (
        <p className="service-note">
          Readiness: <strong>{payload.ready ? "ready" : "not ready"}</strong>
        </p>
      ) : null}
      {payload?.counts ? (
        <dl className="metric-grid">
          {Object.entries(payload.counts).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {payload?.knowledgeServiceBaseUrl ? (
        <p className="service-note">Upstream: {payload.knowledgeServiceBaseUrl}</p>
      ) : null}
      {payload?.knowledgeServiceApiPrefix ? (
        <p className="service-note">Upstream API: {payload.knowledgeServiceApiPrefix}</p>
      ) : null}
      {payload?.requestTimeoutMs ? (
        <p className="service-note">Timeout: {payload.requestTimeoutMs} ms</p>
      ) : null}
      {payload?.dataPath ? <p className="service-note">Store: {payload.dataPath}</p> : null}
      {payload?.starterCatalogPath ? (
        <p className="service-note">Starter Catalog: {payload.starterCatalogPath}</p>
      ) : null}
      {payload?.auditPath ? <p className="service-note">Audit Log: {payload.auditPath}</p> : null}
      {payload?.importRoot ? <p className="service-note">Import Root: {payload.importRoot}</p> : null}
      {payload?.maxImportFiles ? (
        <p className="service-note">Max Batch Files: {payload.maxImportFiles}</p>
      ) : null}
      {payload?.corsAllowedOrigins?.length ? (
        <p className="service-note">
          CORS: {payload.corsAllowedOrigins.slice(0, 3).join(", ")}
          {payload.corsAllowedOrigins.length > 3 ? " …" : ""}
        </p>
      ) : null}
      {payload?.upstream ? (
        <div className="health-detail-list">
          <article className="overview-source-card">
            <strong>Upstream knowledge-service</strong>
            <span>Status: {payload.upstream.status}</span>
            <span>Reachable: {payload.upstream.reachable ? "yes" : "no"}</span>
            <span>Ready: {payload.upstream.ready ? "yes" : "no"}</span>
            {typeof payload.upstream.latencyMs === "number" ? (
              <span>Latency: {payload.upstream.latencyMs.toFixed(2)} ms</span>
            ) : null}
            {payload.upstream.error ? <span>Error: {payload.upstream.error}</span> : null}
          </article>
        </div>
      ) : null}
      {payload?.readinessChecks?.length ? (
        <div className="health-detail-list">
          {payload.readinessChecks.map((check) => (
            <article className="overview-source-card" key={check.name}>
              <strong>{check.name}</strong>
              <span>Status: {check.status}</span>
              <span>{check.detail}</span>
            </article>
          ))}
        </div>
      ) : null}
      {payload?.warnings?.length ? (
        <ul className="coverage-list">
          {payload.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
