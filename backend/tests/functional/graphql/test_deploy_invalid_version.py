"""Error-propagation test for a non-parseable application version on ``deploy`` (#329).

A user-supplied ``version`` that :mod:`packaging.version` cannot parse
(``tata``) must reach the GraphQL client as a ``VALIDATION_ERROR`` naming the
offending value — the same client-facing contract every other bad input
gets — never as the masked ``INTERNAL_ERROR`` / "An internal error occurred"
that :class:`StructuredErrorExtension` reserves for genuinely unexpected
exceptions.

The ``prefect_manager_mock`` fixture isn't needed: version resolution fails
before the resolver dispatches anything to the workflow engine.

The same holds for ``updateDeploymentVersion``, with and without a pinned
driver version, and a version that parses but is outside the driver's range
names the supported range in its message.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment

from ._queries import load_query
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)


@pytest.mark.asyncio
async def test_deploy_rejects_unparseable_version_with_validation_error(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    await seed_application_driver_version(
        session, driver_name="simple-app", application_supported_versions=">=1.0.0"
    )
    env = await seed_environment(session)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy"),
            "variables": {
                "driver": "simple-app",
                "version": "tata",
                "environmentId": str(env.id),
                "name": "my-app",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["deploy"] is None
    assert len(payload["errors"]) == 1, payload
    error = payload["errors"][0]

    # Client-facing validation error, never the masked internal error.
    assert error["extensions"]["code"] == "VALIDATION_ERROR", error
    assert error["message"] != "An internal error occurred", error
    # The message must tell the user which value was rejected.
    assert "tata" in error["message"], error


async def _post(client: AsyncClient, query: str, variables: dict) -> dict:
    response = await client.post(
        "/graphql", json={"query": query, "variables": variables}
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("pinned", [False, True], ids=["unpinned", "pinned"])
@pytest.mark.parametrize("version", ["latest", "1.2.3-ls45"])
async def test_update_version_rejects_unparseable_version_with_validation_error(
    client: AsyncClient,
    session: AsyncSession,
    version: str,
    pinned: bool,
) -> None:
    adv = await seed_application_driver_version(
        session, driver_name="simple-app", application_supported_versions=">=1.0.0"
    )
    adv_id = adv.id
    deployment = await seed_deployment(session, adv=adv)
    deployment_id = deployment.id

    variables: dict = {"deploymentId": str(deployment_id), "version": version}
    if pinned:
        variables["driverVersionId"] = str(adv_id)
    payload = await _post(client, load_query("update_deployment_version"), variables)

    assert payload["data"]["updateDeploymentVersion"] is None
    assert len(payload["errors"]) == 1, payload
    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", error
    assert error["message"] != "An internal error occurred", error
    assert repr(version) in error["message"], error

    # The rejected upgrade leaves the deployment as it was.
    session.expire_all()
    unchanged = await session.get(Deployment, deployment_id)
    assert unchanged is not None
    assert unchanged.application_version == "1.0.0"


@pytest.mark.asyncio
async def test_deploy_out_of_range_version_names_the_supported_ranges(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """A parseable version that no driver version supports lists the ranges."""
    await seed_application_driver_version(
        session,
        driver_name="simple-app",
        application_supported_versions=">=1.0,<2.0",
    )
    env = await seed_environment(session)

    payload = await _post(
        client,
        load_query("deploy"),
        {
            "driver": "simple-app",
            "version": "9.9.9",
            "environmentId": str(env.id),
            "name": "my-app",
        },
    )

    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", error
    assert "9.9.9" in error["message"], error
    assert "(supported: >=1.0,<2.0)" in error["message"], error


@pytest.mark.asyncio
async def test_update_version_out_of_range_version_names_the_supported_ranges(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    adv = await seed_application_driver_version(
        session,
        driver_name="simple-app",
        application_supported_versions=">=1.0,<2.0",
    )
    deployment = await seed_deployment(session, adv=adv)
    deployment_id = deployment.id

    payload = await _post(
        client,
        load_query("update_deployment_version"),
        {"deploymentId": str(deployment_id), "version": "9.9.9"},
    )

    error = payload["errors"][0]
    assert error["extensions"]["code"] == "VALIDATION_ERROR", error
    assert "9.9.9" in error["message"], error
    assert "(supported: >=1.0,<2.0)" in error["message"], error
