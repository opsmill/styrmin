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
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from styrmin_backend.services.driver.exceptions import DriverLoadingError

_EXAMPLE = "drivers/infrahub"


def _refuse(value: str, rule: str) -> DriverLoadingError:
    # ``repr`` quoting shows a NUL character as ``\x00``.
    return DriverLoadingError(
        f"Driver directory {value!r} is refused: {rule}. "
        f"Give a path relative to the repository root, such as {_EXAMPLE!r}."
    )


def normalise_driver_directory(value: str | None) -> str | None:
    """Return the stored form of a driver directory, or ``None`` for the root.

    Applies the rules in order: remove surrounding whitespace; refuse a
    backslash, a NUL character or a leading ``/``; split on ``/`` and drop
    empty and ``.`` segments; refuse a ``..`` segment; join what is left
    with ``/``.

    Args:
        value: The driver directory as given, or ``None``.

    Returns:
        The segments joined with ``/``, or ``None`` when no segment is left,
        which means the repository root.

    Raises:
        DriverLoadingError: The value is an absolute path, or contains a
            ``..`` segment, a backslash or a NUL character.

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
    if "\\" in stripped:
        raise _refuse(value, "it contains a backslash")
    if "\x00" in stripped:
        raise _refuse(value, "it contains a NUL character")
    if stripped.startswith("/"):
        raise _refuse(value, "it is an absolute path")
    segments = [s for s in stripped.split("/") if s not in ("", ".")]
    if ".." in segments:
        raise _refuse(value, "it contains a '..' segment")
    return "/".join(segments) or None


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
    """Return the first 7 hex characters of the SHA-256 of a driver directory.

    Prefect refuses ``/`` in deployment names, so the digest stands for the
    driver directory in the name of each action's deployment (research R-003).

    Args:
        driver_directory: The stored driver directory.

    Returns:
        The first 7 hex characters of the SHA-256 of the UTF-8 value.

    >>> driver_directory_digest("drivers/infrahub")
    'c8dc0c0'
    """
    return hashlib.sha256(driver_directory.encode("utf-8")).hexdigest()[:7]


def redact_repository_url(url: str) -> str:
    """Return a repository URL without its user info, for messages and logs.

    Args:
        url: The repository URL or path as given.

    Returns:
        For a URL with ``://``, the URL without ``user:password@``; any other
        string unchanged. Never raises, so a malformed URL that ``urlsplit``
        refuses still loses its user info.

    >>> redact_repository_url("https://user:token@host/x.git")
    'https://host/x.git'
    >>> redact_repository_url("git@github.com:o/r.git")
    'git@github.com:o/r.git'
    >>> redact_repository_url("https://user:token@[bad/x.git")
    'https://[bad/x.git'
    >>> redact_repository_url("https://[bad/x.git")
    'https://[bad/x.git'
    """
    if "://" not in url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        # Such as "Invalid IPv6 URL". The user info ends at the last "@"
        # before the first "/" after "://".
        scheme, rest = url.split("://", 1)
        authority, slash, path = rest.partition("/")
        if "@" not in authority:
            return url
        return f"{scheme}://{authority.rsplit('@', 1)[1]}{slash}{path}"
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=host))
