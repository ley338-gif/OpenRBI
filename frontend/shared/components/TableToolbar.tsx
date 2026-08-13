import type { ReactNode } from "react";

/** Standard toolbar row above a data table: an optional search box, any
 * number of filter controls (selects, etc. — passed in as children of
 * `filters`), and a right-aligned primary action. Pages keep owning their
 * own filter state/options; this only standardizes the layout.
 */
export function TableToolbar({
  search,
  onSearchChange,
  searchPlaceholder = "Search…",
  searchListId,
  filters,
  onRefresh,
  actions,
}: {
  search?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  /** Optional id of a <datalist> rendered by the caller, for autocomplete
   * suggestions on the search box (e.g. Audit's known event types) —
   * suggestions only, never validated against by this component. */
  searchListId?: string;
  filters?: ReactNode;
  onRefresh?: () => void;
  actions?: ReactNode;
}) {
  return (
    <div className="table-toolbar">
      <div className="table-toolbar-controls">
        {onSearchChange && (
          <input
            className="table-toolbar-search"
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label="Search"
            list={searchListId}
          />
        )}
        {filters}
        {onRefresh && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRefresh}>
            Refresh
          </button>
        )}
      </div>
      {actions && <div style={{ display: "flex", gap: "8px" }}>{actions}</div>}
    </div>
  );
}
