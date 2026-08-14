import { useEffect, useRef, useState } from "react";
import { Icons } from "./Icons";

export interface AttachListItem {
  id: string;
  label: string;
  meta?: string;
}

/**
 * A search-and-add / removable-list widget for many-to-many links between
 * two entities (Group<->Policy today) — the "add this group to this
 * policy" pattern familiar from directory-service admin tools. No prior
 * component in this codebase did entity-to-entity linking (checked); this
 * is the one place that pattern lives, meant to be reused for any future
 * many-to-many admin relationship rather than rebuilt per page.
 */
export function AttachList({
  attached,
  onAdd,
  onRemove,
  onSearch,
  entityLabel,
  entityLabelPlural,
  placeholder,
  emptyLabel,
  busy,
}: {
  attached: AttachListItem[];
  onAdd: (id: string) => void | Promise<void>;
  onRemove: (id: string) => void | Promise<void>;
  onSearch: (query: string) => Promise<AttachListItem[]>;
  entityLabel: string;
  /** Defaults to `${entityLabel}s` — pass explicitly for irregular plurals (e.g. "policy" -> "policies"). */
  entityLabelPlural?: string;
  placeholder?: string;
  emptyLabel?: string;
  busy?: boolean;
}) {
  const plural = entityLabelPlural ?? `${entityLabel}s`;
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AttachListItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Debounced search — every keystroke would otherwise fire a request,
  // and typing "polic" would race "policy"'s response arriving after it.
  useEffect(() => {
    if (!query.trim()) {
      setResults(null);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = window.setTimeout(() => {
      onSearch(query.trim())
        .then((r) => {
          if (!cancelled) setResults(r);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, onSearch]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const attachedIds = new Set(attached.map((a) => a.id));
  const visibleResults = (results ?? []).filter((r) => !attachedIds.has(r.id));

  async function handleAdd(id: string) {
    await onAdd(id);
    setQuery("");
    setResults(null);
    setOpen(false);
  }

  return (
    <div className="attach-list" ref={containerRef}>
      <div className="attach-list-search">
        <label className="search-input">
          <Icons.Search width={16} height={16} />
          <input
            value={query}
            placeholder={placeholder ?? `Search ${plural} to add…`}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            disabled={busy}
            aria-label={`Search ${plural} to add`}
          />
        </label>
        {open && query.trim() && (
          <div className="attach-list-dropdown">
            {searching ? (
              <div className="attach-list-dropdown-item attach-list-dropdown-hint">Searching…</div>
            ) : visibleResults.length === 0 ? (
              <div className="attach-list-dropdown-item attach-list-dropdown-hint">No matching {plural}</div>
            ) : (
              visibleResults.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className="attach-list-dropdown-item"
                  onClick={() => void handleAdd(r.id)}
                  disabled={busy}
                >
                  <span className="attach-list-dropdown-label">
                    {r.label}
                    {r.meta && <small className="text-muted">{r.meta}</small>}
                  </span>
                  <span className="attach-list-add">+ Add</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {attached.length === 0 ? (
        <p className="text-muted attach-list-empty">{emptyLabel ?? `No ${plural} attached yet.`}</p>
      ) : (
        <ul className="attach-list-items">
          {attached.map((item) => (
            <li key={item.id} className="attach-list-item">
              <span className="attach-list-item-label">
                {item.label}
                {item.meta && <small className="text-muted">{item.meta}</small>}
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => void onRemove(item.id)}
                disabled={busy}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
