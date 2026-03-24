"""Application driver resource operations."""

from __future__ import annotations

from styrmin_sdk._queries import load_query
from styrmin_sdk.models.driver import ApplicationDriverVersion
from styrmin_sdk.resources._base import BaseResource


class DriverResource(BaseResource):
    async def load_version(self, repository_url: str, branch: str) -> ApplicationDriverVersion:
        result = await self._transport.execute(
            load_query("load_version"),
            {"repositoryUrl": repository_url, "branch": branch},
        )
        self._check_graphql_errors(result)
        return ApplicationDriverVersion.model_validate(result["data"]["loadRemoteApplicationDriverVersion"])

    async def load_local_version(self, path: str) -> ApplicationDriverVersion:
        result = await self._transport.execute(
            load_query("load_local_version"),
            {"path": path},
        )
        self._check_graphql_errors(result)
        return ApplicationDriverVersion.model_validate(result["data"]["loadLocalApplicationDriverVersion"])
