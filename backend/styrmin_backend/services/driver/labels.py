# A 4-line duplicate of this helper lives at cli/src/styrminctl/labels.py
# because the CLI is a separate package. Keep them in sync; the canonical
# rendering rule is specs/013-driver-fingerprint/contracts/sdk-cli-rendering.md.
"""Driver version label formatting.

Per spec 013 (Provenance fingerprint), every user-visible surface that
names an application driver version renders the label as ``<version>@<short>``
where ``<short>`` is the first 7 characters of the populated provenance
fingerprint -- ``content_hash`` for ``source_type == "local"``, or
``source_commit_sha`` for ``source_type == "git"``. The suffix is shown
unconditionally so labels stay stable when a second row appears.

This helper is the single source of truth for the rendering rule;
callers in :mod:`cli.styrminctl` and any future Python label renderers
MUST route through it.
"""

from loguru import logger


def format_driver_version_label(
    *,
    version: str,
    content_hash: str | None,
    source_commit_sha: str | None,
) -> str:
    """Render a driver-version label as ``<version>@<short>``.

    Falls back to the bare ``version`` string when neither fingerprint is
    populated (only expected for legacy rows on dev databases predating
    the provenance backfill). A warning is logged on the fallback path —
    on rows created by the spec-013 load path both columns are always set
    for the matching ``source_type``, so this fallback firing in
    production indicates a loader regression, a manual DB insert, or a
    missed backfill rather than expected behaviour.

    When both fingerprints are set (not expected by invariant — a row is
    either ``source_type == "local"`` or ``source_type == "git"``),
    ``content_hash`` wins defensively.
    """

    fingerprint = content_hash or source_commit_sha
    if not fingerprint:
        logger.warning(
            "ApplicationDriverVersion {version} rendered without a provenance "
            "fingerprint; this should not happen on rows created by the "
            "spec-013 load path. Check for legacy rows, manual inserts, or "
            "loader regressions.",
            version=version,
        )
        return version
    return f"{version}@{fingerprint[:7]}"


def short_fingerprint(
    *,
    content_hash: str | None,
    source_commit_sha: str | None,
) -> str | None:
    """Return the short (7-char) provenance fingerprint for a driver-version row.

    Spec 013 — used as the disambiguator on Prefect deployment tags so two
    same-``version`` reloads with different content do not clobber each
    other's workflow registration. Returns ``None`` for rows that have no
    provenance fingerprint at all (legacy rows pre-dating the backfill);
    Prefect lookups treat ``None`` as "omit the fingerprint tag" so the
    historical deployment continues to resolve.
    """
    fingerprint = content_hash or source_commit_sha
    if not fingerprint:
        return None
    return fingerprint[:7]
