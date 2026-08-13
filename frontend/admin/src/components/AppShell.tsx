import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { Icons } from "@shared/components/Icons";
import { UserMenu } from "@shared/components/UserMenu";

const NAV = [
  { to: "/", label: "Dashboard", end: true, icon: Icons.Dashboard },
  { to: "/users", label: "Users", icon: Icons.Users },
  { to: "/groups", label: "Groups", icon: Icons.Groups },
  { to: "/sessions", label: "Sessions", icon: Icons.Sessions },
  { to: "/policies", label: "Policies", icon: Icons.Shield },
  { to: "/quarantine", label: "Quarantine", icon: Icons.Quarantine },
  { to: "/incidents", label: "Incidents", icon: Icons.Incident },
  { to: "/audit", label: "Audit", icon: Icons.Audit },
  { to: "/system", label: "System", icon: Icons.System },
  { to: "/settings/ldap", label: "LDAP", icon: Icons.Settings },
];

const COLLAPSE_KEY = "openrbi_admin_sidebar_collapsed";

export function AppShell() {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");

  function toggleCollapsed() {
    setCollapsed((v) => {
      localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1");
      return !v;
    });
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <div className="sidebar-brand">
          {collapsed ? (
            <img src="/favicon.png" alt="OpenRBI" />
          ) : (
            <div>
              <img className="sidebar-logo-full" src="/logo-compact.png" alt="OpenRBI — Remote Browser Isolation" />
              <span className="subtitle">ADMIN PORTAL</span>
            </div>
          )}
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => (isActive ? "active" : "")}>
              <item.icon />
              {!collapsed && item.label}
            </NavLink>
          ))}
        </nav>
        <button type="button" className="sidebar-collapse-btn" onClick={toggleCollapsed}>
          {collapsed ? <Icons.ChevronsRight /> : <Icons.ChevronsLeft />}
          {!collapsed && "Collapse"}
        </button>
      </aside>
      <div className="main-area">
        <div className="topbar">
          {user && <UserMenu username={user.username} role={user.role} profileTo="/profile" onLogout={() => void logout()} />}
        </div>
        <Outlet />
      </div>
    </div>
  );
}
