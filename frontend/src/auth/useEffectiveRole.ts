import { useAuth } from "./AuthProvider";
import type { Role } from "@/generated/graphql";

/**
 * Returns the effective role of the current user, or `null` when unauthenticated.
 *
 * "Effective" reflects role-via-group elevation: a user whose direct `role` is
 * READ_ONLY but is a member of an ADMIN group has `effectiveRole === "ADMIN"`.
 */
export function useEffectiveRole(): Role | null {
  return useAuth().currentUser?.effectiveRole ?? null;
}
