# Cross-package duplicate of backend/styrmin_backend/services/driver/labels.py
# kept here because the CLI is a separate package and importing from the
# backend would pull in unwanted server-side dependencies. The two copies
# MUST stay in sync; see specs/013-driver-fingerprint/contracts/sdk-cli-rendering.md
# for the canonical rendering rule.
"""Driver version label formatting for ``styrminctl``.

Per spec 013 (Provenance fingerprint), every user-visible CLI surface that
names an application driver version renders the label as ``<version>@<short>``
where ``<short>`` is the first 7 characters of the populated provenance
fingerprint -- ``content_hash`` for ``source_type == "local"``, or
``source_commit_sha`` for ``source_type == "git"``. The suffix is shown
unconditionally so labels stay stable when a second row appears.
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

    When both fingerprints are set (not expected by invariant -- a row is
    either ``source_type == "local"`` or ``source_type == "git"``),
    ``content_hash`` wins defensively.
    """

    fingerprint = content_hash or source_commit_sha
    if not fingerprint:
        return version
    return f"{version}@{fingerprint[:7]}"
