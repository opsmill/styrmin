"""Shared CLI-local types for the auth package.

``TokenSource`` is a literal enumeration of credential-resolution outcomes
(see ``specs/011-styrminctl-auth/contracts/credential-precedence.md``).
``AuthContext`` is the value object returned by :func:`get_auth_context`
so the ``whoami`` command can render the ``Authenticated via: ...`` line
without leaking the token itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from styrmin_sdk import StyrminClient

TokenSource = Literal["env", "file", "auto-login", "none"]


@dataclass(frozen=True)
class AuthContext:
    """Carries the resolved client plus the rung that produced its token."""

    client: StyrminClient
    source: TokenSource
