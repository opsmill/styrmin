import type { Role } from "@/generated/graphql";

/**
 * Human-readable label for a Role enum value.
 *
 * The raw enum (`READ_WRITE`, `READ_ONLY`, `ADMIN`) is appropriate for API
 * payloads but should never appear directly in user-facing UI — surfaces that
 * render a role to a human go through this helper instead. Keeping the
 * mapping in one place lets us re-skin every badge, dropdown, and detail row
 * with a single edit.
 */
export function roleLabel(role: Role | null | undefined): string {
  switch (role) {
    case "ADMIN":
      return "Admin";
    case "READ_WRITE":
      return "Read/write";
    case "READ_ONLY":
      return "Read-only";
    default:
      // Defensive fallback for unknown / null values — surface the raw input
      // rather than a misleading blank so it's obvious in screenshots when
      // the enum has drifted ahead of the UI.
      return String(role ?? "Unknown");
  }
}
