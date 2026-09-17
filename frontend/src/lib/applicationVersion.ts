/**
 * Client-side rules for the deploy form's "Application Version" field.
 *
 * The field is free text. These helpers only check the *shape* of what the
 * user typed and phrase the error against the selected driver version's
 * `supportedVersions` range. Range enforcement itself (PEP 440 specifier
 * evaluation) stays on the server, which answers with the same range in its
 * `VALIDATION_ERROR` message.
 */

/**
 * Optional `v` prefix and numeric epoch (`v1.6.0`, `1!1.6.0`), a dotted
 * numeric core (`1`, `1.0`, `1.0.0`) and an optional pre-release / post /
 * build suffix (`2.0rc1`, `1.0.post1`, `1.0.0-beta+build.1`). Deliberately
 * permissive — it mirrors the forms the backend's version parser accepts so
 * a value the server would take is never blocked here. Whether such a value
 * falls inside the driver's range (pre-releases usually do not) is the
 * server's call.
 */
export const APPLICATION_VERSION_PATTERN =
  /^[vV]?(\d+!)?\d+(\.\d+)*([-+.]?[0-9A-Za-z][0-9A-Za-z.+-]*)?$/;

export function isApplicationVersionShape(value: string): boolean {
  return APPLICATION_VERSION_PATTERN.test(value);
}

const GENERIC_MESSAGE = "Enter a valid application version such as 1.0.0";

/** Clauses whose version is itself inside the range, usable as an example. */
const INCLUSIVE_LOWER_BOUND = /^(?:>=|==|~=)\s*(\d+(?:\.\d+)*)/;

/**
 * Pick a concrete version the user could type for a supported range, taken
 * from its inclusive lower bound and padded to three components
 * (`>=1.5,<2.0` → `1.5.0`). Returns `null` when the range has no inclusive
 * lower bound to borrow from (`<2.0`, `>1.0`, `!=1.2`).
 */
export function exampleVersionForRange(range: string): string | null {
  for (const clause of range.split(",")) {
    const match = INCLUSIVE_LOWER_BOUND.exec(clause.trim());
    if (!match) continue;
    const parts = match[1]!.split(".");
    while (parts.length < 3) parts.push("0");
    return parts.join(".");
  }
  return null;
}

/**
 * Field error for a value that does not look like a version. Quotes the
 * selected driver version's range when one is known so the user sees what is
 * accepted, and falls back to generic wording otherwise.
 */
export function invalidApplicationVersionMessage(
  range: string | null | undefined,
): string {
  const trimmed = range?.trim() ?? "";
  if (trimmed === "" || trimmed === "*") return GENERIC_MESSAGE;
  const example = exampleVersionForRange(trimmed);
  const base = `Enter a version in the supported range ${trimmed}`;
  return example ? `${base}, for example ${example}` : base;
}
