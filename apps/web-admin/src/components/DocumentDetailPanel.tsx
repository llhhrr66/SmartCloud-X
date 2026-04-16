import type { AdminAsyncJob, AdminDocumentDetailPayload } from "../types";

type DocumentDetailPanelProps = {
  detail: AdminDocumentDetailPayload | null;
  latestJob: AdminAsyncJob | null;
  loading: boolean;
  jobLoading: boolean;
  confirmToken: string;
  onConfirmTokenChange: (value: string) => void;
  onReindex: () => void;
  reindexLoading: boolean;
};

function formatDate(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "-";
}

export function DocumentDetailPanel({
  detail,
  latestJob,
  loading,
  jobLoading,
  confirmToken,
  onConfirmTokenChange,
  onReindex,
  reindexLoading,
}: DocumentDetailPanelProps) {
  const document = detail?.document;
  const chunkStats = detail?.chunk_stats;

  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Admin Maintenance</div>
          <h2>Selected Document Detail</h2>
        </div>
        <span className="pill">
          {loading ? "Loading..." : document ? document.index_status : "No selection"}
        </span>
      </div>

      {!document ? (
        <p className="empty-cell">
          Select a knowledge document to inspect detail, latest job state, and reindex controls.
        </p>
      ) : (
        <div className="result-stack">
          <div className="note-box">
            <strong>{document.title}</strong>
            <p className="service-note">
              KB {document.kb_id} · {document.status} · v{document.version_no}
            </p>
          </div>

          <dl className="metric-grid">
            <div>
              <dt>Chunks</dt>
              <dd>{chunkStats?.chunk_count ?? 0}</dd>
            </div>
            <div>
              <dt>Tokens</dt>
              <dd>{chunkStats?.token_count ?? 0}</dd>
            </div>
            <div>
              <dt>Avg tokens / chunk</dt>
              <dd>{chunkStats?.average_tokens_per_chunk ?? 0}</dd>
            </div>
            <div>
              <dt>Indexed at</dt>
              <dd>{formatDate(document.indexed_at)}</dd>
            </div>
          </dl>

          <div className="overview-columns">
            <div className="overview-source-card">
              <strong>Document Source</strong>
              <span>file_id: {document.file_id ?? "-"}</span>
              <span>source_type: {document.source_type ?? "-"}</span>
              <span>source_uri: {document.source_uri ?? "-"}</span>
            </div>
            <div className="overview-source-card">
              <strong>Latest Async Job</strong>
              {jobLoading ? (
                <span>Loading job...</span>
              ) : latestJob ? (
                <>
                  <span>{latestJob.type}</span>
                  <span>
                    {latestJob.status} · {latestJob.progress}%
                  </span>
                  <span>finished: {formatDate(latestJob.finished_at)}</span>
                </>
              ) : (
                <span>No job recorded yet.</span>
              )}
            </div>
          </div>

          {detail?.error_message ? (
            <p className="warning-note">Error: {detail.error_message}</p>
          ) : null}

          <div className="inline-inputs">
            <label>
              <span>Selected Document</span>
              <input value={document.doc_id} readOnly />
            </label>
            <label>
              <span>Confirm Token</span>
              <input value={confirmToken} onChange={(event) => onConfirmTokenChange(event.target.value)} />
            </label>
          </div>
          <p className="service-note">
            The knowledge-service admin contract requires the confirm token to match
            <code>reindex:{`{doc_id}`}</code> for high-risk reindex actions.
          </p>
          <button
            type="button"
            className="ghost-button"
            onClick={onReindex}
            disabled={reindexLoading || !document.doc_id}
          >
            {reindexLoading ? "Reindexing..." : "Reindex Selected Document"}
          </button>
        </div>
      )}
    </section>
  );
}
