import type { ReactNode } from "react";

/** Standard header for every top-level page: title, one short explanatory
 * subtitle (never marketing copy), optional status/meta row, and a right-
 * aligned primary-action slot. Replaces each page rolling its own
 * `.flex-between` + inline spacing overrides.
 */
export function PageHeader({
  title,
  subtitle,
  meta,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
        {meta && <div className="page-header-meta">{meta}</div>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}
