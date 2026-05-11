import type { KnowledgeSearchPayload } from "../types";

type KnowledgeSearchPanelProps = {
  payload: KnowledgeSearchPayload | null;
  loading: boolean;
};

export function KnowledgeSearchPanel({ payload, loading }: KnowledgeSearchPanelProps) {
  const queryTokens = payload?.queryTokens ?? [];
  const sourceBreakdown = payload?.sourceBreakdown ?? [];
  const tagBreakdown = payload?.tagBreakdown ?? [];
  const results = payload?.results ?? [];

  return (
    <section className="result-box">
      <div className="section-header compact">
        <div>
          <div className="eyebrow">Knowledge Search</div>
          <h2>Direct Search Preview</h2>
        </div>
        <span className="pill">
          {loading ? "Searching..." : `${payload?.total ?? 0} hits`}
        </span>
      </div>

      <p className="service-note">Query tokens</p>
      <div className="badge-list">
        {queryTokens.length ? (
          queryTokens.map((term) => (
            <span className="badge" key={term}>
              {term}
            </span>
          ))
        ) : (
          <span className="empty-cell">Run a search to inspect tokenization.</span>
        )}
      </div>

      <div className="overview-columns">
        <div>
          <p className="service-note">Matching sources</p>
          <div className="overview-source-list">
            {sourceBreakdown.length ? (
              sourceBreakdown.map((source) => (
                <article className="overview-source-card" key={source.sourceId}>
                  <strong>{source.sourceName}</strong>
                  <span>{source.resultCount} hits</span>
                  <span>Best score {source.bestScore.toFixed(2)}</span>
                </article>
              ))
            ) : (
              <span className="empty-cell">Source coverage appears here after a search.</span>
            )}
          </div>
        </div>
        <div>
          <p className="service-note">Matching tags</p>
          <div className="badge-list">
            {tagBreakdown.length ? (
              tagBreakdown.map((bucket) => (
                <span className="badge badge-secondary" key={bucket.label}>
                  {bucket.label} · {bucket.count}
                </span>
              ))
            ) : (
              <span className="empty-cell">Tag overlap appears here after a search.</span>
            )}
          </div>
        </div>
      </div>

      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Document</th>
              <th>Source</th>
              <th>Score</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {results.length ? (
              results.map((result) => (
                <tr key={result.chunk.id}>
                  <td>
                    <strong>{result.chunk.documentTitle}</strong>
                    <div className="table-note">{result.chunk.content.slice(0, 110)}...</div>
                  </td>
                  <td>{result.sourceName}</td>
                  <td>{result.score.toFixed(2)}</td>
                  <td>{result.matchReason}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4} className="empty-cell">
                  No search preview yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
