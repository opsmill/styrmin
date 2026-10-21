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

/**
 * The roles a role select offers, in display order, each with its label.
 *
 * Pass it to the select's `items` so that its trigger shows the label, not the
 * raw enum value, and render the select's options from it.
 */
export const ROLE_OPTIONS: ReadonlyArray<{ value: Role; label: string }> = (
  ["READ_ONLY", "READ_WRITE", "ADMIN"] as const
).map((role) => ({ value: role, label: roleLabel(role) }));
