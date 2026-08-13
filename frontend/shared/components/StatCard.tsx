import type { ReactNode } from "react";

/** Formalizes the `.stat-card` markup every dashboard already used ad hoc
 * (label + primary value + optional smaller hint line) into one component,
 * so the KPI row stays visually consistent without each page repeating the
 * same three `<div>`s with slightly different inline font-sizes.
 */
export function StatCard({ label, value, hint }: { label: ReactNode; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="stat-card-hint">{hint}</div>}
    </div>
  );
}
