import { useState, useEffect } from "react";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  LayoutGrid,
  Layers,
  HardDrive,
  Server,
  Settings,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/use-theme";
import { useAuth } from "@/auth/AuthProvider";
import { HeaderUserMenu } from "@/components/HeaderUserMenu";
import { ThemeToggle } from "@/components/ThemeToggle";
import { IfRole } from "@/auth/IfRole";
import type { Role } from "@/generated/graphql";

const STORAGE_KEY = "sidebar-collapsed";

const navItems = [
  { label: "Environments", icon: LayoutGrid, href: "/", exact: true },
  { label: "Drivers", icon: Layers, href: "/drivers", exact: false },
];

// Users/Groups admin surfaces are reachable from the Settings page,
// not the top-level sidebar — see SettingsPage. Settings itself is
// admin-only after the Cluster section moved to the dedicated Clusters
// page; the Settings entry below is gated by `minRole`.
interface BottomNavItem {
  label: string;
  icon: typeof Settings;
  href: string;
  exact: boolean;
  minRole?: Role;
}

const bottomNavItems: BottomNavItem[] = [
  { label: "Clusters", icon: Server, href: "/clusters", exact: false },
  {
    label: "Backup Storage",
    icon: HardDrive,
    href: "/backup-storage-locations",
    exact: false,
  },
  {
    label: "Settings",
    icon: Settings,
    href: "/settings",
    exact: false,
    minRole: "ADMIN",
  },
];

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem(STORAGE_KEY) === "true";
  });
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { theme } = useTheme();
  const { currentUser, logout } = useAuth();
  const isLoginRoute = pathname === "/login";

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(collapsed));
  }, [collapsed]);

  function isActive(href: string, exact: boolean) {
    if (exact) return pathname === href;
    return pathname.startsWith(href);
  }

  function renderNavLink(item: (typeof navItems)[number]) {
    const active = isActive(item.href, item.exact);
    return (
      <Link
        key={item.href}
        to={item.href}
        title={collapsed ? item.label : undefined}
        className={cn(
          "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors",
          active
            ? "bg-primary text-primary-foreground"
            : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          collapsed && "justify-center px-2",
        )}
      >
        <item.icon className="h-[18px] w-[18px] shrink-0" />
        {!collapsed && <span>{item.label}</span>}
      </Link>
    );
  }

  function renderBottomNavLink(item: BottomNavItem) {
    const link = renderNavLink(item);
    if (item.minRole) {
      return (
        <IfRole key={item.href} minimum={item.minRole}>
          {link}
        </IfRole>
      );
    }
    return link;
  }

  if (isLoginRoute) {
    // Login is a full-screen experience; we still render the shared top
    // header so global affordances (the theme toggle) remain visible, but the
    // navigation sidebar and the authenticated user menu are hidden.
    return (
      <div className="flex min-h-screen flex-col">
        <header
          className="flex h-12 items-center justify-end border-b border-border bg-background px-4"
          data-testid="app-header"
        >
          <ThemeToggle />
        </header>
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <aside
        className={cn(
          "flex flex-col border-r border-border bg-sidebar transition-all duration-200",
          collapsed ? "w-14" : "w-60",
        )}
      >
        {/* Logo */}
        <div className="px-3 py-4">
          <Link
            to="/"
            aria-label="Styrmin home"
            title={collapsed ? "Styrmin home" : undefined}
            className="flex items-center gap-2.5 rounded-lg p-1"
          >
            {!collapsed && (
              <>
                <div
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-lg text-[13px] font-bold text-white",
                    theme === "dark" ? "bg-primary" : "bg-foreground",
                  )}
                >
                  S
                </div>
                <span className="text-[15px] font-semibold tracking-tight text-sidebar-foreground">
                  Styrmin
                </span>
              </>
            )}
            {collapsed && (
              <div
                className={cn(
                  "mx-auto flex h-7 w-7 items-center justify-center rounded-lg text-[13px] font-bold text-white",
                  theme === "dark" ? "bg-primary" : "bg-foreground",
                )}
              >
                S
              </div>
            )}
          </Link>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3">
          {navItems.map(renderNavLink)}
        </nav>

        {/* Bottom */}
        <div className="space-y-1 border-t border-border px-3 py-2">
          {bottomNavItems.map(renderBottomNavLink)}
          <button
            onClick={() => setCollapsed((prev) => !prev)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
              collapsed && "justify-center px-2",
            )}
          >
            {collapsed ? (
              <PanelLeft className="h-[18px] w-[18px] shrink-0" />
            ) : (
              <>
                <PanelLeftClose className="h-[18px] w-[18px] shrink-0" />
                <span>Collapse</span>
              </>
            )}
          </button>
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header
          className="flex h-12 items-center justify-end gap-3 border-b border-border bg-background px-4"
          data-testid="app-header"
        >
          <ThemeToggle />
          {currentUser !== null && (
            <HeaderUserMenu user={currentUser} onLogout={logout} />
          )}
        </header>
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
