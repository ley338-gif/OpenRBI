import type { ReactNode } from "react";

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading-block">
      <span className="spinner" /> {label}
    </div>
  );
}

/** Two ways to call this, both still supported: `<EmptyState>text</EmptyState>`
 * (unchanged, used where a one-liner is enough) or the structured form
 * (icon + title + one short line + optional CTA) for pages where an empty
 * list is common enough to deserve a proper empty state (section 42).
 */
export function EmptyState({
  children,
  icon,
  title,
  action,
}: {
  children?: ReactNode;
  icon?: ReactNode;
  title?: ReactNode;
  action?: ReactNode;
}) {
  if (!title) return <div className="empty-state">{children}</div>;
  return (
    <div className="empty-state empty-state-structured">
      {icon && <div className="empty-state-icon">{icon}</div>}
      <div className="empty-state-title">{title}</div>
      {children && <div className="empty-state-body">{children}</div>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}

export function ErrorState({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="error-state">
      <div>{children}</div>
      {action && <div style={{ marginTop: "12px" }}>{action}</div>}
    </div>
  );
}
