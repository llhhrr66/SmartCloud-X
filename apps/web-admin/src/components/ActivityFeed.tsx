import type { DocumentRecord, IngestionJob, SourceRecord } from "../types";

type ActivityFeedProps = {
  ingestions: IngestionJob[];
  sources: SourceRecord[];
  documents: DocumentRecord[];
};

export function ActivityFeed({ ingestions, sources, documents }: ActivityFeedProps) {
  function sourceNameFor(sourceId: string): string {
    const source = sources.find((item) => item.id === sourceId);
    return source?.name ?? sourceId;
  }

  function documentTitleFor(documentId: string): string {
    const document = documents.find((item) => item.id === documentId);
    return document?.title ?? documentId;
  }

  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Ingestion Activity</div>
          <h2>Recent Jobs</h2>
        </div>
        <span className="pill">{ingestions.length} jobs</span>
      </div>
      {ingestions.length === 0 ? (
        <p className="empty-cell">No ingestion jobs recorded yet.</p>
      ) : (
        <div className="activity-list">
          {ingestions.map((job) => (
            <article className="activity-item" key={job.id}>
              <div className="activity-header">
                <div>
                  <strong>{sourceNameFor(job.sourceId)}</strong>
                  <p className="service-note">Document: {documentTitleFor(job.documentId)}</p>
                </div>
                <span className="pill">
                  {job.status} · {job.chunksCreated} chunks
                </span>
              </div>
              <p className="service-note">
                {new Date(job.completedAt).toLocaleString()} · {job.documentsReceived} document received
              </p>
              {job.warnings.length > 0 ? (
                <p className="warning-note">{job.warnings.join(", ")}</p>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
