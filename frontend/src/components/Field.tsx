import { useId, type ReactNode } from "react";

/** Labelled form control; the child receives the generated id via render prop. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: (id: string, describedBy?: string) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
      </label>
      {children(id, hintId)}
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-fg-muted">
          {hint}
        </p>
      )}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1>{title}</h1>
        {description && <p className="mt-1 text-fg-muted max-w-3xl">{description}</p>}
      </div>
      {actions}
    </header>
  );
}

/** Banner for features gated on backend contracts that do not exist yet. */
export function GapNotice({ children }: { children: ReactNode }) {
  return <p className="rounded-control border border-dashed border-border bg-surface-muted p-3 text-sm text-fg-muted">{children}</p>;
}
