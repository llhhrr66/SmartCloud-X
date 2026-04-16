import type { KnowledgeBaseRecord } from "../types";

type SourceTableProps = {
  sources: KnowledgeBaseRecord[];
  selectedKnowledgeBaseId?: string;
  onSelect?: (knowledgeBaseId: string) => void;
};

export function SourceTable({ sources, selectedKnowledgeBaseId, onSelect }: SourceTableProps) {
  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Admin Inventory</div>
          <h2>Knowledge Bases</h2>
        </div>
        <span className="pill">{sources.length} KBs</span>
      </div>
      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Code</th>
              <th>Scene</th>
              <th>Language</th>
              <th>Docs</th>
              <th>Chunks</th>
              <th>Status</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {sources.length === 0 ? (
              <tr>
                <td colSpan={8} className="empty-cell">
                  No knowledge bases yet.
                </td>
              </tr>
            ) : (
              sources.map((source) => (
                <tr
                  key={source.kb_id}
                  className={onSelect ? "table-row-clickable" : undefined}
                  data-active={source.kb_id === selectedKnowledgeBaseId}
                >
                  <td>
                    {onSelect ? (
                      <button
                        type="button"
                        className="table-select-button"
                        aria-pressed={source.kb_id === selectedKnowledgeBaseId}
                        onClick={() => onSelect(source.kb_id)}
                      >
                        {source.name}
                      </button>
                    ) : (
                      source.name
                    )}
                  </td>
                  <td>{source.code}</td>
                  <td>{source.scene}</td>
                  <td>{source.language}</td>
                  <td>{source.document_count}</td>
                  <td>{source.chunk_count}</td>
                  <td>{source.status}</td>
                  <td>{source.updated_at ? new Date(source.updated_at).toLocaleString() : "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
