export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="empty-state">
      <div className="w-12 h-12 mx-auto mb-3 rounded-full grid place-items-center"
        style={{ background: "radial-gradient(circle, rgba(83,167,255,0.3), rgba(40,145,255,0.1))" }}>
        <span className="text-lg" style={{ color: "var(--accent-frost)" }}>◇</span>
      </div>
      <h3 className="text-base font-semibold mb-1" style={{ color: "var(--text-primary)" }}>{title}</h3>
      {description && <p className="text-sm" style={{ color: "var(--text-muted)" }}>{description}</p>}
    </div>
  );
}
