import type { AdminDocumentRecord, KnowledgeBaseRecord } from "../types";

type DocumentTableProps = {
  documents: AdminDocumentRecord[];
  sources: KnowledgeBaseRecord[];
  selectedDocumentId?: string;
  onSelect?: (documentId: string) => void;
};

export function DocumentTable({
  documents,
  sources,
  selectedDocumentId,
  onSelect,
}: DocumentTableProps) {
  function sourceNameFor(sourceId: string): string {
    const source = sources.find((item) => item.kb_id === sourceId);
    return source?.name ?? sourceId;
  }

  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Admin Catalog</div>
          <h2>Knowledge Documents</h2>
        </div>
        <span className="pill">{documents.length} documents</span>
      </div>
      {onSelect ? (
        <p className="service-note">Click a document row to inspect its chunk boundaries below.</p>
      ) : null}
      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Knowledge Base</th>
              <th>Status</th>
              <th>Index</th>
              <th>Chunks</th>
              <th>Version</th>
              <th>Indexed</th>
            </tr>
          </thead>
          <tbody>
            {documents.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-cell">
                  No documents yet.
                </td>
              </tr>
            ) : (
              documents.map((document) => (
                <tr
                  key={document.doc_id}
                  className={onSelect ? "table-row-clickable" : undefined}
                  data-active={document.doc_id === selectedDocumentId}
                >
                  <td>
                    {onSelect ? (
                      <button
                        type="button"
                        className="table-select-button"
                        aria-pressed={document.doc_id === selectedDocumentId}
                        onClick={() => onSelect(document.doc_id)}
                      >
                        {document.title}
                      </button>
                    ) : (
                      document.title
                    )}
                  </td>
                  <td>{sourceNameFor(document.kb_id)}</td>
                  <td>{document.status}</td>
                  <td>{document.index_status}</td>
                  <td>{document.chunk_count}</td>
                  <td>v{document.version_no}</td>
                  <td>{document.indexed_at ? new Date(document.indexed_at).toLocaleString() : "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
