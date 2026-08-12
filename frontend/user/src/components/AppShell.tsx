import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/browser", label: "Secure Browser" },
  { to: "/downloads", label: "Downloads" },
  { to: "/profile", label: "Profile / MFA" },
];

export function AppShell() {
  const { user, logout } = useAuth();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src="/favicon.svg" alt="" />
          <div>
            OpenRBI
            <span className="subtitle">USER PORTAL</span>
          </div>
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => (isActive ? "active" : "")}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div style={{ marginBottom: "8px" }}>{user?.username}</div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void logout()}>
            Log out
          </button>
        </div>
      </aside>
      <div className="main-area">
        <Outlet />
      </div>
    </div>
  );
}
