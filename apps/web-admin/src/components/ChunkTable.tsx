import type { ChunkRecord, DocumentRecord } from "../types";

type ChunkTableProps = {
  chunks: ChunkRecord[];
  selectedDocument: DocumentRecord | null;
  loading: boolean;
};

export function ChunkTable({ chunks, selectedDocument, loading }: ChunkTableProps) {
  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Chunk Inspection</div>
          <h2>Document Chunk Preview</h2>
        </div>
        <span className="pill">
          {loading ? "Loading..." : `${chunks.length} chunks`}
        </span>
      </div>
      <p className="service-note">
        {selectedDocument
          ? `Inspecting chunking output for ${selectedDocument.title}.`
          : "Select a document to inspect chunk boundaries, keywords, and tags."}
      </p>
      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Chunk</th>
              <th>Keywords</th>
              <th>Tags</th>
              <th>Tokens</th>
            </tr>
          </thead>
          <tbody>
            {!selectedDocument ? (
              <tr>
                <td colSpan={5} className="empty-cell">
                  No document selected yet.
                </td>
              </tr>
            ) : loading ? (
              <tr>
                <td colSpan={5} className="empty-cell">
                  Loading chunks...
                </td>
              </tr>
            ) : chunks.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty-cell">
                  No chunks returned for the selected document.
                </td>
              </tr>
            ) : (
              chunks.map((chunk) => (
                <tr key={chunk.id}>
                  <td>{chunk.ordinal}</td>
                  <td>
                    <strong>{chunk.documentTitle}</strong>
                    <div className="table-note">{chunk.content.slice(0, 180)}...</div>
                  </td>
                  <td>{chunk.keywords.join(", ") || "-"}</td>
                  <td>{chunk.tags.join(", ") || "-"}</td>
                  <td>{chunk.tokenEstimate}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
