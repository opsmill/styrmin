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

    def _describe_http_error(self, exc: httpx.HTTPError, method: str, path: str) -> str:
        """Build a human-readable message for an httpx transport failure.

        Several httpx exceptions — notably ``ConnectError``, ``ConnectTimeout``,
        and ``ReadTimeout`` — carry an empty ``str()``. Wrapping those directly
        (``StyrminTransportError(str(exc))``) produced a blank message that gave
        the user nothing to act on (e.g. ``deployments apply`` printed
        ``failed <name>: manifest <path>:`` with no reason). Always include the
        exception kind and the target URL, and add a connectivity hint for the
        common "server unreachable / wrong address" cases so the operator knows
        where to look.
        """
        kind = type(exc).__name__
        target = f"{method} {self._client.base_url}{path}"
        detail = str(exc).strip()

        suffix = f" ({detail})" if detail else ""
        if isinstance(exc, httpx.TimeoutException):
            return (
                f"{kind}: request to {target} timed out after "
                f"{self._client.timeout.read}s — is the server reachable and "
                f"healthy at {self._client.base_url}?{suffix}"
            )
        if isinstance(exc, httpx.ConnectError):
            return (
                f"{kind}: could not connect to {target} — is the server running "
                f"and is the address correct ({self._client.base_url})?{suffix}"
            )
        if detail:
            return f"{kind}: {detail} ({target})"
        return f"{kind}: request to {target} failed (no further detail from httpx)"

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
            raise StyrminTransportError(self._describe_http_error(exc, "POST", "/graphql")) from exc

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
            raise StyrminTransportError(self._describe_http_error(exc, "GET", path)) from exc

        return response.json()

    def set_authorization(self, token: str | None) -> None:
        """Set or clear the Bearer Authorization header for subsequent requests."""
        if token is None:
            self._client.headers.pop("Authorization", None)
        else:
            self._client.headers["Authorization"] = f"Bearer {token}"

    async def close(self) -> None:
        await self._client.aclose()
