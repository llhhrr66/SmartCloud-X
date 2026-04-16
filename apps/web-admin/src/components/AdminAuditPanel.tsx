import type { AdminAuditRecord } from "../types";

type AdminAuditPanelProps = {
  records: AdminAuditRecord[];
  loading: boolean;
  resourceType: string;
  action: string;
  operatorId: string;
  onResourceTypeChange: (value: string) => void;
  onActionChange: (value: string) => void;
  onOperatorIdChange: (value: string) => void;
};

function readStringField(record: AdminAuditRecord, field: string): string | null {
  const value = record.after_json?.[field] ?? record.before_json?.[field];
  return typeof value === "string" && value.trim() ? value : null;
}

function recordLabel(record: AdminAuditRecord): string {
  return (
    readStringField(record, "name") ??
    readStringField(record, "title") ??
    readStringField(record, "code") ??
    record.resource_id
  );
}

export function AdminAuditPanel({
  records,
  loading,
  resourceType,
  action,
  operatorId,
  onResourceTypeChange,
  onActionChange,
  onOperatorIdChange,
}: AdminAuditPanelProps) {
  return (
    <section className="panel">
      <div className="section-header">
        <div>
          <div className="eyebrow">Admin Audit Trail</div>
          <h2>Recent Write Events</h2>
        </div>
        <span className="pill">{loading ? "Loading..." : `${records.length} records`}</span>
      </div>

      <div className="inline-inputs">
        <label>
          <span>Resource Type</span>
          <select value={resourceType} onChange={(event) => onResourceTypeChange(event.target.value)}>
            <option value="">All resources</option>
            <option value="knowledge_base">Knowledge bases</option>
            <option value="knowledge_document">Knowledge documents</option>
          </select>
        </label>
        <label>
          <span>Action</span>
          <select value={action} onChange={(event) => onActionChange(event.target.value)}>
            <option value="">All actions</option>
            <option value="create">Create</option>
            <option value="update">Update</option>
            <option value="reindex">Reindex</option>
          </select>
        </label>
        <label>
          <span>Operator ID</span>
          <input
            value={operatorId}
            onChange={(event) => onOperatorIdChange(event.target.value)}
            placeholder="web-admin"
          />
        </label>
      </div>

      {records.length === 0 ? (
        <p className="empty-cell">No admin audit records match the current filters yet.</p>
      ) : (
        <div className="activity-list">
          {records.map((record) => (
            <article className="activity-item" key={record.audit_id}>
              <div className="activity-header">
                <div>
                  <strong>{recordLabel(record)}</strong>
                  <p className="service-note">
                    {record.resource_type} · {record.resource_id}
                  </p>
                </div>
                <span className="pill">
                  {record.action} · {record.operator_id}
                </span>
              </div>
              <p className="service-note">{new Date(record.created_at).toLocaleString()}</p>
              <p className="service-note">Reason: {record.reason}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
