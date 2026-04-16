import type { FileImportPayload, FileImportPreviewItem, FileImportPreviewPayload } from "../types";

type FileImportPanelProps = {
  preview: FileImportPreviewPayload | null;
  importState: FileImportPayload | null;
  previewLoading: boolean;
  importLoading: boolean;
  selectedKnowledgeBaseId: string;
  adminDocumentLoading: boolean;
  adminDocumentFileId: string | null;
  onCreateAdminDocument: (item: FileImportPreviewItem) => void;
};

export function FileImportPanel({
  preview,
  importState,
  previewLoading,
  importLoading,
  selectedKnowledgeBaseId,
  adminDocumentLoading,
  adminDocumentFileId,
  onCreateAdminDocument,
}: FileImportPanelProps) {
  const previewSummary = `${preview?.importableFiles ?? 0}/${preview?.matchedFiles ?? 0} ready`;
  const importSummary = `${importState?.importedFiles ?? 0} imported · ${importState?.reusedFiles ?? 0} reused`;

  return (
    <div className="result-stack">
      <section className="result-box">
        <div className="section-header compact">
          <div>
            <div className="eyebrow">Filesystem Preview</div>
            <h2>Batch Candidate Files</h2>
          </div>
          <span className="pill">{previewLoading ? "Scanning..." : previewSummary}</span>
        </div>
        <p className="service-note">
          {preview?.importRoot
            ? `Import root: ${preview.importRoot}`
            : "Preview a directory to inspect markdown/text files before ingestion."}
        </p>
        <p className="service-note">
          When a target KB is selected, ready files can also be promoted through the admin document-create
          route for audit-backed validation.
        </p>
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Title</th>
                <th>Type</th>
                <th>Size</th>
                <th>Status</th>
                <th>Admin Route</th>
              </tr>
            </thead>
            <tbody>
              {preview?.items.length ? (
                preview.items.map((item) => (
                  <tr key={item.path}>
                    <td>{item.path}</td>
                    <td>{item.title}</td>
                    <td>{item.extension}</td>
                    <td>{item.sizeBytes} bytes</td>
                    <td>{item.importable ? "ready" : item.note ?? "blocked"}</td>
                    <td>
                      <button
                        type="button"
                        className="table-inline-button"
                        disabled={!selectedKnowledgeBaseId || !item.importable || adminDocumentLoading}
                        onClick={() => onCreateAdminDocument(item)}
                      >
                        {adminDocumentLoading && adminDocumentFileId === item.path
                          ? "Creating..."
                          : !item.importable
                            ? "Blocked"
                          : selectedKnowledgeBaseId
                            ? "Create Document"
                            : "Select KB"}
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="empty-cell">
                    No preview yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="result-box">
        <div className="section-header compact">
          <div>
            <div className="eyebrow">Filesystem Import</div>
            <h2>Latest Batch Result</h2>
          </div>
          <span className="pill">{importLoading ? "Importing..." : importSummary}</span>
        </div>
        {importState ? (
          <div className="note-box">
            Processed {importState.processedFiles} files into source {importState.source.name};
            {` ${importState.failedFiles} failed.`}
          </div>
        ) : null}
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Title</th>
                <th>Status</th>
                <th>Chunks</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {importState?.results.length ? (
                importState.results.map((result) => (
                  <tr key={`${result.path}-${result.status}`}>
                    <td>{result.path}</td>
                    <td>{result.title}</td>
                    <td>{result.status}</td>
                    <td>{result.chunksCreated}</td>
                    <td>{result.warning ?? result.error ?? "-"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="empty-cell">
                    No filesystem import run yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
