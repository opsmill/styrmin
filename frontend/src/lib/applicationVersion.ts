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
 * The PEP 440 version grammar (Appendix B of the specification), which is the
 * grammar of `packaging.version.Version`, the parser the server applies to the
 * application version. It matches `1.6.0`, `v1.6.0`, `1!1.6.0`, `1.6.0rc1`,
 * `1.6.0-rc.1`, `1.6.0.post1`, `1.6.0+build_5` and `2026.8.5`, and refuses
 * `latest`, `3f2a9c1`, `2024-10-01`, `1.2.3-ls45`, `7.1.0-alpine` and
 * `1.0.0-x.7.z.92`. Matching is case-insensitive, as in the server.
 *
 * Whether a version that parses falls inside the driver's range
 * (pre-releases usually do not) is the server's call.
 */
export const APPLICATION_VERSION_PATTERN = new RegExp(
  [
    "^v?",
    // epoch, release segment
    "(?:\\d+!)?\\d+(?:\\.\\d+)*",
    // pre-release
    "(?:[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?\\d*)?",
    // post release
    "(?:-\\d+|[-_.]?(?:post|rev|r)[-_.]?\\d*)?",
    // dev release
    "(?:[-_.]?dev[-_.]?\\d*)?",
    // local version
    "(?:\\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?$",
  ].join(""),
  "i",
);

/**
 * The value to validate and to send. The server's parser allows surrounding
 * whitespace but the server does not trim the value, so the form trims it.
 */
export function normalizeApplicationVersion(value: string): string {
  return value.trim();
}

export function isApplicationVersionShape(value: string): boolean {
  return APPLICATION_VERSION_PATTERN.test(normalizeApplicationVersion(value));
}

const GENERIC_MESSAGE = "Enter a valid application version such as 1.0.0";

/** Clauses whose version is itself inside the range, usable as an example. */
const INCLUSIVE_LOWER_BOUND = /^(?:>=|==|~=)\s*(\d+(?:\.\d+)*)/;

/** Exclusion clauses: exact (`!=1.5`, equal to `1.5.0`) or wildcard (`!=1.5.*`). */
const EXCLUSION = /^!=\s*(\d+(?:\.\d+)*)(\.\*)?$/;

/** Zero-pad a dotted numeric version to at least `length` components. */
function padVersion(version: string, length: number): string {
  const parts = version.split(".");
  while (parts.length < length) parts.push("0");
  return parts.join(".");
}

/** Whether a `!=` clause in the range rules out `candidate`. */
function isExcluded(candidate: string, clauses: string[]): boolean {
  return clauses.some((clause) => {
    const match = EXCLUSION.exec(clause);
    if (!match) return false;
    const excluded = match[1]!;
    if (match[2]) {
      // `!=1.5.*` excludes 1.5 and every 1.5.x.
      return candidate === excluded || candidate.startsWith(`${excluded}.`);
    }
    const width = Math.max(
      candidate.split(".").length,
      excluded.split(".").length,
    );
    return padVersion(candidate, width) === padVersion(excluded, width);
  });
}

/**
 * Pick a concrete version the user could type for a supported range, taken
 * from its inclusive lower bound and padded to three components
 * (`>=1.5,<2.0` → `1.5.0`). Returns `null` when the range has no inclusive
 * lower bound to borrow from (`<2.0`, `>1.0`, `!=1.2`), or when a `!=`
 * clause rules that bound back out (`>=1.5,<2.0,!=1.5.0`).
 */
export function exampleVersionForRange(range: string): string | null {
  const clauses = range.split(",").map((clause) => clause.trim());
  for (const clause of clauses) {
    const match = INCLUSIVE_LOWER_BOUND.exec(clause);
    if (!match) continue;
    const candidate = padVersion(match[1]!, 3);
    return isExcluded(candidate, clauses) ? null : candidate;
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
