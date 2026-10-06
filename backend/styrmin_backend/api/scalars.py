from __future__ import annotations

from typing import TYPE_CHECKING, Any, NewType

import strawberry

if TYPE_CHECKING:
    from typing import TypeAlias

    JSON: TypeAlias = dict[Any, Any]
    BigInt: TypeAlias = int
else:
    from strawberry.scalars import JSON

    BigInt = NewType("BigInt", int)

# Every ``strawberry.Schema`` built from the app's Query/Mutation must pass
# ``StrawberryConfig(scalar_map=SCALAR_MAP)``; without it the build fails.
SCALAR_MAP = {
    BigInt: strawberry.scalar(
        name="BigInt",
        description=(
            "Integer that can exceed the 32-bit range of Int, such as a byte "
            "count. Serialized as a JSON number, exact up to 2^53."
        ),
        serialize=int,
        parse_value=int,
    ),
}

__all__ = ["JSON", "BigInt", "SCALAR_MAP"]
