import { useState, useEffect } from "react";
import { Link, Outlet, useLocation } from "react-router";
import {
  Server,
  Package,
  HardDrive,
  Settings,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "sidebar-collapsed";

const navItems = [
  { label: "Environments", icon: Server, href: "/", exact: true },
  { label: "Drivers", icon: Package, href: "/drivers", exact: false },
  {
    label: "Backup Storage",
    icon: HardDrive,
    href: "/backup-storage-locations",
    exact: false,
  },
];

const bottomNavItems = [
  { label: "Settings", icon: Settings, href: "/settings", exact: false },
];

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem(STORAGE_KEY) === "true";
  });
  const location = useLocation();

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(collapsed));
  }, [collapsed]);

  function isActive(href: string, exact: boolean) {
    if (exact) return location.pathname === href;
    return location.pathname.startsWith(href);
  }

  function renderNavLink(item: (typeof navItems)[number]) {
    const active = isActive(item.href, item.exact);
    return (
      <Link
        key={item.href}
        to={item.href}
        title={collapsed ? item.label : undefined}
        className={cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          active
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground",
          collapsed && "justify-center px-0",
        )}
      >
        <item.icon className="h-4 w-4 shrink-0" />
        {!collapsed && <span>{item.label}</span>}
      </Link>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          "flex flex-col border-r bg-muted/30 transition-all duration-200",
          collapsed ? "w-14" : "w-60",
        )}
      >
        <div className="flex h-14 items-center border-b px-4">
          {!collapsed && (
            <span className="text-sm font-semibold tracking-tight">
              Styrmin
            </span>
          )}
        </div>

        <nav className="flex-1 space-y-1 p-2">
          {navItems.map(renderNavLink)}
        </nav>

        <div className="border-t p-2">
          {bottomNavItems.map(renderNavLink)}
          <button
            onClick={() => setCollapsed((prev) => !prev)}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/50 hover:text-accent-foreground",
              collapsed && "justify-center px-0",
            )}
          >
            {collapsed ? (
              <PanelLeft className="h-4 w-4 shrink-0" />
            ) : (
              <>
                <PanelLeftClose className="h-4 w-4 shrink-0" />
                <span>Collapse</span>
              </>
            )}
          </button>
        </div>
      </aside>

      <div className="flex-1">
        <Outlet />
      </div>
    </div>
  );
}
