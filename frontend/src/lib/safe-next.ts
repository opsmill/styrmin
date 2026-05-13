/**
 * Open-redirect guard for `?next=…` query-parameter destinations.
 *
 * The login flow captures the pathname the user was trying to reach before
 * being bounced to /login, then restores it after a successful sign-in. An
 * attacker who crafts a phishing link like `/login?next=//evil.com/foo`
 * could otherwise turn our login screen into a redirector to an arbitrary
 * origin. To prevent that, we accept ONLY same-origin absolute paths that:
 *
 *   - start with a single `/` (i.e. begin with the path component),
 *   - do NOT begin with `//` (which the URL spec treats as protocol-relative
 *     and would route to a different host),
 *   - do NOT begin with `/\` (some browsers normalise back-slashes to
 *     forward-slashes, so `/\evil.com` is functionally identical to
 *     `//evil.com`),
 *   - are not absolute URLs (`http:`, `https:`, `javascript:`, `data:`, …),
 *   - are not the bare `/login` path (preserves the redirect → login loop).
 *
 * Inputs that fail any of the above resolve to the fallback `/` so the
 * caller can rely on `safeNext(maybeNext) ?? "/"` returning a definitely-safe
 * destination.
 */
export function safeNext(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (value.length === 0) return null;
  // Must be a same-origin absolute path: leading "/" followed by a single
  // non-slash, non-backslash character. Rejects "/", "//evil", "/\evil".
  if (!/^\/[^/\\]/.test(value)) return null;
  // Reject control characters and whitespace anywhere in the path — these
  // would not survive a clean redirect anyway, and they can hide tricks in
  // logs.
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f\s]/.test(value)) return null;
  // Bouncing back to /login would loop the user. Treat it as "no next".
  if (value === "/login" || value.startsWith("/login?")) return null;
  return value;
}
