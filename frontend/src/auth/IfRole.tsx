import type { ReactNode } from "react";
import type { Role } from "@/generated/graphql";
import { useEffectiveRole } from "./useEffectiveRole";

const ROLE_RANK: Record<Role, number> = {
  READ_ONLY: 0,
  READ_WRITE: 1,
  ADMIN: 2,
};

export interface IfRoleProps {
  minimum: Role;
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * Render children when the current user's effective role is greater than or
 * equal to `minimum`. Otherwise render `fallback` (default: nothing).
 *
 * Comparison order: READ_ONLY < READ_WRITE < ADMIN.
 *
 * Unauthenticated users (no effective role) never satisfy the minimum.
 */
export function IfRole({
  minimum,
  children,
  fallback = null,
}: IfRoleProps) {
  const effective = useEffectiveRole();
  if (effective === null) {
    return <>{fallback}</>;
  }
  if (ROLE_RANK[effective] >= ROLE_RANK[minimum]) {
    return <>{children}</>;
  }
  return <>{fallback}</>;
}
