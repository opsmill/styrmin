"""Strawberry input types for the ``updateEnvironment`` mutation (009).

Phase-1 placeholder: the class is declared so downstream imports resolve.
Real fields land in T028 (US2) per ``specs/009-environment-update/tasks.md``.
"""

from __future__ import annotations

import strawberry


@strawberry.input(
    description=(
        "Structured input for the ``updateEnvironment`` mutation. "
        "Placeholder shape — real fields land in T028."
    )
)
class UpdateEnvironmentInput:
    """Placeholder input class for the 009 environment-update mutation.

    Strawberry requires at least one field on an input type. The
    ``_placeholder`` field is removed in T028 when the real config-mirror
    fields are added.
    """

    _placeholder: strawberry.Private[None] = None
