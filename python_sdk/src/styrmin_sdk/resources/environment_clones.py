"""Environment clone resource operations.

A clone copies a live environment into a *new* environment on the same cluster,
built entirely from a fresh environment backup of the source (spec FR-002 /
FR-007). It composes the environment-backup machinery
(:mod:`styrmin_sdk.resources.environment_backups`) rather than replacing it: the
capture is an ordinary environment backup, and each included deployment's
constituent backup is restored into a freshly created counterpart deployment.

Like the environment-level backup and restore records, a clone's ``status`` is
*derived* on every read from its own steps and never stored (FR-009), so
polling for completion means polling for a terminal derived status rather than
watching a column flip. Unlike them, a clone can already be ``IN_PROGRESS``
the instant it is registered — any deployment skipped upfront is recorded with
the clone row itself, which is enough to move the derivation off ``PENDING``.
Do not treat ``PENDING`` as a guaranteed first observation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.clone_environment import (
    CloneEnvironment,
    CloneEnvironmentCloneEnvironment,
)
from styrmin_sdk.graphql._generated.enums import EnvironmentCloneStatus
from styrmin_sdk.graphql._generated.get_environment_clone import (
    GetEnvironmentClone,
    GetEnvironmentCloneEnvironmentClone,
)
from styrmin_sdk.graphql._generated.list_environment_clones import (
    ListEnvironmentClones,
    ListEnvironmentClonesEnvironmentClones,
)
from styrmin_sdk.resources._base import BaseResource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from styrmin_sdk.graphql._generated.input_types import UpdateEnvironmentInput

#: Derived clone statuses that will never change again. ``PARTIAL`` is terminal:
#: it means some source deployments did not make it into the clone while the
#: rest did, which is a final outcome, not a transitional one.
TERMINAL_ENVIRONMENT_CLONE_STATUSES: Final[frozenset[EnvironmentCloneStatus]] = frozenset(
    {
        EnvironmentCloneStatus.COMPLETED,
        EnvironmentCloneStatus.PARTIAL,
        EnvironmentCloneStatus.FAILED,
    }
)


class EnvironmentCloneResource(BaseResource):
    """``client.environment_clones`` — clone an environment, then track the clone."""

    async def create(
        self,
        name: str,
        *,
        environment_id: str | UUID | None = None,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
        deployment_ids: Sequence[str | UUID] | None = None,
        config_override: UpdateEnvironmentInput | None = None,
        clear_config_fields: Sequence[str] | None = None,
    ) -> CloneEnvironmentCloneEnvironment:
        """Clone an environment into a new environment named *name*.

        Requires the ``ADMIN`` role — a clone strictly supersets what an
        environment restore does, and that already carries ADMIN.

        Only *name* is positional; everything else is keyword-only, so a call
        never reads as a row of anonymous identifiers.

        The source is addressed by the usual dual-identifier convention
        (``environment_id`` **or** ``environment_name``, optionally scoped by
        ``cluster_id`` / ``cluster_name``).

        ``deployment_ids`` selects which of the source's eligible deployments to
        include; omitting it includes all eligible ones (FR-003). Every source
        deployment considered is accounted for on ``deployment_results`` —
        cloned, skipped with a reason, or failed with a reason (SC-003).

        ``config_override`` is an environment-config override merged over the
        captured source config before any counterpart deployment comes up, and
        ``clear_config_fields`` removes captured fields outright before that
        merge (FR-006). The two are asymmetric on purpose:

        * ``config_override`` is **sent** as a GraphQL ``UpdateEnvironmentInput``
          (camelCase wire fields — ``fqdnSuffix``, ``ingressClass``, …) but is
          **stored and returned** on ``EnvironmentClone.config_override`` as
          canonical snake_case ``EnvironmentConfig`` JSON
          (``{"fqdn_suffix": ...}``). Do not round-trip the returned JSON
          straight back into this argument without re-validating it through
          ``UpdateEnvironmentInput`` — the Pydantic model accepts either
          spelling, so validating it is the conversion.
        * ``clear_config_fields`` takes **snake_case** top-level
          ``EnvironmentConfig`` field names (``"ingress_class"``) in both
          directions. Names that are not fields are rejected upfront with
          ``VALIDATION_ERROR``.

        Returns as soon as the clone is registered; the returned ``status`` is
        typically ``PENDING`` or ``IN_PROGRESS``. Upfront failures — a taken
        target name, an unknown source or selected deployment, an invalid
        override, another environment-level operation already running on the
        source — raise before anything is created (FR-011). A selection that
        leaves out a deployment that a copied affinity term names, or that
        includes such a deployment when it is not eligible, raises
        ``OperationFailedError`` with ``VALIDATION_ERROR``. Its
        ``extensions["deployments"]`` lists each such deployment with its
        ``deployment_id``, ``deployment_name``, ``reason`` and the ``paths`` of
        the terms that name it. ``deployment_id`` is ``None`` for a name that no
        live deployment of the source environment has, and ``deployment_name``
        is ``None`` for an id that is not a deployment of the source
        environment. ``reason`` is text for people to read.
        """
        variables: dict[str, Any] = {"name": name}
        if environment_id is not None:
            variables["environmentId"] = str(environment_id)
        if environment_name is not None:
            variables["environmentName"] = environment_name
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        if deployment_ids is not None:
            variables["deploymentIds"] = [str(deployment_id) for deployment_id in deployment_ids]
        if config_override is not None:
            variables["configOverride"] = config_override.model_dump(by_alias=True, exclude_none=True)
        if clear_config_fields is not None:
            variables["clearConfigFields"] = list(clear_config_fields)

        result = await self._transport.execute(load_query("clone_environment"), variables)
        self._check_graphql_errors(result)
        return self._parse(
            CloneEnvironment,
            result["data"],
            "clone_environment",
            CloneEnvironmentCloneEnvironment,
        )

    async def get(self, environment_clone_id: str | UUID) -> GetEnvironmentCloneEnvironmentClone:
        """Get one clone record by id.

        The query is non-nullable: an unknown id raises
        :class:`~styrmin_sdk.exceptions.ResourceNotFoundError` rather than
        returning ``None``.
        """
        result = await self._transport.execute(
            load_query("get_environment_clone"),
            {"environmentCloneId": str(environment_clone_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            GetEnvironmentClone,
            result["data"],
            "environment_clone",
            GetEnvironmentCloneEnvironmentClone,
        )

    async def list(self, environment_id: str | UUID) -> list[ListEnvironmentClonesEnvironmentClones]:
        """List the clones taken *of* an environment, newest first.

        Scoped by **source** environment. A clone-born environment's own
        provenance is the source-side record's ``created_environment`` link, not
        an entry in its own list.
        """
        result = await self._transport.execute(
            load_query("list_environment_clones"),
            {"environmentId": str(environment_id)},
        )
        self._check_graphql_errors(result)
        data = ListEnvironmentClones.model_validate(result["data"])
        return data.environment_clones

    async def wait_for_clone(
        self,
        environment_clone_id: str | UUID,
        max_wait: float = 1800,
        interval: float = 5,
    ) -> GetEnvironmentCloneEnvironmentClone:
        """Poll :meth:`get` until the derived status is terminal.

        Terminal means ``COMPLETED``, ``PARTIAL`` or ``FAILED``. The default
        ``max_wait`` is the longest of the environment-level helpers because a
        clone contains a full capture *and* a full restore, plus creating an
        environment and its counterpart deployments in between.

        Returns the last observed record when ``max_wait`` elapses first, so
        callers always get a value and can inspect the non-terminal status
        themselves rather than catching a timeout.
        """
        elapsed = 0.0
        while elapsed < max_wait:
            environment_clone = await self.get(environment_clone_id)
            if environment_clone.status in TERMINAL_ENVIRONMENT_CLONE_STATUSES:
                return environment_clone
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get(environment_clone_id)
