import type { KnowledgeBaseRecord } from "../types";

type KnowledgeBaseSettingsForm = {
  name: string;
  description: string;
  retrievalMode: string;
  status: "ready" | "disabled";
};

type KnowledgeBaseSettingsPanelProps = {
  knowledgeBase: KnowledgeBaseRecord | null;
  form: KnowledgeBaseSettingsForm;
  loading: boolean;
  onChange: (patch: Partial<KnowledgeBaseSettingsForm>) => void;
  onSubmit: () => void;
};

function formatDate(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "-";
}

export function KnowledgeBaseSettingsPanel({
  knowledgeBase,
  form,
  loading,
  onChange,
  onSubmit,
}: KnowledgeBaseSettingsPanelProps) {
  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Admin Maintenance</div>
          <h2>Selected Knowledge Base</h2>
        </div>
        <span className="pill">
          {knowledgeBase ? `${knowledgeBase.status} · ${knowledgeBase.document_count} docs` : "No selection"}
        </span>
      </div>

      {!knowledgeBase ? (
        <p className="empty-cell">
          Select a knowledge base to update its operator-facing name, retrieval mode, status, and description.
        </p>
      ) : (
        <div className="result-stack">
          <div className="note-box">
            <strong>{knowledgeBase.name}</strong>
            <p className="service-note">
              {knowledgeBase.code} · {knowledgeBase.scene} · {knowledgeBase.language}
            </p>
          </div>

          <dl className="metric-grid">
            <div>
              <dt>Documents</dt>
              <dd>{knowledgeBase.document_count}</dd>
            </div>
            <div>
              <dt>Chunks</dt>
              <dd>{knowledgeBase.chunk_count}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDate(knowledgeBase.created_at)}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{formatDate(knowledgeBase.updated_at)}</dd>
            </div>
          </dl>

          <div className="inline-inputs">
            <label>
              <span>Name</span>
              <input value={form.name} onChange={(event) => onChange({ name: event.target.value })} />
            </label>
            <label>
              <span>Retrieval Mode</span>
              <input
                value={form.retrievalMode}
                onChange={(event) => onChange({ retrievalMode: event.target.value })}
              />
            </label>
          </div>

          <div className="inline-inputs">
            <label>
              <span>Status</span>
              <select
                value={form.status}
                onChange={(event) =>
                  onChange({ status: event.target.value as KnowledgeBaseSettingsForm["status"] })
                }
              >
                <option value="ready">ready</option>
                <option value="disabled">disabled</option>
              </select>
            </label>
            <label>
              <span>Code</span>
              <input value={knowledgeBase.code} readOnly />
            </label>
          </div>

          <label>
            <span>Description</span>
            <textarea
              rows={4}
              value={form.description}
              onChange={(event) => onChange({ description: event.target.value })}
            />
          </label>
          <p className="service-note">Route: PATCH /api/v1/admin/knowledge-bases/{`{kb_id}`}</p>
          <button type="button" className="ghost-button" onClick={onSubmit} disabled={loading}>
            {loading ? "Saving..." : "Save Knowledge Base Settings"}
          </button>
        </div>
      )}
    </section>
  );
}
