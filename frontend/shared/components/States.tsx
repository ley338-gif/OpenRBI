import type { ReactNode } from "react";

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading-block">
      <span className="spinner" /> {label}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function ErrorState({ children }: { children: ReactNode }) {
  return <div className="error-state">{children}</div>;
}
