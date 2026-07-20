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

/**
 * "Latest / newest" is always scoped to the versions loaded into this Styrmin
 * instance — Styrmin can't see versions in the driver's source that haven't
 * been loaded, so a newer one may exist upstream. Shown as a tooltip on the
 * "Latest" badge and on the "newest loaded version" wording.
 */
export const LOADED_SCOPE_NOTE =
  "Newest version loaded into Styrmin. A newer one may exist in the driver's source — Styrmin only knows the versions you've loaded.";

/**
 * Order two driver versions "latest first" using the same rule the backend
 * applies to bind a deployment (CONTEXT.md "Latest-wins driver-version
 * resolution"): highest version string first (compared numerically so `"10"`
 * beats `"9"` and `"2.1.0"` beats `"2.0.3"`), ties broken by most-recent load
 * time. So `sort(compareVersionsLatestFirst)[0]` is the version new
 * deployments and upgrades resolve to — not merely the most recently loaded.
 *
 * KNOWN LIMITATION: this is an approximation of the backend rule. The backend
 * compares the highest *parseable* `spec.version` (unparseable strings rank
 * below parseable ones, final tie-break on row id); we use `localeCompare`
 * numeric on the raw string. For normal numeric/semver versions the two agree;
 * they can diverge for unparseable/mixed version strings. Follow-up: expose the
 * backend resolution (or a shared parser) so the badge is always identical to
 * what a deploy actually binds. Low priority.
 */
export function compareVersionsLatestFirst(
  a: { version: string; createdOn: string },
  b: { version: string; createdOn: string },
): number {
  const byVersion = b.version.localeCompare(a.version, undefined, {
    numeric: true,
    sensitivity: "base",
  });
  if (byVersion !== 0) return byVersion;
  return new Date(b.createdOn).getTime() - new Date(a.createdOn).getTime();
}

/**
 * The set of version *strings* that appear more than once within a driver's
 * version list. Only these need the `@<fingerprint>` disambiguator when shown;
 * a version whose number is unique reads cleaner as the bare number.
 */
export function collidingVersions(
  versions: ReadonlyArray<{ version: string }>,
): Set<string> {
  const counts = new Map<string, number>();
  for (const v of versions) {
    counts.set(v.version, (counts.get(v.version) ?? 0) + 1);
  }
  return new Set(
    [...counts].filter(([, n]) => n > 1).map(([version]) => version),
  );
}

/**
 * Display label for a driver version: the bare version number by default, or
 * `version@<fingerprint>` only when another loaded version shares the same
 * number (see {@link collidingVersions}). Keeps the common case scannable while
 * still disambiguating genuine collisions.
 */
export function displayDriverVersion(
  v: {
    version: string;
    contentHash?: string | null;
    sourceCommitSha?: string | null;
  },
  colliding: Set<string>,
): string {
  return colliding.has(v.version) ? formatDriverVersionLabel(v) : v.version;
}
