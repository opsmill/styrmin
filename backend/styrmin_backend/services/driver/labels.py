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


def format_driver_version_label(
    *,
    version: str,
    content_hash: str | None,
    source_commit_sha: str | None,
) -> str:
    """Render a driver-version label as ``<version>@<short>``.

    Falls back to the bare ``version`` string when neither fingerprint is
    populated (only expected for legacy rows on dev databases predating
    the provenance backfill).

    When both fingerprints are set (not expected by invariant — a row is
    either ``source_type == "local"`` or ``source_type == "git"``),
    ``content_hash`` wins defensively.
    """

    fingerprint = content_hash or source_commit_sha
    if not fingerprint:
        return version
    return f"{version}@{fingerprint[:7]}"
