import type { ReactNode } from "react";
import { AccessDenied } from "@/components/AccessDenied";
import { IfRole } from "./IfRole";

interface AdminOnlyProps {
  /** Short label identifying the gated area, shown on the denied page. */
  area: string;
  children: ReactNode;
}

/**
 * Wraps an admin-only page body. When the current effective role is below
 * ADMIN (including unauthenticated), renders the standard `<AccessDenied>`
 * page instead of the children. This replaces the older
 * `beforeLoad → redirect("/")` pattern, which silently bounced users
 * without explanation.
 *
 * Unauthenticated users never see this wrapper in practice because the
 * root route's `beforeLoad` guard redirects them to `/login` first.
 */
export function AdminOnly({ area, children }: AdminOnlyProps) {
  return (
    <IfRole
      minimum="ADMIN"
      fallback={<AccessDenied area={area} requiredRole="ADMIN" />}
    >
      {children}
    </IfRole>
  );
}
