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


def driver_directory_of(*, source_type: str, source_path: str | None) -> str | None:
    """Return the driver directory of a driver-version row, or ``None``.

    Spec 028 — the driver directory of a git row is its ``source_path``
    (``None`` for a load from the repository root). A local row's
    ``source_path`` is a server path, not a driver directory, so it gives
    ``None``. Prefect lookups pass the result as ``driver_directory``.

    >>> driver_directory_of(source_type="git", source_path="drivers/a")
    'drivers/a'
    >>> driver_directory_of(source_type="local", source_path="/srv/drivers/a") is None
    True
    """
    if source_type == "git":
        return source_path
    return None


def action_directory_of(*, source_type: str, source_path: str | None) -> str | None:
    """Return the ``driver_directory`` of a driver version's action registrations and lookups.

    Spec 029 — ``source_path`` for ``git`` (the driver directory, or ``None``
    for a load from the repository root) and for ``local`` (the absolute path
    given on the server); ``None`` for any other source type. A local value
    starts with ``/`` and a git value never does, so the two cannot match.
    Unlike :func:`driver_directory_of`, which gives the GraphQL field
    ``driverDirectory``, this gives a local row its path.

    >>> action_directory_of(source_type="git", source_path="drivers/a")
    'drivers/a'
    >>> action_directory_of(source_type="local", source_path="/srv/drivers/a")
    '/srv/drivers/a'
    >>> action_directory_of(source_type="internal", source_path="x") is None
    True
    """
    if source_type in {"git", "local"}:
        return source_path
    return None
