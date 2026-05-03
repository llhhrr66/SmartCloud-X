export function SkeletonRow({ cols = 4 }: { cols?: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-3.5 py-3">
          <div className="skeleton h-4 rounded" style={{ width: `${60 + Math.random() * 40}%` }} />
        </td>
      ))}
    </tr>
  );
}

export function SkeletonCard() {
  return (
    <div className="metric-card animate-pulse">
      <div className="skeleton h-3 w-20 rounded" />
      <div className="skeleton h-8 w-28 rounded mt-2" />
    </div>
  );
}

export function SkeletonPanel() {
  return (
    <div className="panel animate-pulse">
      <div className="skeleton h-5 w-32 rounded mb-4" />
      <div className="space-y-3">
        <div className="skeleton h-4 w-full rounded" />
        <div className="skeleton h-4 w-3/4 rounded" />
        <div className="skeleton h-4 w-1/2 rounded" />
      </div>
    </div>
  );
}
