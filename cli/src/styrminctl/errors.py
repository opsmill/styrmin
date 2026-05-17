"""CLI-only error types for ``styrminctl``.

These exceptions are control-flow signals consumed by the top-level CLI error
boundary; they intentionally do not live in the SDK's typed-error hierarchy.
Each exception renders as a single human-readable line via ``__str__`` so the
error boundary can simply do ``sys.exit(str(exc))`` (or write to stderr and
exit non-zero) without printing a Python traceback.
"""

from __future__ import annotations

from pathlib import Path


class TokenStoreError(Exception):
    """Raised by :class:`styrminctl.auth.token_store.TokenStore`.

    Covers corrupt JSON, unknown ``schema_version``, parent-directory not
    writable, and chmod failures. Carries the offending file path and a
    short human reason so the CLI error boundary can render a single line
    that names the file.
    """

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(self._format())

    def _format(self) -> str:
        return f"Token store error at {self.path}: {self.reason}"

    def __str__(self) -> str:
        return self._format()


class AsymmetricEnvCredentialsError(Exception):
    """Raised when exactly one of ``STYRMIN_USERNAME`` / ``STYRMIN_PASSWORD`` is set.

    Carries the name of the missing environment variable so the CLI can name
    it in a single-line error message.
    """

    def __init__(self, missing_variable: str) -> None:
        self.missing_variable = missing_variable
        super().__init__(self._format())

    def _format(self) -> str:
        return (
            f"Missing environment variable {self.missing_variable}: "
            f"set both STYRMIN_USERNAME and STYRMIN_PASSWORD, or neither."
        )

    def __str__(self) -> str:
        return self._format()
