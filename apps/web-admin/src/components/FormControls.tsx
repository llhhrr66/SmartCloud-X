import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

export function Field({ label, helper, className, children }: { label: string; helper?: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={"form-field" + (className ? " " + className : "")}>
      <span>{label}</span>
      {children}
      {helper && <small className="text-xs" style={{ color: "var(--text-muted)" }}>{helper}</small>}
    </label>
  );
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="control" {...props} />;
}

export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="control textarea" {...props} />;
}

export function SelectInput(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="control" {...props} />;
}

export function FormGrid({ children }: { children: React.ReactNode }) {
  return <div className="form-grid-2">{children}</div>;
}
