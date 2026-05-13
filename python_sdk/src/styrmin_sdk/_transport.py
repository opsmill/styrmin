"""Low-level GraphQL execution over httpx."""

from __future__ import annotations

from typing import Any

import httpx

from styrmin_sdk.exceptions import StyrminTransportError


class Transport:
    """Internal HTTP + GraphQL transport.

    Holds a persistent ``httpx.AsyncClient`` for the lifetime of the
    ``StyrminClient`` that owns it.
    """

    def __init__(
        self,
        server_address: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=server_address,
            timeout=timeout,
            headers=headers or {},
        )

    async def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation and return the full result dict.

        Returns the full GraphQL response including both ``data`` and ``errors``
        keys. Callers should use ``BaseResource._check_graphql_errors()`` to
        inspect structured errors with ``extensions.code``.

        Raises:
            StyrminTransportError: On HTTP-level failures.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self._client.post("/graphql", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise StyrminTransportError(str(exc)) from exc

        return response.json()

    async def get(self, path: str) -> dict[str, Any]:
        """Perform an HTTP GET and return the parsed JSON body.

        Raises:
            StyrminTransportError: On HTTP-level failures.
        """
        try:
            response = await self._client.get(path)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise StyrminTransportError(str(exc)) from exc

        return response.json()

    def set_authorization(self, token: str | None) -> None:
        """Set or clear the Bearer Authorization header for subsequent requests."""
        if token is None:
            self._client.headers.pop("Authorization", None)
        else:
            self._client.headers["Authorization"] = f"Bearer {token}"

    async def close(self) -> None:
        await self._client.aclose()
