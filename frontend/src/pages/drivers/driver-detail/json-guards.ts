/**
 * Shared type-guard helpers for the `components` JSON scalar on a driver
 * version.
 *
 * The GraphQL `components` field is typed as `unknown` on the TS side. Per
 * `specs/012-driver-detail-tabs/data-model.md`, callers must treat it as
 * untrusted JSON: only a plain object (not `null`, not an array) is a valid
 * component declaration, and within that, only entries whose VALUE is itself
 * a plain object count as a real component.
 *
 * Both `ComponentsTab` (which renders the rows) and `OverviewTab` (which
 * shows the count tile) MUST apply the same filter so the two tabs cannot
 * disagree about how many components a driver version declares.
 */
export function isPlainObject(
  value: unknown,
): value is Record<string, unknown> {
  return (
    value !== null &&
    value !== undefined &&
    typeof value === "object" &&
    !Array.isArray(value)
  );
}
