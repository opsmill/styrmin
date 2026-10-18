"""Driver directory path rule (spec 028).

A driver directory is the folder of a git repository that holds a driver's
``driver.styrmin.yml``, ``values.j2.yml`` and ``actions.py``, given relative
to the repository root. Every written form of the same folder is stored in one
form, so a reload at the same commit finds the existing driver version:

>>> normalise_driver_directory("./drivers/infrahub/")
'drivers/infrahub'
>>> normalise_driver_directory(".") is None
True

The helpers here are pure: the git driver provider calls them before the clone
(to refuse a value) and after it (to keep every path inside the clone).
"""

import hashlib
import re
import unicodedata
from pathlib import Path

from styrmin_backend.services.driver.exceptions import DriverLoadingError

_EXAMPLE = "drivers/infrahub"

# Longest stored driver directory, in characters.
MAX_DRIVER_DIRECTORY_LENGTH = 255

# ``scheme://`` followed by the user info that ends at the last ``@`` before a ``/``.
_USER_INFO = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*://)[^/\s]*@")


def quoted(value: str) -> str:
    r"""Return ``value`` in single quotes as given, with control characters escaped.

    >>> print(quoted("drivers\\a"))
    'drivers\a'
    >>> print(quoted("a\x00b"))
    'a\x00b'
    """
    shown = "".join(
        ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii")
        for ch in value
    )
    return f"'{shown}'"


def _refuse(value: str, rule: str) -> DriverLoadingError:
    return DriverLoadingError(
        f"Driver directory {quoted(value)} is refused: {rule}. "
        f"Give a path relative to the repository root, such as {quoted(_EXAMPLE)}."
    )


def normalise_driver_directory(value: str | None) -> str | None:
    """Return the stored form of a driver directory, or ``None`` for the root.

    Applies the rules in order: remove surrounding whitespace; refuse a
    control character, a backslash, ``{`` or ``}`` (Prefect fills in
    ``{{ ... }}`` templates in the working directory step), or a leading
    ``/``; split on ``/`` and drop empty and ``.`` segments; refuse a ``..``
    segment; join what is left with ``/``; refuse a result longer than
    :data:`MAX_DRIVER_DIRECTORY_LENGTH` characters.

    Args:
        value: The driver directory as given, or ``None``.

    Returns:
        The segments joined with ``/``, or ``None`` when no segment is left,
        which means the repository root.

    Raises:
        DriverLoadingError: The value breaks one of the rules above.

    >>> normalise_driver_directory("drivers//./infrahub")
    'drivers/infrahub'
    >>> normalise_driver_directory("  ") is None
    True
    >>> try:
    ...     normalise_driver_directory("a/../b")
    ... except DriverLoadingError as exc:
    ...     print(str(exc).split(". ")[0])
    Driver directory 'a/../b' is refused: it contains a '..' segment
    """
    if value is None:
        return None
    stripped = value.strip()
    if any(unicodedata.category(ch) == "Cc" for ch in stripped):
        raise _refuse(value, "it contains a control character")
    if "\\" in stripped:
        raise _refuse(value, "it contains a backslash")
    if "{" in stripped or "}" in stripped:
        raise _refuse(value, "it contains '{' or '}'")
    if stripped.startswith("/"):
        raise _refuse(value, "it is an absolute path")
    segments = [s for s in stripped.split("/") if s not in ("", ".")]
    if ".." in segments:
        raise _refuse(value, "it contains a '..' segment")
    stored = "/".join(segments)
    if len(stored) > MAX_DRIVER_DIRECTORY_LENGTH:
        raise _refuse(
            value, f"it is longer than {MAX_DRIVER_DIRECTORY_LENGTH} characters"
        )
    return stored or None


def resolve_inside(root: Path, relative: str | Path) -> Path | None:
    """Return the real path of ``root / relative`` when it is inside ``root``.

    Symlinks are followed at every depth; a dangling symlink resolves to its
    target path.

    Args:
        root: The folder the path must stay in, such as the clone root.
        relative: The path relative to ``root``.

    Returns:
        The resolved path when it is ``root.resolve()`` or below it, else
        ``None``.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     root = Path(tmp)
    ...     resolve_inside(root, "drivers/a") == root.resolve() / "drivers" / "a"
    True
    >>> resolve_inside(Path("/tmp"), "../etc") is None
    True
    """
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    if resolved == resolved_root or resolved.is_relative_to(resolved_root):
        return resolved
    return None


def driver_directory_digest(driver_directory: str) -> str:
    """Return the first 12 hex characters of the SHA-256 of a driver directory.

    Prefect refuses ``/`` in deployment names, so the digest stands for the
    driver directory in the name of each action's deployment (research R-003).
    Lookups use the ``directory/`` tag, so the digest only keeps names apart.

    Args:
        driver_directory: The stored driver directory.

    Returns:
        The first 12 hex characters of the SHA-256 of the UTF-8 value.

    >>> driver_directory_digest("drivers/infrahub")
    'c8dc0c0d9f46'
    """
    return hashlib.sha256(driver_directory.encode("utf-8")).hexdigest()[:12]


def redact_user_info(text: str) -> str:
    """Return ``text`` with the user info of every ``scheme://`` URL in it removed.

    For messages and logs: a clone error can repeat the repository URL with
    its user info. An scp-style address such as ``git@host:o/r.git`` has no
    scheme and is kept.

    >>> redact_user_info("https://user:token@host/x.git")
    'https://host/x.git'
    >>> redact_user_info("git@github.com:o/r.git")
    'git@github.com:o/r.git'
    >>> redact_user_info("https://user:token@[bad/x.git")
    'https://[bad/x.git'
    >>> redact_user_info("cannot reach https://u:t@h/x.git or ssh://git@h/y.git")
    'cannot reach https://h/x.git or ssh://h/y.git'
    """
    return _USER_INFO.sub(r"\1", text)
