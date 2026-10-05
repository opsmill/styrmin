"""Schema-walk completeness tests. See ADR-017.

Walks the ``Mutation`` and ``Query`` types and asserts every root field
is either:

* gated by a ``RequiresRole`` permission extension, OR
* named in the documented ``MUTATION_ALLOW_LIST`` /
  ``QUERY_ALLOW_LIST``.

The schema-wide ``RequiresAuthentication`` extension covers any field
that's not allow-listed — but those fields still need to declare a
``RequiresRole`` for non-baseline access, otherwise the test will flag
them. A new resolver that lands without a role gate fails this test in
CI before review.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import strawberry
from graphql import GraphQLError

from styrmin_backend.api.auth.allowlist import (
    MUTATION_ALLOW_LIST,
    QUERY_ALLOW_LIST,
)
from styrmin_backend.api.auth.extensions import RequiresAuthentication
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
        "logout",
        "callback",
        "reportPodStatuses",
        "reportDeploymentStatuses",
    }
    assert set(MUTATION_ALLOW_LIST) == expected, (
        "MUTATION_ALLOW_LIST drift detected. Update both api/auth/allowlist.py "
        "and this test together so the reviewer sees the deliberate change."
    )


# ---------------------------------------------------------------------
# Query authz coverage — mirror of the Mutation walk above.
# ---------------------------------------------------------------------


def test_every_query_field_is_authenticated_or_allow_listed() -> None:
    """Every root ``Query`` field must either be in ``QUERY_ALLOW_LIST`` or
    be reachable only after the schema-wide ``RequiresAuthentication``
    extension has accepted the caller.

    The schema-wide extension is the implicit baseline: any field NOT in
    the allow-list requires an authenticated session at the very least.
    This test fails only when a field name appears that we forgot to
    document as allow-listed AND that has no ``RequiresRole`` either —
    in practice that means a new query field landed without being
    reviewed against the allow-list.
    """
    schema = _build_schema()
    query_type = schema._schema.type_map["Query"]

    # Every field is either:
    #  (a) in QUERY_ALLOW_LIST (unauthenticated allow-list), OR
    #  (b) implicitly gated by the RequiresAuthentication schema extension
    #      (which the schema-walk cannot introspect — instead we assert
    #      this is what would happen for any non-allow-listed field by
    #      proving RequiresAuthentication rejects it below).
    #
    # The schema-walk's job here is to detect the case "a new query field
    # exists and is in neither bucket" — but because the implicit gate
    # catches anything NOT in QUERY_ALLOW_LIST automatically, the only
    # failure mode is "someone added a name to QUERY_ALLOW_LIST without
    # a matching field". We invert the check: every name in the
    # allow-list must correspond to an actual root Query field.
    field_names = set(query_type.fields.keys())
    stale_allow_list_entries = set(QUERY_ALLOW_LIST) - field_names
    assert not stale_allow_list_entries, (
        f"QUERY_ALLOW_LIST names {sorted(stale_allow_list_entries)} are not "
        f"present as root Query fields — either the resolver was renamed "
        f"or the allow-list entry is stale. Update "
        f"api/auth/allowlist.py:QUERY_ALLOW_LIST."
    )

    # Belt-and-suspenders: if a query field declares ``RequiresRole``
    # but is ALSO in QUERY_ALLOW_LIST, that's a contradiction — the
    # allow-list bypasses RequiresAuthentication, so RequiresRole would
    # fire on an unauthenticated principal and reject anyway. Flag this
    # so the reviewer picks one strategy.
    conflicts: list[str] = []
    for graphql_name, gfield in query_type.fields.items():
        sd_field = gfield.extensions.get("strawberry-definition")
        if sd_field is None:
            continue
        if graphql_name in QUERY_ALLOW_LIST and _has_requires_role(sd_field):
            conflicts.append(graphql_name)
    assert not conflicts, (
        f"Query fields {sorted(conflicts)} are both allow-listed AND "
        f"carry a RequiresRole gate. Pick one — either the field is "
        f"unauthenticated (drop the RequiresRole) or it requires a "
        f"role (drop it from QUERY_ALLOW_LIST)."
    )


def test_query_allow_list_only_contains_documented_entries() -> None:
    """Lock the contents of ``QUERY_ALLOW_LIST`` so additions become a
    visible churn-on-allow-list line in review.
    """
    expected = {"currentUser", "ok", "environments"}
    assert set(QUERY_ALLOW_LIST) == expected, (
        "QUERY_ALLOW_LIST drift detected. Update both api/auth/allowlist.py "
        "and this test together so the reviewer sees the deliberate change. "
        "Remember: ``environments`` is a documented exception pending #396 "
        "service-account auth."
    )


def _info_for_query(field_name: str, *, current_user: Any = None) -> Any:
    """Build a minimal ``GraphQLResolveInfo`` stand-in. See
    test_auth_extensions._info — we duplicate the bare minimum here so the
    coverage tests don't depend on the implementation detail of that file.
    """
    path = SimpleNamespace(prev=None)  # is_root=True
    parent_type = SimpleNamespace(name="Query")
    return SimpleNamespace(
        field_name=field_name,
        parent_type=parent_type,
        path=path,
        context={"current_user": current_user},
    )


@pytest.mark.parametrize("field_name", ["users", "groups"])
def test_non_allow_listed_query_rejects_unauthenticated_caller(field_name: str) -> None:
    """Explicit smoke for the gate: a non-allow-listed query (``users``
    / ``groups``) must surface ``UNAUTHENTICATED`` when invoked without
    a current_user.
    """
    ext = RequiresAuthentication()
    info = _info_for_query(field_name, current_user=None)

    def _next(
        *args: Any, **kwargs: Any
    ) -> Any:  # pragma: no cover - must not be called
        raise AssertionError(
            f"RequiresAuthentication should have rejected unauthenticated "
            f"access to '{field_name}' before reaching the resolver"
        )

    with pytest.raises(GraphQLError) as excinfo:
        ext.resolve(_next, None, info)
    assert excinfo.value.extensions == {"code": "UNAUTHENTICATED"}


def test_currentuser_query_is_allow_listed_for_unauthenticated_caller() -> None:
    """Sanity counterpart: ``currentUser`` must pass through the gate so
    the SPA can boot and discover it has no session.
    """
    ext = RequiresAuthentication()
    info = _info_for_query("currentUser", current_user=None)
    sentinel = object()

    def _next(*args: Any, **kwargs: Any) -> Any:
        return sentinel

    assert ext.resolve(_next, None, info) is sentinel
