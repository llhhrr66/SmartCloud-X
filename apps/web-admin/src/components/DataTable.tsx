import type { ReactNode } from "react";

export function DataTable<T>({ columns, rows, keyOf, empty }: {
  columns: Array<{ key: string; title: string; render: (row: T) => ReactNode }>;
  rows: T[];
  keyOf: (row: T, index: number) => string;
  empty?: ReactNode;
}) {
  if (rows.length === 0) {
    return <div className="empty-inline">{empty ?? "暂无数据"}</div>;
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>{columns.map((column) => <th key={column.key}>{column.title}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={keyOf(row, index)}>
              {columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
