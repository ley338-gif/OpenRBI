import { Icons } from "./Icons";
import { useDropdown } from "../hooks/useDropdown";

/** Topbar notification entry point — deliberately not wired to any data.
 * There is no notifications API yet (no endpoint that could tell us "file
 * released", "session isolated", etc. as discrete, readable events aimed
 * at a specific user) — see docs/development.md's "Known gaps" note.
 * Building a bell that shows an invented unread count or demo entries
 * would be worse than not having one; this renders the UI slot honestly
 * empty so the affordance exists without a backend to fake it.
 */
export function NotificationButton() {
  const { open, setOpen, ref } = useDropdown<HTMLDivElement>();

  return (
    <div className="dropdown-menu" ref={ref}>
      <button
        type="button"
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Notifications"
        title="Notifications"
      >
        <Icons.Bell />
      </button>
      {open && (
        <div className="dropdown-panel wide" role="menu">
          <div className="empty-state" style={{ padding: "8px 4px" }}>
            No notifications yet. This isn't connected to live data — see
            docs/development.md for the tracked gap.
          </div>
        </div>
      )}
    </div>
  );
}
