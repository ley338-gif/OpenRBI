import type { ReactNode } from "react";

/** Formalizes the `.stat-card` markup every dashboard already used ad hoc
 * (label + primary value + optional smaller hint line) into one component,
 * so the KPI row stays visually consistent without each page repeating the
 * same three `<div>`s with slightly different inline font-sizes.
 */
export function StatCard({ label, value, hint, icon, action, tone = "primary", compact = false }: { label: ReactNode; value: ReactNode; hint?: ReactNode; icon?: ReactNode; action?: ReactNode; tone?: "primary" | "success" | "warning" | "danger" | "info"; compact?: boolean }) {
  return (
    <article className={`stat-card stat-card-${tone}${compact ? " stat-card-compact" : ""}`}>
      {icon && <div className="stat-card-icon" aria-hidden="true">{icon}</div>}
      <div className="stat-card-content">
        <div className="label">{label}</div>
        <div className="value">{value}</div>
        {hint && <div className="stat-card-hint">{hint}</div>}
        {action && <div className="stat-card-action">{action}</div>}
      </div>
    </article>
  );
}
