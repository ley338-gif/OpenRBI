export interface TabItem {
  id: string;
  label: string;
}

/** Simple, uncontrolled-by-us tab strip — the caller owns `active` state
 * and renders whatever content belongs to it below. No routing, no
 * animation; just the visual pattern for splitting a long form (e.g. the
 * policy editor) into named sections instead of one huge scroll.
 */
export function Tabs({ tabs, active, onChange }: { tabs: TabItem[]; active: string; onChange: (id: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          className={active === tab.id ? "active" : ""}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
