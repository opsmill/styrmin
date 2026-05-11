import { useNavigate } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import type { CurrentUser, Role } from "@/auth/AuthProvider";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const NAME_TRUNCATE_LIMIT = 20;

function truncateName(name: string): string {
  if (name.length <= NAME_TRUNCATE_LIMIT) return name;
  return name.slice(0, NAME_TRUNCATE_LIMIT - 1) + "…";
}

function roleBadgeVariant(
  role: Role,
): "default" | "secondary" | "destructive" | "outline" {
  switch (role) {
    case "ADMIN":
      return "default";
    case "READ_WRITE":
      return "secondary";
    case "READ_ONLY":
    default:
      return "outline";
  }
}

export interface HeaderUserMenuProps {
  user: CurrentUser;
  onLogout: () => Promise<void> | void;
}

export function HeaderUserMenu({ user, onLogout }: HeaderUserMenuProps) {
  const navigate = useNavigate();
  const displayName = truncateName(user.displayName);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "inline-flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        )}
        aria-label="User menu"
        data-testid="header-user-menu-trigger"
      >
        <span
          className="max-w-[160px] truncate"
          data-testid="header-user-display-name"
          title={user.displayName}
        >
          {displayName}
        </span>
        <Badge
          variant={roleBadgeVariant(user.effectiveRole)}
          data-testid="header-user-role-badge"
        >
          {user.effectiveRole}
        </Badge>
        <ChevronDown className="h-4 w-4 opacity-60" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[10rem]">
        <DropdownMenuItem
          data-testid="header-user-menu-profile"
          onClick={() => {
            // /profile is added in a later chunk (US4). Cast loose so this
            // component compiles before that route is registered.
            void navigate({ to: "/profile" } as Parameters<
              typeof navigate
            >[0]);
          }}
        >
          Profile
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          data-testid="header-user-menu-logout"
          onClick={() => {
            void onLogout();
          }}
        >
          Logout
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
