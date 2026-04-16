import type { KnowledgeOverview } from "../types";

type OverviewPanelProps = {
  payload: KnowledgeOverview | null;
  loading: boolean;
};

export function OverviewPanel({ payload, loading }: OverviewPanelProps) {
  return (
    <section className="panel overview-panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Catalog Overview</div>
          <h2>Inventory Snapshot</h2>
        </div>
        <span className="pill">
          {loading ? "Refreshing..." : `${payload?.counts.documents ?? 0} docs`}
        </span>
      </div>

      <dl className="metric-grid overview-metrics">
        <div>
          <dt>Avg chunks / doc</dt>
          <dd>{payload?.averageChunksPerDocument ?? 0}</dd>
        </div>
        <div>
          <dt>Latest ingestion</dt>
          <dd>{payload?.latestIngestionAt ? new Date(payload.latestIngestionAt).toLocaleString() : "-"}</dd>
        </div>
      </dl>

      <div className="overview-columns">
        <div>
          <p className="service-note">Sources by kind</p>
          <div className="badge-list">
            {payload?.sourcesByKind.length ? (
              payload.sourcesByKind.map((bucket) => (
                <span className="badge" key={bucket.label}>
                  {bucket.label} · {bucket.count}
                </span>
              ))
            ) : (
              <span className="empty-cell">No source kinds recorded yet.</span>
            )}
          </div>
        </div>
        <div>
          <p className="service-note">Top tags</p>
          <div className="badge-list">
            {payload?.topTags.length ? (
              payload.topTags.map((bucket) => (
                <span className="badge badge-secondary" key={bucket.label}>
                  {bucket.label} · {bucket.count}
                </span>
              ))
            ) : (
              <span className="empty-cell">No tags recorded yet.</span>
            )}
          </div>
        </div>
      </div>

      <div className="overview-columns">
        <div>
          <p className="service-note">Document languages</p>
          <div className="badge-list">
            {payload?.documentLanguages.length ? (
              payload.documentLanguages.map((bucket) => (
                <span className="badge" key={bucket.label}>
                  {bucket.label} · {bucket.count}
                </span>
              ))
            ) : (
              <span className="empty-cell">No language data yet.</span>
            )}
          </div>
        </div>
        <div>
          <p className="service-note">Largest sources</p>
          <div className="overview-source-list">
            {payload?.largestSources.length ? (
              payload.largestSources.map((source) => (
                <article className="overview-source-card" key={source.sourceId}>
                  <strong>{source.sourceName}</strong>
                  <span>{source.kind}</span>
                  <span>
                    {source.documentCount} docs · {source.chunkCount} chunks
                  </span>
                </article>
              ))
            ) : (
              <span className="empty-cell">No source inventory yet.</span>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
