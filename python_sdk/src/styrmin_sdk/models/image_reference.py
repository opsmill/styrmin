"""Client-side ``{{ app.version }}`` token check for component image overrides.

Mirrors the backend's token regex (the SDK cannot import the backend); a backend unit test
keeps the two in step.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# re.ASCII: only ASCII whitespace is tolerated inside the braces, as on the backend.
APP_VERSION_TOKEN_RE = re.compile(r"\{\{\s*app\.version\s*\}\}", re.ASCII)


def has_app_version_token(ref: str) -> bool:
    """Return whether ``ref`` contains at least one ``{{ app.version }}`` token."""
    return APP_VERSION_TOKEN_RE.search(ref) is not None


def pinned_image_components(overrides: Mapping[str, str | None]) -> list[str]:
    """Return, sorted, the components whose image override has no ``{{ app.version }}`` token.

    ``overrides`` maps component name to its stored reference; components without one
    (``None`` or empty) are skipped.
    """
    return sorted(name for name, ref in overrides.items() if ref and not has_app_version_token(ref))
