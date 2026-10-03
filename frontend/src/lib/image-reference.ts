/**
 * Image-reference grammar and `{{ app.version }}` substitution
 * (018-component-image-overrides, research D-006/D-007).
 *
 * A port of `backend/styrmin_backend/services/image_overrides/reference.py`.
 * Both test suites read `image-reference.vectors.json`, so keep the two in
 * step; the backend stays the authority and re-validates every write.
 */

export type ImageReferenceReason =
  | "grammar"
  | "missing_tag_or_digest"
  | "template_expression"
  | "after_substitution";

export interface ImageReferenceError {
  reason: ImageReferenceReason;
}

/** The version substituted when no real one applies (stored-value check). */
export const PLACEHOLDER_VERSION = "0";
const NAME_MAX_LENGTH = 255;

// ASCII whitespace only, like Python's re.ASCII `\s`; JS `\s` also matches U+00A0.
const WS = "[ \\t\\n\\r\\f\\v]*";
const TOKEN_SOURCE = `\\{\\{${WS}app\\.version${WS}\\}\\}`;

/** Matches one `{{ app.version }}` token (inner whitespace optional). Stateless (no `g`). */
export const APP_VERSION_TOKEN_RE = new RegExp(TOKEN_SOURCE);
const APP_VERSION_TOKEN_GLOBAL_RE = new RegExp(TOKEN_SOURCE, "g");

const TEMPLATE_MARKERS = ["{{", "}}", "{%", "%}"];

// No `u`/`i` flags, so `\w` stays [A-Za-z0-9_]; `$` without `m` anchors at the very end.
const ALPHANUMERIC = "[a-z0-9]+";
const PATH_COMPONENT = `${ALPHANUMERIC}(?:(?:[._]|__|-+)${ALPHANUMERIC})*`;
const DOMAIN_COMPONENT = "(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])";
const HOST = `(?:${DOMAIN_COMPONENT}(?:\\.${DOMAIN_COMPONENT})*|\\[[a-fA-F0-9:]+\\])`;
const NAME = `(?:${HOST}(?::[0-9]+)?/)?${PATH_COMPONENT}(?:/${PATH_COMPONENT})*`;
const TAG = "\\w[\\w.-]{0,127}";
const DIGEST =
  "[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,}";
const REFERENCE_RE = new RegExp(
  `^(?<name>${NAME})(?::(?<tag>${TAG}))?(?:@(?<digest>${DIGEST}))?$`,
);

/** Replace every `{{ app.version }}` token with `version`, inserted literally. */
export function substituteAppVersion(ref: string, version: string): string {
  return ref.replace(APP_VERSION_TOKEN_GLOBAL_RE, () => version);
}

/** Whether `ref` carries at least one `{{ app.version }}` token. */
export function hasAppVersionToken(ref: string): boolean {
  return APP_VERSION_TOKEN_RE.test(ref);
}

function checkResolved(resolved: string): ImageReferenceReason | null {
  if (TEMPLATE_MARKERS.some((marker) => resolved.includes(marker))) {
    return "template_expression";
  }
  const match = REFERENCE_RE.exec(resolved);
  const groups = match?.groups;
  if (!groups || groups.name.length > NAME_MAX_LENGTH) return "grammar";
  if (groups.tag === undefined && groups.digest === undefined) {
    return "missing_tag_or_digest";
  }
  return null;
}

/**
 * Validate `ref` after substituting `version` (placeholder `"0"` by default,
 * as the backend's `validate_stored_reference` does). Returns `null` when
 * valid. Checks run in order: template expressions, grammar, tag/digest; a
 * token reference valid with the placeholder but not with `version` fails
 * with `after_substitution`.
 */
export function validateImageReference(
  ref: string,
  version: string = PLACEHOLDER_VERSION,
): ImageReferenceError | null {
  const reason = checkResolved(substituteAppVersion(ref, version));
  if (reason === null) return null;
  if (
    hasAppVersionToken(ref) &&
    version !== PLACEHOLDER_VERSION &&
    checkResolved(substituteAppVersion(ref, PLACEHOLDER_VERSION)) === null
  ) {
    return { reason: "after_substitution" };
  }
  return { reason };
}

const MESSAGES: Record<ImageReferenceReason, string> = {
  grammar:
    "Not a valid image reference (expected [registry[:port]/]name[:tag][@digest] with a lowercase name).",
  missing_tag_or_digest:
    'No tag or digest: add ":<tag>", "@sha256:<digest>", or ":{{ app.version }}".',
  template_expression:
    "Contains a template expression; only {{ app.version }} is substituted.",
  after_substitution:
    "Does not resolve to a valid image reference for this application version.",
};

/** Inline error text for a reason, worded like the backend's INVALID_IMAGE_REFERENCE messages. */
export function imageReferenceMessage(reason: ImageReferenceReason): string {
  return MESSAGES[reason];
}
