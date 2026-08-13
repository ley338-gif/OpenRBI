import type { ReactNode } from "react";

export interface DefinitionItem {
  label: ReactNode;
  value: ReactNode;
}

/** Formalizes the `.detail-grid` <dl> markup every detail page already
 * used ad hoc into one component with a plain `items` array, so adding or
 * reordering a field is a one-line change instead of hand-editing <dt>/<dd>
 * pairs.
 */
export function DefinitionList({ items }: { items: DefinitionItem[] }) {
  return (
    <dl className="detail-grid">
      {items.map((item, i) => (
        <div key={i}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
