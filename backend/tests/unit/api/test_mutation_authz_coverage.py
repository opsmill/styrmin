"""Schema-walk completeness test. See ADR-020.

Walks the ``Mutation`` type and asserts every field has either a
``RequiresRole`` permission attached or a name in the documented
allow-list. A new mutation that lands without a role gate fails this
test in CI before review.
"""

from __future__ import annotations

import strawberry

from styrmin_backend.api.auth.allowlist import MUTATION_ALLOW_LIST
from styrmin_backend.api.auth.permissions import RequiresRole
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query


def _build_schema() -> strawberry.Schema:
    return strawberry.Schema(query=Query, mutation=Mutation)


def _has_requires_role(strawberry_field: object) -> bool:
    """True iff the field carries a ``RequiresRole`` permission extension."""
    extensions = getattr(strawberry_field, "extensions", None) or []
    for ext in extensions:
        for permission in getattr(ext, "permissions", []) or []:
            if isinstance(permission, RequiresRole):
                return True
    return False


def test_every_mutation_has_role_gate_or_is_allow_listed() -> None:
    schema = _build_schema()
    mutation_type = schema._schema.type_map["Mutation"]

    unguarded: list[str] = []
    for graphql_name, gfield in mutation_type.fields.items():
        sd_field = gfield.extensions.get("strawberry-definition")
        if sd_field is None:
            continue
        if _has_requires_role(sd_field):
            continue
        if graphql_name in MUTATION_ALLOW_LIST:
            continue
        unguarded.append(graphql_name)

    assert not unguarded, (
        f"Mutation fields without RequiresRole and not on the documented "
        f"allow-list: {sorted(unguarded)}. Either attach "
        f"PermissionExtension([RequiresRole(Role.X)]) to the resolver, or "
        f"add the field name to api/auth/allowlist.py:MUTATION_ALLOW_LIST "
        f"with a documented reason."
    )


def test_allow_list_only_contains_documented_entries() -> None:
    """Belt-and-suspenders: lock the allow-list contents.

    Adding a name to ``MUTATION_ALLOW_LIST`` should be a deliberate review
    decision in the same PR that adds the unguarded resolver. This guard
    flips the failure to "the allow-list grew" so the reviewer at least
    sees a churn-on-allow-list line in the diff.
    """
    expected = {
        "login",
        "callback",
        "reportPodStatuses",
        "reportDeploymentStatuses",
    }
    assert set(MUTATION_ALLOW_LIST) == expected, (
        "MUTATION_ALLOW_LIST drift detected. Update both api/auth/allowlist.py "
        "and this test together so the reviewer sees the deliberate change."
    )
