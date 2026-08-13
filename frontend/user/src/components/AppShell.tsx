import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { Icons } from "@shared/components/Icons";
import { UserMenu } from "@shared/components/UserMenu";
import { HelpMenu } from "@shared/components/HelpMenu";
import { NotificationButton } from "@shared/components/NotificationButton";
import darkLogo from "@shared/logo-dm.png";

const HELP_LINKS = [
  { label: "User Guide", href: "/docs/user-guide.md" },
  { label: "Troubleshooting", href: "/docs/troubleshooting.md" },
];

const NAV = [
  { to: "/", label: "Dashboard", end: true, icon: Icons.Dashboard },
  { to: "/browser", label: "Secure Browser", icon: Icons.Browser },
  { to: "/downloads", label: "Downloads", icon: Icons.Download },
  { to: "/profile", label: "Profile & Security", icon: Icons.User },
];

const COLLAPSE_KEY = "openrbi_user_sidebar_collapsed";

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
              <span className="subtitle">USER PORTAL</span>
            </div>
          )}
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} onClick={() => setMobileOpen(false)} className={({ isActive }) => (isActive ? "active" : "")}>
              <item.icon />
              {(!collapsed || mobileOpen) && item.label}
            </NavLink>
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
          <span className="topbar-context">User portal</span>
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
