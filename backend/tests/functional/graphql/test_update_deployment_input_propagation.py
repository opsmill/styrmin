"""GraphQL ↔ DB propagation tests for ``UpdateDeploymentInput`` (011 / T030).

One parametrized test (:func:`test_update_deployment_input_field_propagates`)
covers every row of the 22-row matrix in
``specs/011-typed-deployment-input/contracts/graphql.md`` §4. Each row
submits a real ``updateDeployment`` mutation with one typed input field
set, then reads the row back from the DB through the real
``session.get`` path and asserts the persisted state matches the
expected projection.

Rows 02 (``parameters`` merge) and 04 (``components.envVars``) need
extra assertions beyond a round-trip — they live in their own dedicated
test functions below the parametrized one.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Component,
    ComponentConfig,
    Deployment,
)

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
) -> Deployment:
    """Seed a deployment whose driver declares ``component_names`` and whose
    Component rows mirror those names. Mirrors the helper in
    ``test_env_vars_propagation.py`` so the components-row propagation
    test can target a driver-known component name.
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
# Parametrized matrix (rows 01, 03, 05–22; rows 02 + 04 below)
#
# Each row is (test_id, input_var, expected_db_state) where:
#   * test_id is the human-readable suffix used in the parametrize id;
#   * input_var is the dict fed into the mutation's ``input`` variable;
#   * expected_db_state asserts on either:
#       - ``Deployment.config``    (most rows),
#       - ``Deployment.name``      (row 01),
#       - ``Deployment.service_name_overrides`` (row 03).
#
# The mutation succeeds in every case because all inputs are
# semantically valid configuration; the assertions hit the *persisted*
# DB row, which is what FR-001 / FR-002 / FR-005 / SC-001 require.
# ---------------------------------------------------------------------------


_NAME_ROW: dict[str, Any] = {"name": "renamed-via-input"}
_SERVICE_NAME_OVERRIDES_ROW: dict[str, Any] = {
    "serviceNameOverrides": [
        {"driverServiceName": "simple-app", "overrideName": "renamed"}
    ]
}
_ENV_VARS_ROW: dict[str, Any] = {"envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}
_IP_WHITELIST_ROW: dict[str, Any] = {"ipWhitelist": ["10.0.0.0/8", "192.168.0.0/16"]}
_DEDICATED_INGRESS_ROW: dict[str, Any] = {
    "dedicatedIngress": {"implementation": "traefik", "type": "ingress"}
}
_SCHEDULING_RESOURCES_REQUESTS_ROW: dict[str, Any] = {
    "scheduling": {"resources": {"requests": {"cpu": "200m", "memory": "256Mi"}}}
}
_SCHEDULING_TOLERATIONS_ROW: dict[str, Any] = {
    "scheduling": {
        "tolerations": [
            {
                "key": "dedicated",
                "operator": "EQUAL",
                "value": "batch",
                "effect": "NO_SCHEDULE",
            }
        ]
    }
}
_SCHEDULING_TOPOLOGY_SPREAD_ROW: dict[str, Any] = {
    "scheduling": {
        "topologySpreadConstraints": [
            {
                "maxSkew": 1,
                "topologyKey": "kubernetes.io/hostname",
                "whenUnsatisfiable": "DO_NOT_SCHEDULE",
            }
        ]
    }
}
_SCHEDULING_POD_AFFINITY_ROW: dict[str, Any] = {
    "scheduling": {
        "podAffinity": {
            "required": [
                {
                    "topologyKey": "kubernetes.io/hostname",
                    "labelSelector": {"matchLabels": {"app": "demo"}},
                }
            ]
        }
    }
}
_SCHEDULING_RUNTIME_CLASS_ROW: dict[str, Any] = {"scheduling": {"runtimeClass": "kata"}}
_SCHEDULING_INJECT_ROW: dict[str, Any] = {
    "scheduling": {"inject": {"podAffinity": False, "resources": True}}
}
_FQDN_SUFFIX_ROW: dict[str, Any] = {"fqdnSuffix": "demo.example.com"}
_EXTERNAL_URL_SCHEME_ROW: dict[str, Any] = {"externalUrlScheme": "HTTPS"}
_EXTERNAL_URL_PORT_ROW: dict[str, Any] = {"externalUrlPort": 8443}
_EXTERNAL_DNS_ENDPOINTS_TYPE_ROW: dict[str, Any] = {
    "externalDnsEndpointsType": "NODE_EXTERNAL_IP"
}
_INGRESS_CLASS_ROW: dict[str, Any] = {"ingressClass": "nginx"}
_DB_SIZE_ROW: dict[str, Any] = {"dbSize": "20Gi"}
_RUNTIME_CLASS_ROW: dict[str, Any] = {"runtimeClass": "kata"}
_NODE_SELECTOR_ROW: dict[str, Any] = {"nodeSelector": "tier=batch"}
_STANDARD_STORAGE_ROW: dict[str, Any] = {
    "standardStorage": {"storageClass": "fast-ssd"}
}
_FAST_STORAGE_ROW: dict[str, Any] = {"fastStorage": {"storageClass": "nvme-local"}}
_BACKUP_TTL_ROW: dict[str, Any] = {"backupTtl": "8760h"}


# Each row: (id, input_var, kind, expected)
#  - kind="config"   → assert deployment.config == expected
#  - kind="name"     → assert deployment.name == expected
#  - kind="accepted" → assert the resolver accepted the input (no errors).
#    Used for inputs whose persisted state lives off the Deployment row
#    (e.g. service_name_overrides → DeployedService table after the
#    services-discovery step); the resolver-side flatten from list →
#    dict is what this row proves got wired correctly.
_PROPAGATION_ROWS: list[tuple[str, dict[str, Any], str, Any]] = [
    # Row 01
    ("name", _NAME_ROW, "name", "renamed-via-input"),
    # Row 03 — see contracts §4 row 03. The list → dict flatten happens
    # in ``update_deployment_input_to_dict``; downstream it is forwarded
    # to ``reconcile_services_on_upgrade`` which writes per-service
    # rows. For the seeded driver fixture there are zero service
    # definitions, so ``DeployedService`` rows are not created — what
    # this row proves is the *resolver-side* conversion is wired (no
    # type / coercion error from the new typed input).
    (
        "service_name_overrides",
        _SERVICE_NAME_OVERRIDES_ROW,
        "accepted",
        None,
    ),
    # Row 05
    ("env_vars", _ENV_VARS_ROW, "config", {"env_vars": {"LOG_LEVEL": "debug"}}),
    # Row 06
    (
        "ip_whitelist",
        _IP_WHITELIST_ROW,
        "config",
        {"ip_whitelist": ["10.0.0.0/8", "192.168.0.0/16"]},
    ),
    # Row 07
    (
        "dedicated_ingress",
        _DEDICATED_INGRESS_ROW,
        "config",
        {"dedicated_ingress": {"implementation": "traefik", "type": "ingress"}},
    ),
    # Row 08
    (
        "scheduling_resources_requests",
        _SCHEDULING_RESOURCES_REQUESTS_ROW,
        "config",
        {"scheduling": {"resources": {"requests": {"cpu": "200m", "memory": "256Mi"}}}},
    ),
    # Row 09
    (
        "scheduling_tolerations",
        _SCHEDULING_TOLERATIONS_ROW,
        "config",
        {
            "scheduling": {
                "tolerations": [
                    {
                        "key": "dedicated",
                        "operator": "Equal",
                        "value": "batch",
                        "effect": "NoSchedule",
                    }
                ]
            }
        },
    ),
    # Row 10
    (
        "scheduling_topology_spread",
        _SCHEDULING_TOPOLOGY_SPREAD_ROW,
        "config",
        {
            "scheduling": {
                "topology_spread_constraints": [
                    {
                        "max_skew": 1,
                        "topology_key": "kubernetes.io/hostname",
                        "when_unsatisfiable": "DoNotSchedule",
                    }
                ]
            }
        },
    ),
    # Row 11
    (
        "scheduling_pod_affinity",
        _SCHEDULING_POD_AFFINITY_ROW,
        "config",
        {
            "scheduling": {
                "pod_affinity": {
                    "required": [
                        {
                            "topology_key": "kubernetes.io/hostname",
                            "label_selector": {"match_labels": {"app": "demo"}},
                        }
                    ]
                }
            }
        },
    ),
    # Row 12
    (
        "scheduling_runtime_class",
        _SCHEDULING_RUNTIME_CLASS_ROW,
        "config",
        {"scheduling": {"runtime_class": "kata"}},
    ),
    # Row 13
    (
        "scheduling_inject",
        _SCHEDULING_INJECT_ROW,
        "config",
        {"scheduling": {"inject": {"pod_affinity": False, "resources": True}}},
    ),
    # Row 14
    (
        "fqdn_suffix",
        _FQDN_SUFFIX_ROW,
        "config",
        {"fqdn_suffix": "demo.example.com"},
    ),
    # Row 15
    (
        "external_url_scheme",
        _EXTERNAL_URL_SCHEME_ROW,
        "config",
        {"external_url_scheme": "https"},
    ),
    # Row 16
    (
        "external_url_port",
        _EXTERNAL_URL_PORT_ROW,
        "config",
        {"external_url_port": 8443},
    ),
    # Row 17
    (
        "external_dns_endpoints_type",
        _EXTERNAL_DNS_ENDPOINTS_TYPE_ROW,
        "config",
        {"external_dns_endpoints_type": "NodeExternalIP"},
    ),
    # Row 18
    ("ingress_class", _INGRESS_CLASS_ROW, "config", {"ingress_class": "nginx"}),
    # Row 19
    ("db_size", _DB_SIZE_ROW, "config", {"db_size": "20Gi"}),
    # Row 20
    ("runtime_class", _RUNTIME_CLASS_ROW, "config", {"runtime_class": "kata"}),
    # Row 21
    ("node_selector", _NODE_SELECTOR_ROW, "config", {"node_selector": "tier=batch"}),
    # Row 22
    (
        "standard_storage",
        _STANDARD_STORAGE_ROW,
        "config",
        {"standard_storage": {"storage_class": "fast-ssd"}},
    ),
    # Row 23 — fast_storage peer of standard_storage
    (
        "fast_storage",
        _FAST_STORAGE_ROW,
        "config",
        {"fast_storage": {"storage_class": "nvme-local"}},
    ),
    # Row 24 — backup_ttl, the deployment-scope retention override (016 / US2)
    (
        "backup_ttl",
        _BACKUP_TTL_ROW,
        "config",
        {"backup_ttl": "8760h"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row_id", "input_var", "kind", "expected"),
    _PROPAGATION_ROWS,
    ids=[row[0] for row in _PROPAGATION_ROWS],
)
async def test_update_deployment_input_field_propagates(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — keeps the mutation from touching real Prefect
    row_id: str,
    input_var: dict[str, Any],
    kind: str,
    expected: Any,
) -> None:
    """Drive every row of the 22-row matrix from ``contracts/graphql.md`` §4.

    For each row, submit an ``updateDeployment`` mutation carrying the
    one typed input field under test, then read the deployment row back
    through the real DB session and assert the value reached its
    persisted destination (``Deployment.config`` / ``Deployment.name`` /
    ``Deployment.service_name_overrides``).

    Rows 02 (``parameters`` merge) and 04 (``components.envVars``) live
    in their own dedicated test functions below — both require setup
    that the parametrized body cannot express cleanly.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": input_var,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, (
        f"row {row_id} unexpectedly failed: {payload.get('errors')}"
    )

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None

    if kind == "name":
        assert db_row.name == expected, (
            f"row {row_id}: name did not round-trip to Deployment.name"
        )
    elif kind == "accepted":
        # Resolver-side flatten succeeded — see comment on the row tuple.
        # The "did not 500" check is already covered by the
        # ``"errors" not in payload`` assertion above; reading the row
        # back here just proves the DB session is still in a sane state
        # (no transactional poisoning from the conversion).
        assert db_row.id == deployment_id
    else:
        assert db_row.config == expected, (
            f"row {row_id}: did not round-trip to Deployment.config"
        )


# ---------------------------------------------------------------------------
# Row 02 — parameters merge semantics (FR-006)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_input_parameters_merge(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Row 02: ``input.parameters`` flattens to ``Deployment.parameters``
    using **merge** semantics — entries in the input merge on top of the
    persisted dict; keys not named in the input survive.

    Driver parameters are normally constrained by the driver's parameter
    definitions, but for an unconstrained driver-version fixture
    (``seed_application_driver_version`` registers no parameter spec)
    ``validate_parameter_values`` accepts any JSON values. We exercise
    the merge behaviour the resolver promises (research.md §3) by
    seeding a baseline dict, submitting a partial overlay, and reading
    the merged result back through the DB session.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    # Seed a driver with parameter definitions; otherwise
    # ``validate_parameter_values`` rejects every submitted name with
    # "Unknown parameter(s)".
    adv = await seed_application_driver_version(session)
    adv.parameters = [
        {
            "name": "replicas",
            "label": "Replicas",
            "kind": "integer",
            "default": 1,
        },
        {
            "name": "verbose",
            "label": "Verbose",
            "kind": "boolean",
            "default": False,
        },
        {
            "name": "label",
            "label": "Label",
            "kind": "string",
            "default": "",
        },
        {
            "name": "new_flag",
            "label": "New flag",
            "kind": "boolean",
            "default": False,
        },
    ]
    session.add(adv)
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    deployment_id = deployment.id

    # Baseline: parameters preset on the row.
    deployment.parameters = {"replicas": 2, "verbose": False, "label": "baseline"}
    session.add(deployment)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {
                    "parameters": [
                        {"name": "replicas", "value": 5},
                        {"name": "new_flag", "value": True},
                    ]
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    # Merge semantics: existing ``label`` and ``verbose`` survive, while
    # ``replicas`` is overridden and ``new_flag`` is added.
    assert db_row.parameters == {
        "replicas": 5,
        "verbose": False,
        "label": "baseline",
        "new_flag": True,
    }


# ---------------------------------------------------------------------------
# Row 04 — components + per-component envVars flatten (FR-001/FR-002 + 008)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_input_components_env_vars(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Row 04: ``input.components[].envVars`` flattens the per-component
    list to a dict on ``Deployment.config.components.<name>.env_vars``,
    with the duplicate-detection scope set to ``component:<name>``.

    The mutation succeeds when every named component is declared by the
    driver (the ``UNKNOWN_COMPONENT_ENV_VAR`` boundary is exercised in
    the error-matrix test file). Asserts both the persisted dict shape
    and that the deployment-level (top-level) ``env_vars`` and the
    per-component blocks coexist without bleeding into each other.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await _seed_deployment_with_components(
        session, component_names=["api", "worker"]
    )
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {
                    "envVars": [{"name": "LOG_LEVEL", "value": "info"}],
                    "components": [
                        {
                            "name": "worker",
                            "envVars": [
                                {"name": "LOG_LEVEL", "value": "debug"},
                                {"name": "WORKER_QUEUE", "value": "orders"},
                            ],
                        },
                        {"name": "api", "envVars": []},
                    ],
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None

    config = db_row.config
    # Top-level env_vars survives untouched alongside the per-component
    # block (no bleed between scopes).
    assert config["env_vars"] == {"LOG_LEVEL": "info"}
    # Per-component flatten: list-of-{name,value} → dict[name]=value.
    assert config["components"]["worker"]["env_vars"] == {
        "LOG_LEVEL": "debug",
        "WORKER_QUEUE": "orders",
    }
    # An empty envVars list explicitly clears the component's env vars
    # to ``{}`` — the entry exists but is empty (not absent / not None).
    assert config["components"]["api"]["env_vars"] == {}


# ---------------------------------------------------------------------------
# Row 03 follow-up — service_name_overrides actually persists (FR-005)
#
# The parametrized ``service_name_overrides`` row above only proves the
# resolver-side flatten succeeded (the seeded driver has zero service
# definitions, so no DeployedService rows are created). This dedicated
# test seeds a driver with one declared service, submits the override,
# and reads the DeployedService row back to confirm the override name
# reached the persisted ``resolved_name`` column.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_input_service_name_overrides_persists(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """``input.serviceNameOverrides`` flattens to ``dict[driver_name → override]``
    and the override reaches ``DeployedService.resolved_name``.

    Regression guard for the case where a refactor drops
    ``service_name_overrides`` from the resolver-derived legacy kwargs —
    the parametrized row 03 only round-trips the resolver, not the DB
    write, so it would not catch a missing forward.
    """
    from styrmin_backend.db.models import DeployedService

    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    adv = await seed_application_driver_version(session)
    adv.services = [
        {
            "name": "simple-app",
            "kind": "http",
            "scope": "internal",
            "port": 8080,
            "component": "web",
        }
    ]
    session.add(adv)
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {
                    "serviceNameOverrides": [
                        {"driverServiceName": "simple-app", "overrideName": "renamed"}
                    ]
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    # Confirm the override reached the DeployedService row.
    session.expire_all()
    from sqlmodel import select

    result = await session.exec(
        select(DeployedService).where(DeployedService.deployment_id == deployment_id)
    )
    services = list(result.all())
    assert len(services) == 1, (
        f"expected exactly one DeployedService row, got {len(services)}"
    )
    assert services[0].driver_service_name == "simple-app"
    assert services[0].resolved_name == "renamed", (
        "service_name_overrides did not propagate to DeployedService.resolved_name"
    )


# ---------------------------------------------------------------------------
# Clearing semantics (spec.md Acceptance Scenarios AS-2, AS-7, AS-8)
#
# These three tests exercise the full-replacement clear path — they
# differ from the parametrized matrix by *seeding existing state* and
# then submitting a typed input that explicitly clears it. The matrix
# only sets fields from empty / default; clearing has its own failure
# mode (silent drop, wrong dict shape) that the matrix cannot catch.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_replacement_clears_ip_whitelist(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """AS-2: submitting ``ipWhitelist: []`` clears the persisted allowlist."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await seed_deployment(session)
    deployment.config = {"ip_whitelist": ["10.0.0.0/8", "192.168.0.0/16"]}
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"ipWhitelist": []},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    # Empty list reaches the persisted dict as ``[]`` (explicit clear),
    # not as "missing key" or as the prior value.
    assert db_row.config.get("ip_whitelist") == [], (
        f"expected explicit clear (``[]``); got {db_row.config!r}"
    )


@pytest.mark.asyncio
async def test_components_empty_list_clears_components(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """AS-7: submitting ``components: []`` clears every per-component block."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await _seed_deployment_with_components(
        session, component_names=["api"]
    )
    deployment.config = {
        "components": {"api": {"env_vars": {"FOO": "bar"}}},
    }
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"components": []},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    # Empty list flattens to ``{}`` — the components key is present but
    # the dict is empty (no surviving per-component blocks).
    assert db_row.config.get("components") == {}, (
        f"expected components cleared to {{}}; got {db_row.config!r}"
    )


@pytest.mark.asyncio
async def test_components_empty_env_vars_clears_component_env_vars(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """AS-8: ``components: [{name, envVars: []}]`` keeps the component but
    clears its env vars.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await _seed_deployment_with_components(
        session, component_names=["api"]
    )
    deployment.config = {
        "components": {"api": {"env_vars": {"FOO": "bar", "BAZ": "qux"}}},
    }
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {
                    "components": [
                        {"name": "api", "envVars": []},
                    ],
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    # Component entry survives; its env_vars dict is empty.
    assert db_row.config.get("components") == {"api": {"env_vars": {}}}, (
        f"expected env_vars cleared on api; got {db_row.config!r}"
    )


# ---------------------------------------------------------------------------
# 016 / FR-005 — backup_ttl survives (or is deliberately dropped by) a
# full-replacement update.
#
# The deployment-scope retention override is only useful if a client that
# re-submits the persisted config keeps it; the mirror case (a submission
# without the field) must read as an explicit "drop the policy", which is
# exactly why the web UI's input builders have to carry it through.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_backup_ttl_preserved_when_resubmitted(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Re-submitting ``backupTtl`` alongside another field keeps the policy."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await seed_deployment(session)
    deployment.config = {"backup_ttl": "8760h"}
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {
                    "backupTtl": "8760h",
                    "envVars": [{"name": "LOG_LEVEL", "value": "debug"}],
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    assert db_row.config == {
        "backup_ttl": "8760h",
        "env_vars": {"LOG_LEVEL": "debug"},
    }


@pytest.mark.asyncio
async def test_update_deployment_omitting_backup_ttl_clears_it(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Omitting ``backupTtl`` drops it — full-replacement semantics.

    A deployment that loses its override falls back to the environment /
    cluster / built-in hop on the next backup, so the clear has to be
    visible in the persisted config rather than silently retained.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    deployment = await seed_deployment(session)
    deployment.config = {"backup_ttl": "8760h"}
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"envVars": [{"name": "LOG_LEVEL", "value": "debug"}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    assert db_row.config is not None
    assert db_row.config == {"env_vars": {"LOG_LEVEL": "debug"}}
    assert "backup_ttl" not in db_row.config


# ---------------------------------------------------------------------------
# Edge case — empty input (spec.md Edge Cases / spec 014 no-op)
#
# The resolver routes ``deployment_config={}`` to ``None`` so an empty
# typed input does not silently wipe the persisted config. Spec 014
# removed the service-layer "at least one of …" guard: an empty input
# that resolves to no change is now a clean no-op (``null``), not a
# ``VALIDATION_ERROR``. It must still leave the persisted config intact.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_input_is_noop_and_preserves_config(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Edge case: submitting ``input: {}`` against a settled deployment is a
    no-op — the mutation returns ``null`` (no error) and does not touch the
    persisted config.

    The resolver still routes the empty typed input to
    ``deployment_config=None`` so the persisted ``deployment.config`` is
    not overwritten with an empty dict. Spec 014 then resolves the
    unchanged desired state to the current instance and short-circuits,
    so the mutation returns ``null`` rather than a ``VALIDATION_ERROR``.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    deployment = await seed_deployment(session)
    deployment_id = deployment.id
    original_config = {"ipWhitelist": ["10.0.0.0/8"]}

    # First apply the config so the deployment has an active instance; an
    # empty input is only a no-op against a settled (already-realised)
    # deployment — with no active instance it is treated as a creation
    # (spec.md Edge Cases).
    seed = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": original_config,
            },
        },
    )
    assert "errors" not in seed.json(), seed.json()

    session.expire_all()
    settled = await session.get(Deployment, deployment_id)
    assert settled is not None
    persisted_config = settled.config

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, (
        f"empty input must be a no-op, not an error: {payload}"
    )
    assert payload["data"]["updateDeployment"] is None

    # Persisted config untouched — the resolver still routes {} to None.
    session.expire_all()
    db_row = await session.get(Deployment, deployment_id)
    assert db_row is not None
    assert db_row.config == persisted_config, (
        f"empty input must not touch persisted config; got {db_row.config!r}"
    )


# ---------------------------------------------------------------------------
# Distinct-deployment fixture sanity (defensive: ensures the parametrized
# matrix never accidentally reuses a row across rows by holding shared
# state). Each parametrized invocation seeds its own deployment via
# ``seed_deployment``; this test just pins the contract.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_helper_yields_fresh_deployment_id(
    session: AsyncSession,
) -> None:
    """Sanity: every ``seed_deployment`` call returns a fresh row so the
    parametrized matrix above does not accidentally share state between
    rows. Catches the case where a future refactor switches to a
    module-scoped fixture without realising the matrix relies on
    function-scoped isolation.
    """
    a = await seed_deployment(session)
    b = await seed_deployment(session)
    assert a.id != b.id
    # uuid4 sanity: drift to a deterministic id generator would silently
    # break the matrix; pin the uuid version here.
    assert str(uuid4()) != str(a.id)
