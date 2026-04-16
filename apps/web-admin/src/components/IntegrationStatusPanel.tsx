import type { KnowledgeRuntimeSnapshot } from "../types";

type Props = {
  snapshot: KnowledgeRuntimeSnapshot | null;
  loading: boolean;
};

export function IntegrationStatusPanel({ snapshot, loading }: Props) {
  const integrations = snapshot?.integrations;
  const eventCounters: Record<string, number> = integrations?.eventCounters ?? {};
  const connectors = integrations
    ? [
        { label: "Raw storage", connector: integrations.rawStorage },
        { label: "Metadata", connector: integrations.metadataStore },
        { label: "Vector", connector: integrations.vectorStore },
        { label: "BM25", connector: integrations.bm25Store },
        { label: "Cache", connector: integrations.cache },
        { label: "Task queue", connector: integrations.taskQueue },
      ]
    : [];

  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Runtime Wiring</div>
          <h2>Connectors + Async Indexing</h2>
        </div>
        {integrations ? <span className="pill">{integrations.pendingEvents} queued events</span> : null}
      </div>
      {loading && !integrations ? <p>Loading runtime integration snapshot…</p> : null}
      {!loading && !integrations ? (
        <p>Runtime integration details will appear after the next snapshot refresh.</p>
      ) : null}
      {integrations ? (
        <>
          <div className="connector-grid">
            {connectors.map(({ label, connector }) => (
              <div key={label} className="connector-card">
                <strong>{label}</strong>
                <span>{connector.backend}</span>
                <span>{connector.configured ? "configured" : "local fallback"}</span>
                {connector.target ? <small>{connector.target}</small> : null}
                {connector.endpoint ? <small>{connector.endpoint}</small> : null}
              </div>
            ))}
          </div>
          <div className="inline-stat-row">
            <span className="badge">outbox: {integrations.outboxPath}</span>
            <span className="badge badge-secondary">raw mirror: {integrations.rawMirrorRoot}</span>
            <span className="badge badge-secondary">
              queued {eventCounters.queued ?? integrations.pendingEvents}
            </span>
            <span className="badge badge-secondary">
              processing {eventCounters.processing ?? 0}
            </span>
            <span className="badge badge-secondary">
              completed {eventCounters.completed ?? 0}
            </span>
          </div>
          <div className="section-header compact">
            <div>
              <strong>Recent outbox events</strong>
            </div>
          </div>
          {integrations.recentEvents.length === 0 ? (
            <p>No indexing events have been emitted yet.</p>
          ) : (
            <div className="overview-source-list">
              {integrations.recentEvents.map((event) => (
                <div key={event.eventId} className="overview-source-card">
                  <strong>
                    {event.operation} · {event.docId}
                  </strong>
                  <span>
                    {event.rawObject.storageKind} → {event.vectorTarget ?? "vector disabled"} /{" "}
                    {event.bm25Target ?? "bm25 disabled"}
                  </span>
                  <span>
                    {event.status} · queue {event.queueName} · {event.chunkCount} chunks ·{" "}
                    {new Date(event.createdAt).toLocaleString()}
                  </span>
                  {event.processorId ? <span>processor {event.processorId}</span> : null}
                  {typeof event.attemptCount === "number" ? (
                    <span>attempts {event.attemptCount}</span>
                  ) : null}
                  {event.lastError ? <span>last error: {event.lastError}</span> : null}
                  {event.connectorResults && event.connectorResults.length > 0 ? (
                    <div className="inline-stat-row">
                      {event.connectorResults.map((result) => (
                        <span key={`${event.eventId}-${result.connector}`} className="badge badge-secondary">
                          {result.connector}: {result.status}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
