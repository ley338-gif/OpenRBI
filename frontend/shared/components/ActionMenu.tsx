import type { ReactNode } from "react";
import { useDropdown } from "../hooks/useDropdown";

export interface ActionMenuItem {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
}

/** A "⋯" row-action menu — for rows with more actions than can reasonably
 * sit as individual buttons. Deliberately NOT used to hide a row's single
 * most important action (section 23: never bury the primary action);
 * callers should keep that one as its own visible button and put the rest
 * here.
 */
export function ActionMenu({ items, label = "Actions" }: { items: ActionMenuItem[]; label?: string }) {
  const { open, setOpen, ref } = useDropdown<HTMLDivElement>();

  return (
    <div className="dropdown-menu" ref={ref}>
      <button
        type="button"
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
      >
        ⋯
      </button>
      {open && (
        <div className="dropdown-panel" role="menu">
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className={item.danger ? "danger" : ""}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.icon} {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
