"""Error-propagation tests for ``UpdateDeploymentInput`` (011 / T031).

One parametrized test (:func:`test_update_deployment_input_error_code`)
covers every row of the 9-row error matrix in
``specs/011-typed-deployment-input/contracts/graphql.md`` §5. Each row
crafts an ``updateDeployment`` input that triggers exactly one typed
error and asserts:

* the GraphQL response carries ``errors``;
* ``response.errors[0]['extensions']['code']`` matches the expected
  typed code;
* where the matrix promises a payload field (``name`` / ``scope`` /
  ``component_name``), the field is present on ``extensions`` with the
  expected value.

The fixture uses the ``client`` (admin Bearer) so the boundary
``RequiresAuthentication`` extension is fully exercised. The
``prefect_manager_mock`` fixture isn't needed because every row fails
**before** the resolver dispatches anything to the workflow engine —
this is the whole point of typed-error pre-validation (FR-008 / FR-009).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Component, ComponentConfig

from ._queries import load_query
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_deployment_with_components(
    session: AsyncSession,
    *,
    component_names: list[str],
) -> Any:
    """Seed a deployment whose driver declares ``component_names`` and whose
    Component rows mirror those names.
    """
    adv = await seed_application_driver_version(session)
    for name in component_names:
        cc = ComponentConfig(
            name=name,
            config={
                "identifier": {
                    "label": {"app.kubernetes.io/name": f"{name}-app"},
                },
            },
            application_driver_version_id=adv.id,
        )
        session.add(cc)
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    for name in component_names:
        comp = Component(
            name=name,
            config={
                "identifier": {
                    "label": {"app.kubernetes.io/name": f"{name}-app"},
                },
            },
            enabled=True,
            deployment_id=deployment.id,
        )
        session.add(comp)
    await session.commit()
    return deployment


# ---------------------------------------------------------------------------
# Error matrix
# ---------------------------------------------------------------------------
#
# Each row is (row_id, build_input, expected_code, expected_metadata,
# needs_driver_components).
#
#  - ``build_input``  is a callable that, given the seeded driver's
#    component names, returns the GraphQL ``input`` variable.
#  - ``expected_code`` is the ``extensions.code`` string the matrix
#    promises.
#  - ``expected_metadata`` is a dict of additional ``extensions`` keys
#    that must equal the given value (e.g. ``{"name": "1invalid"}``).
#  - ``needs_driver_components`` flips the seeding helper to
#    ``_seed_deployment_with_components(["api", "worker"])`` instead of
#    the bare ``seed_deployment`` path.

_OVERSIZED_VALUE = "x" * (64 * 1024 + 1)


def _e1_invalid_env_var_name_top_level(_components: list[str]) -> dict[str, Any]:
    return {"envVars": [{"name": "1invalid", "value": "x"}]}


def _e2_invalid_env_var_name_component(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": components[0],
                "envVars": [{"name": "1invalid", "value": "x"}],
            }
        ]
    }


def _e3_duplicate_env_var_name_top_level(_components: list[str]) -> dict[str, Any]:
    return {
        "envVars": [
            {"name": "FOO", "value": "a"},
            {"name": "FOO", "value": "b"},
        ]
    }


def _e4_duplicate_env_var_name_component(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": components[0],
                "envVars": [
                    {"name": "BAR", "value": "1"},
                    {"name": "BAR", "value": "2"},
                ],
            }
        ]
    }


def _e5_env_var_size_top_level(_components: list[str]) -> dict[str, Any]:
    return {"envVars": [{"name": "BIG", "value": _OVERSIZED_VALUE}]}


def _e6_env_var_size_component(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": components[0],
                "envVars": [{"name": "BIG", "value": _OVERSIZED_VALUE}],
            }
        ]
    }


def _e7_unknown_component(_components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": "does_not_exist",
                "envVars": [{"name": "X", "value": "y"}],
            }
        ]
    }


def _e8_duplicate_parameter_name(_components: list[str]) -> dict[str, Any]:
    return {
        "parameters": [
            {"name": "replicas", "value": 1},
            {"name": "replicas", "value": 2},
        ]
    }


def _e9_duplicate_component_name(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {"name": components[0], "envVars": [{"name": "X", "value": "y"}]},
            {"name": components[0], "envVars": []},
        ]
    }


_ERROR_ROWS = [
    # (row_id, build_input, expected_code, expected_metadata, needs_driver_components)
    (
        "e1_invalid_env_var_name_top_level",
        _e1_invalid_env_var_name_top_level,
        "INVALID_ENV_VAR_NAME",
        {"name": "1invalid"},
        False,
    ),
    (
        "e2_invalid_env_var_name_component",
        _e2_invalid_env_var_name_component,
        "INVALID_ENV_VAR_NAME",
        {"name": "1invalid", "scope": "component"},
        True,
    ),
    (
        "e3_duplicate_env_var_name_top_level",
        _e3_duplicate_env_var_name_top_level,
        "DUPLICATE_ENV_VAR_NAME",
        {"name": "FOO", "scope": "deployment"},
        False,
    ),
    (
        "e4_duplicate_env_var_name_component",
        _e4_duplicate_env_var_name_component,
        "DUPLICATE_ENV_VAR_NAME",
        # The component scope is encoded as ``component:<name>`` per
        # research.md §4 and the ``_flatten_components`` helper; the
        # seeded fixture's first component is ``"api"`` so the scope
        # reaching the GraphQL extensions payload is ``component:api``.
        # FR-009 mandates the scope reach the boundary intact, so assert
        # on it explicitly. The matcher already does substring-match on
        # the ``scope`` key.
        {"name": "BAR", "scope": "component:api"},
        True,
    ),
    (
        "e5_env_var_size_top_level",
        _e5_env_var_size_top_level,
        "ENV_VAR_SIZE_LIMIT_EXCEEDED",
        {"name": "BIG"},
        False,
    ),
    (
        "e6_env_var_size_component",
        _e6_env_var_size_component,
        "ENV_VAR_SIZE_LIMIT_EXCEEDED",
        {"name": "BIG", "scope": "component"},
        True,
    ),
    (
        "e7_unknown_component",
        _e7_unknown_component,
        "UNKNOWN_COMPONENT_ENV_VAR",
        {"component_name": "does_not_exist"},
        True,
    ),
    (
        "e8_duplicate_parameter_name",
        _e8_duplicate_parameter_name,
        "DUPLICATE_PARAMETER_NAME",
        {"name": "replicas"},
        False,
    ),
    (
        "e9_duplicate_component_name",
        _e9_duplicate_component_name,
        "DUPLICATE_COMPONENT_NAME",
        # The duplicate-component check fires on the second occurrence;
        # the offending name is the seeded fixture's first component
        # ("api"). FR-009 mandates the typed payload identify the
        # offending name.
        {"name": "api"},
        True,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row_id", "build_input", "expected_code", "expected_metadata", "needs_driver"),
    _ERROR_ROWS,
    ids=[row[0] for row in _ERROR_ROWS],
)
async def test_update_deployment_input_error_code(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — guards against accidental Prefect dispatch
    row_id: str,
    build_input: Any,
    expected_code: str,
    expected_metadata: dict[str, Any],
    needs_driver: bool,
) -> None:
    """Drive every row of the 9-row error matrix from ``contracts/graphql.md``
    §5: each row submits an input that triggers one typed error and asserts
    on ``response.errors[0]['extensions']['code']`` (and any payload field
    the matrix promises).
    """
    if needs_driver:
        component_names = ["api", "worker"]
        deployment = await _seed_deployment_with_components(
            session, component_names=component_names
        )
    else:
        component_names = []
        deployment = await seed_deployment(session)

    input_var = build_input(component_names)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment.id),
                "input": input_var,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, (
        f"row {row_id}: expected an errors array, got data only: {payload}"
    )
    errors = payload["errors"]
    assert len(errors) >= 1
    extensions = errors[0].get("extensions") or {}
    assert extensions.get("code") == expected_code, (
        f"row {row_id}: expected extensions.code = {expected_code!r}; "
        f"got {extensions.get('code')!r}. Full extensions: {extensions}"
    )
    for key, value in expected_metadata.items():
        actual = extensions.get(key)
        if key == "scope":
            # Some scopes carry a free-form prefix (``component:<name>``);
            # accept either equality or a "starts-with" match so the test
            # is robust to scope-format tweaks across rows.
            assert actual is not None, (
                f"row {row_id}: expected scope, got None in {extensions}"
            )
            assert value in actual, (
                f"row {row_id}: expected scope to contain {value!r}; got {actual!r}"
            )
        else:
            assert actual == value, (
                f"row {row_id}: expected extensions.{key} = {value!r}; "
                f"got {actual!r}. Full extensions: {extensions}"
            )
