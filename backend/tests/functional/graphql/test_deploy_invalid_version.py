"""Error-propagation test for a non-parseable application version on ``deploy`` (#329).

A user-supplied ``version`` that :mod:`packaging.version` cannot parse
(``tata``) must reach the GraphQL client as a ``VALIDATION_ERROR`` naming the
offending value — the same client-facing contract every other bad input
gets — never as the masked ``INTERNAL_ERROR`` / "An internal error occurred"
that :class:`StructuredErrorExtension` reserves for genuinely unexpected
exceptions.

The ``prefect_manager_mock`` fixture isn't needed: version resolution fails
before the resolver dispatches anything to the workflow engine.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from ._queries import load_query
from .seeds import seed_application_driver_version, seed_environment


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
