import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { Icons } from "@shared/components/Icons";
import { UserMenu } from "@shared/components/UserMenu";
import { HelpMenu } from "@shared/components/HelpMenu";
import { NotificationButton } from "@shared/components/NotificationButton";
import darkLogo from "@shared/logo-dm.png";

const HELP_LINKS = [
  { label: "Admin Guide", href: "/docs/admin-guide.md" },
  { label: "Policies", href: "/docs/policies.md" },
  { label: "Quarantine", href: "/docs/quarantine.md" },
  { label: "Troubleshooting", href: "/docs/troubleshooting.md" },
];

const NAV = [
  { label: "Overview", items: [{ to: "/", label: "Dashboard", end: true, icon: Icons.Dashboard }] },
  { label: "Users & access", items: [
    { to: "/users", label: "Users", icon: Icons.Users }, { to: "/groups", label: "Groups", icon: Icons.Groups },
    { to: "/sessions", label: "Sessions", icon: Icons.Sessions },
  ] },
  { label: "Browser security", items: [
    { to: "/policies", label: "Policies", icon: Icons.Shield }, { to: "/quarantine", label: "Quarantine", icon: Icons.Quarantine },
    { to: "/incidents", label: "Incidents", icon: Icons.Incident },
  ] },
  { label: "Infrastructure", items: [
    { to: "/workers", label: "Workers", icon: Icons.Worker }, { to: "/system", label: "System health", icon: Icons.System },
  ] },
  { label: "Administration", items: [
    { to: "/audit", label: "Audit log", icon: Icons.Audit }, { to: "/settings/ldap", label: "LDAP / identity", icon: Icons.Settings },
  ] },
];

const COLLAPSE_KEY = "openrbi_admin_sidebar_collapsed";

export function AppShell() {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [mobileOpen, setMobileOpen] = useState(false);

  function toggleCollapsed() {
    setCollapsed((v) => {
      localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1");
      return !v;
    });
  }

  return (
    <div className="app-shell">
      {mobileOpen && <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " mobile-open" : ""}`}>
        <div className="sidebar-brand">
          {collapsed && !mobileOpen ? (
            <img src="/favicon.png" alt="OpenRBI" />
          ) : (
            <div>
              <img className="sidebar-logo-full" src={darkLogo} alt="OpenRBI — Remote Browser Isolation" />
              <span className="subtitle">ADMIN PORTAL</span>
            </div>
          )}
        </div>
        <nav>
          {NAV.map((group) => (
            <div className="nav-group" key={group.label}>
              {(!collapsed || mobileOpen) && <div className="nav-group-label">{group.label}</div>}
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={"end" in item ? item.end : undefined} onClick={() => setMobileOpen(false)} className={({ isActive }) => (isActive ? "active" : "")}>
                  <item.icon />{(!collapsed || mobileOpen) && item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div className="main-area">
        <div className="topbar">
          <button
            type="button"
            className="icon-btn sidebar-toggle-btn"
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
            onClick={() => window.matchMedia("(max-width: 900px)").matches ? setMobileOpen(true) : toggleCollapsed()}
          >
            {collapsed ? <Icons.ChevronsRight /> : <Icons.ChevronsLeft />}
          </button>
          <span className="topbar-context">Administration</span>
          <div className="topbar-spacer" />
          <NotificationButton />
          <HelpMenu links={HELP_LINKS} />
          {user && <UserMenu username={user.username} role={user.role} profileTo="/profile" onLogout={() => void logout()} />}
        </div>
        <Outlet />
      </div>
    </div>
  );
}
