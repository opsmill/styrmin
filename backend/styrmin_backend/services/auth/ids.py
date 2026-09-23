"""Convert GraphQL ``ID`` reference inputs to UUIDs with typed errors.

User and group mutations declare their reference inputs (``groupIds``,
``memberIds``) as ``[ID!]``, so Strawberry does not validate their syntax.
The resolvers own the DTO conversion (see ``services/auth/users.py``); this
helper is service-layer-owned so a malformed value raises a typed
:class:`ValidationError` instead of an unhandled ``ValueError`` that would
surface to clients as ``INTERNAL_ERROR``.
"""

from __future__ import annotations

from uuid import UUID

from styrmin_backend.services.exceptions import ValidationError


def parse_uuid_list(values: list[str] | None, *, field: str) -> list[UUID] | None:
    """Parse ``values`` into UUIDs, raising ``ValidationError`` on bad input.

    ``None`` passes through unchanged — the field was omitted, which is
    distinct from an explicitly empty list. ``field`` names the GraphQL input
    in the error message (e.g. ``"groupIds"``). Every malformed entry is
    reported, not just the first, so a caller can fix them in one round trip.
    """
    if values is None:
        return None
    parsed: list[UUID] = []
    invalid: list[str] = []
    for raw in values:
        try:
            parsed.append(UUID(str(raw)))
        except ValueError:
            invalid.append(str(raw))
    if invalid:
        raise ValidationError(
            f"{field} contains invalid UUID(s): {', '.join(repr(v) for v in invalid)}"
        )
    return parsed
