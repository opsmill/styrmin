"""``Deployment.resolvedScheduling`` expands each level's deployment references before the merge (027).

An affinity term's error path names the config level that holds it, and the
merged config still gives every term of every level as a label selector.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Component,
    Deployment,
    DeploymentState,
    Environment,
)

from ._queries import load_query
from .seeds import seed_deployment, seed_environment

_TOPOLOGY_KEY = "kubernetes.io/hostname"


def _anti_affinity_config(deployment_id: UUID) -> dict:
    return {
        "scheduling": {
            "pod_anti_affinity": {
                "preferred": [
                    {
                        "weight": 10,
                        "term": {
                            "topology_key": _TOPOLOGY_KEY,
                            "deployment_ref": {"deployment_id": str(deployment_id)},
                        },
                    }
                ]
            }
        }
    }


async def _seed_scheduled_deployment(
    session: AsyncSession, environment: Environment, config: dict | None
) -> Deployment:
    deployment = await seed_deployment(session, environment=environment, name="web")
    deployment.config = config
    session.add(deployment)
    session.add(
        Component(
            name="server",
            config={"identifier": {"label": {"app": "server"}}},
            enabled=True,
            deployment_id=deployment.id,
        )
    )
    await session.commit()
    return deployment


async def _query(client: AsyncClient, deployment_id: UUID) -> dict:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_deployment_resolved_scheduling"),
            "variables": {"deploymentId": str(deployment_id)},
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_resolved_scheduling_merges_the_expanded_levels(
    client: AsyncClient, session: AsyncSession
) -> None:
    environment = await seed_environment(session)
    api = await seed_deployment(session, environment=environment, name="api")
    cache = await seed_deployment(session, environment=environment, name="cache")
    environment.config = _anti_affinity_config(api.id)
    session.add(environment)
    await session.commit()
    web = await _seed_scheduled_deployment(
        session, environment, _anti_affinity_config(cache.id)
    )

    payload = await _query(client, web.id)

    assert "errors" not in payload, payload
    [entry] = payload["data"]["deployment"]["resolvedScheduling"]
    assert entry["componentName"] == "server"
    preferred = entry["config"]["pod_anti_affinity"]["preferred"]
    assert [weighted["term"]["label_selector"] for weighted in preferred] == [
        {"match_labels": {"styrmin/deployment_id": str(api.id)}},
        {"match_labels": {"styrmin/deployment_id": str(cache.id)}},
    ]
    assert all("deployment_ref" not in weighted["term"] for weighted in preferred)
    assert entry["provenance"]["pod_anti_affinity"] == "deployment"


@pytest.mark.asyncio
async def test_resolved_scheduling_refuses_tombstoned_deployment_with_level_path(
    client: AsyncClient, session: AsyncSession
) -> None:
    environment = await seed_environment(session)
    postgres = await seed_deployment(session, environment=environment, name="postgres")
    postgres.status = DeploymentState.DELETED
    postgres.deleted_at = datetime.now(UTC)
    session.add(postgres)
    environment.config = _anti_affinity_config(postgres.id)
    session.add(environment)
    await session.commit()
    web = await _seed_scheduled_deployment(session, environment, None)
    # The refusal rolls the session back, which expires the seeded rows.
    postgres_id = postgres.id

    payload = await _query(client, web.id)

    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", payload
    assert error["extensions"]["path"] == (
        "environment.config.scheduling.pod_anti_affinity.preferred[0].term"
    )
    assert error["extensions"]["deployment_id"] == str(postgres_id)
    assert error["extensions"]["deployment_name"] == "postgres"
    assert error["extensions"]["deleted"] is True
