"""Top-level CLI entry point.

Wraps the Cyclopts :data:`app` with the auth error boundary so credential
failures render as a single human-readable stderr line — never a Python
traceback. See the contracts under ``specs/011-styrminctl-auth/contracts/``
for the exact wording.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Literal

try:
    from .cli_commands import app as _inner_app
except ImportError as exc:
    sys.exit(f"Module {exc.name} is not available")

from styrmin_sdk.exceptions import StyrminAuthenticationError

from styrminctl.errors import AsymmetricEnvCredentialsError, TokenStoreError
from styrminctl.telemetry import runtime as _telemetry
from styrminctl.telemetry.store import TelemetryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cyclopts import App


class _AuthBoundaryApp:
    """Callable proxy that installs the auth error boundary around the Cyclopts app.

    Telemetry observes the **final** outcome by wrapping the auth boundary: the
    inner call (boundary included) runs inside ``telemetry.runtime.run``, so a
    credential failure's ``SystemExit(1)`` is the outcome telemetry classifies.
    Telemetry is failure-isolated — it never changes stdout/stderr/exit code.

    Forwards every other attribute access to the underlying Cyclopts app so
    callers that introspect (e.g. ``app.generate_completion(...)``) keep
    working unchanged.
    """

    def __init__(self, inner: App) -> None:
        self._inner = inner
        self._telemetry_store = TelemetryStore()

    def _call_with_auth_boundary(self, args: Sequence[str] | None) -> object:
        """Run the inner app with the credential-failure error boundary."""
        try:
            return self._inner(args)
        except (StyrminAuthenticationError, TokenStoreError, AsymmetricEnvCredentialsError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc

    def __call__(self, args: Sequence[str] | None = None) -> object:
        return _telemetry.run(
            self._call_with_auth_boundary,
            args,
            app=self._inner,
            store=self._telemetry_store,
        )

    def generate_completion(
        self,
        *,
        prog_name: str | None = None,
        shell: Literal["zsh", "bash", "fish"] | None = None,
    ) -> str:
        """Pass-through to the underlying Cyclopts app's completion generator."""
        return self._inner.generate_completion(prog_name=prog_name, shell=shell)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


app = _AuthBoundaryApp(_inner_app)

__all__ = ["app"]
