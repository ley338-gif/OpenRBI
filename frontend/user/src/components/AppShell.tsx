import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@shared/auth/AuthContext";
import { Icons } from "@shared/components/Icons";
import { UserMenu } from "@shared/components/UserMenu";
import { HelpMenu } from "@shared/components/HelpMenu";
import { NotificationButton } from "@shared/components/NotificationButton";

const HELP_LINKS = [
  { label: "User Guide", href: "/docs/user-guide.md" },
  { label: "Troubleshooting", href: "/docs/troubleshooting.md" },
];

const NAV = [
  { to: "/", label: "Dashboard", end: true, icon: Icons.Dashboard },
  { to: "/browser", label: "Secure Browser", icon: Icons.Browser },
  { to: "/downloads", label: "Downloads", icon: Icons.Download },
  { to: "/profile", label: "Profile / MFA", icon: Icons.User },
];

const COLLAPSE_KEY = "openrbi_user_sidebar_collapsed";

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
              <span className="subtitle">USER PORTAL</span>
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
          <NotificationButton />
          <HelpMenu links={HELP_LINKS} />
          {user && <UserMenu username={user.username} role={user.role} profileTo="/profile" onLogout={() => void logout()} />}
        </div>
        <Outlet />
      </div>
    </div>
  );
}
