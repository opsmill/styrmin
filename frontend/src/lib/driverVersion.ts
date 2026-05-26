/**
 * Driver-version label formatting for feature 013.
 *
 * Renders any application-driver-version reference as
 * `<version>@<short>` where `<short>` is the first 7 chars of the
 * populated provenance fingerprint -- `contentHash` for local source,
 * `sourceCommitSha` for git source. Both null falls back to the bare
 * version string (legacy rows only; not expected on rows created by
 * the new load path).
 *
 * When both fingerprints are set (not expected by invariant — a row is
 * either local or git source), `contentHash` wins defensively.
 */
export function formatDriverVersionLabel(v: {
  version: string;
  // Optional + nullable: matches the generated GraphQL types
  // (`contentHash?: string | null`) which mark fields as both
  // nullable and optional. Accepting `undefined` here lets callers
  // pass generated objects directly without unsafe casts.
  contentHash?: string | null;
  sourceCommitSha?: string | null;
}): string {
  const fingerprint = v.contentHash || v.sourceCommitSha;
  if (!fingerprint) return v.version;
  return `${v.version}@${fingerprint.slice(0, 7)}`;
}
