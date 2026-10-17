"""Read the services of an environment from the server while a flow runs (#503).

The server builds a flow's context when the change is requested, so the context does not list
the services of a deployment requested after that. The alias step reads them again.
"""

from __future__ import annotations

import httpx

from styrmin_backend import config
from styrmin_backend.agent.tasks.queries import load_query

_LIST_ENVIRONMENT_SERVICES = load_query("list_environment_services")
#: Bounds how long the alias step waits for the server.
REQUEST_TIMEOUT_SECONDS = 10.0


class EnvironmentServicesReadError(Exception):
    """The server's list of an environment's services could not be read."""


async def read_environment_services(environment_id: str) -> list[dict[str, str]]:
    """The ``resolved_name`` and ``deployment_id`` of each service of the environment.

    Sends the action token of the flow (ADR-059).
    """
    api_token = config.SETTINGS.agent.api_token
    if api_token is None:
        raise EnvironmentServicesReadError("the flow has no action token")
    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_token.get_secret_value()}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                config.SETTINGS.url.graphql,
                json={
                    "query": _LIST_ENVIRONMENT_SERVICES,
                    "variables": {"environmentId": environment_id},
                },
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EnvironmentServicesReadError(f"the request failed: {exc}") from exc
    if errors := payload.get("errors"):
        raise EnvironmentServicesReadError(
            f"GraphQL error: {errors[0].get('message', errors)}"
        )
    try:
        services = payload["data"]["environmentServices"]
        return [
            {
                "resolved_name": svc["resolvedName"],
                "deployment_id": str(svc["deploymentId"]),
            }
            for svc in services
        ]
    except (KeyError, TypeError) as exc:
        raise EnvironmentServicesReadError(f"unexpected response: {exc!r}") from exc
