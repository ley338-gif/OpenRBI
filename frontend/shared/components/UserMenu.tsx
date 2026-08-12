import { Link } from "react-router-dom";
import { Icons } from "./Icons";
import { useDropdown } from "../hooks/useDropdown";

function initialsOf(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

/** Topbar avatar + dropdown (Profile/MFA, Log out) shared by both portals.
 * Closes on outside click and Escape — the only two interactions this
 * needs, kept simple rather than pulling in a menu library for one widget.
 */
export function UserMenu({
  username,
  role,
  profileTo,
  onLogout,
}: {
  username: string;
  role: string;
  profileTo?: string;
  onLogout: () => void;
}) {
  const { open, setOpen, ref } = useDropdown<HTMLDivElement>();

  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="user-menu-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="avatar">{initialsOf(username)}</span>
        <span className="user-menu-label">
          {username}
          <span className="text-muted" style={{ display: "block", fontSize: "0.72rem" }}>
            {role}
          </span>
        </span>
        <Icons.ChevronDown width={14} height={14} />
      </button>
      {open && (
        <div className="user-menu-panel" role="menu">
          {profileTo && (
            <Link to={profileTo} role="menuitem" onClick={() => setOpen(false)}>
              <Icons.User width={16} height={16} /> Profile / MFA
            </Link>
          )}
          <button type="button" role="menuitem" onClick={onLogout}>
            <Icons.Logout width={16} height={16} /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
