"""ApiScenarioDriver — wraps StyrminClient to satisfy the ScenarioDriver protocol.

Each method is a thin passthrough that normalises SDK errors into the
driver-neutral ``ScenarioActionError`` hierarchy and adapts SDK payloads
into the driver-neutral ref types.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError, StyrminError

from tests.e2e.drivers.errors import (
    ResourceNotFound,
    ScenarioActionError,
    ScenarioTimeout,
)
from tests.e2e.drivers.refs import (
    BackupRef,
    BSLRef,
    ClusterRef,
    DeploymentRef,
    DriverVersionRef,
    EnvironmentRef,
    RestoreRef,
    TimelineEntry,
)


def _normalise(exc: Exception) -> Exception:
    """Map an SDK exception onto the driver-neutral hierarchy."""
    if isinstance(exc, ResourceNotFoundError):
        return ResourceNotFound(str(exc))
    if isinstance(exc, StyrminError):
        return ScenarioActionError(str(exc))
    return exc


# Kubernetes-style enum string values used in test fixture configs vs. the
# SCREAMING_SNAKE values the typed `UpdateDeploymentInput` expects. Tests
# author scheduling blocks with K8s-doc-style strings (`NoSchedule`,
# `ScheduleAnyway`, `In`, `Equal`) for readability; the api_driver
# translates before `model_validate`.
_SCHEDULING_ENUM_MAP: dict[str, str] = {
    # tolerations.operator / match_expressions.operator
    "Equal": "EQUAL",
    "Exists": "EXISTS",
    "In": "IN",
    "NotIn": "NOT_IN",
    "DoesNotExist": "DOES_NOT_EXIST",
    # tolerations.effect
    "NoSchedule": "NO_SCHEDULE",
    "PreferNoSchedule": "PREFER_NO_SCHEDULE",
    "NoExecute": "NO_EXECUTE",
    # topology_spread_constraints.when_unsatisfiable
    "DoNotSchedule": "DO_NOT_SCHEDULE",
    "ScheduleAnyway": "SCHEDULE_ANYWAY",
}
_SCHEDULING_ENUM_KEYS = frozenset(
    {"operator", "effect", "when_unsatisfiable", "whenUnsatisfiable"}
)


def _translate_scheduling_enums(value: Any) -> Any:
    """Recursively rewrite known scheduling enum string values to the
    typed-input form. Leaves unknown keys and non-string values untouched."""
    if isinstance(value, dict):
        return {
            k: (
                _SCHEDULING_ENUM_MAP.get(v, v)
                if k in _SCHEDULING_ENUM_KEYS and isinstance(v, str)
                else _translate_scheduling_enums(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_translate_scheduling_enums(v) for v in value]
    return value


class ApiScenarioDriver:
    def __init__(self, client: StyrminClient) -> None:
        self._client = client

    def attach_to_deployment(self, *, environment_id: str) -> None:  # noqa: ARG002
        # API driver does not cache an environment context; every call takes
        # the deployment/environment id it needs. Implemented as a no-op to
        # satisfy the protocol used by UI-aware helpers.
        return

    # --- Platform setup ---------------------------------------------------

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef:
        try:
            cluster = await self._client.clusters.create(name=name, config=config)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return ClusterRef(id=str(cluster.id), name=cluster.name)

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef:
        try:
            env = await self._client.environments.create(
                name=name, cluster_id=cluster_id, config=config
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return EnvironmentRef(
            id=str(env.id),
            name=env.name,
            cluster_id=cluster_id,
        )

    async def delete_environment(self, *, environment_id: str) -> None:
        try:
            await self._client.environments.delete(environment_id=environment_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def create_backup_storage_location(
        self,
        *,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> BSLRef:
        try:
            bsl = await self._client.backup_storage_locations.create(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BSLRef(id=str(bsl.id), name=bsl.name)

    async def assign_bsl_to_environment(
        self, *, environment_id: str, bsl_id: str
    ) -> None:
        try:
            await self._client.backup_storage_locations.assign(
                environment_id=environment_id, bsl_id=bsl_id
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def load_driver_version(self, *, git_url: str, ref: str) -> DriverVersionRef:
        try:
            version = await self._client.drivers.load_version(git_url, ref)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return DriverVersionRef(
            id=str(version.id),
            application_driver_id=str(version.application_driver_id),
            driver_name=version.application_driver.name,
            version=version.version,
        )

    # --- Deployments ------------------------------------------------------

    async def create_deployment(
        self,
        *,
        driver: str,
        version: str,
        environment_id: str,
        name: str | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> DeploymentRef:
        try:
            task = await self._client.deployments.create(
                driver=driver,
                version=version,
                environment_id=environment_id,
                name=name,
                parameters=parameters,
                service_name_overrides=service_name_overrides,
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        deployment_id = task.deployment_id
        if deployment_id is None:
            raise ScenarioActionError(
                "deploy mutation returned a task without a deployment_id"
            )
        return DeploymentRef(
            id=str(deployment_id),
            status="pending",
            application_version=None,
            instance_id=None,
        )

    async def wait_for_deployment_running(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> DeploymentRef:
        deadline = time.time() + timeout
        deployment = None
        while time.time() < deadline:
            try:
                deployment = await self._client.deployments.get(deployment_id)
            except ResourceNotFoundError:
                # Deployment hasn't materialised yet — keep polling. Other
                # SDK errors (auth, 5xx, schema mismatch) propagate so a
                # broken server doesn't hide as a generic timeout.
                deployment = None
            else:
                if deployment.status == "running":
                    instance_id = None
                    if deployment.application_instance:
                        instance_id = str(deployment.application_instance.id)
                    return DeploymentRef(
                        id=str(deployment.id),
                        status=deployment.status,
                        application_version=deployment.application_version,
                        instance_id=instance_id,
                    )
            # 2s poll: a deployment becoming ready within the same second sees
            # up to a 2s detection lag (was 10s). The styrmin-server's
            # `GetDeployment` GraphQL is a single DB lookup — cheap to poll.
            await asyncio.sleep(2)
        status = deployment.status if deployment else "unknown"
        raise ScenarioTimeout(
            f"Deployment {deployment_id} did not reach 'running' after {timeout}s "
            f"(status: {status})"
        )

    async def upgrade_deployment(self, *, deployment_id: str, version: str) -> None:
        try:
            await self._client.deployments.update_version(deployment_id, version)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def update_deployment(
        self, *, deployment_id: str, config: dict[str, Any]
    ) -> None:
        """Translate the legacy ``config`` dict into a typed
        ``UpdateDeploymentInput`` and submit via the SDK.

        ``config`` mirrors the read-side ``Deployment.config`` JSON blob:
        snake_case keys with ``env_vars`` and ``components`` as dicts keyed
        by name. The SDK now expects ``list[EnvVarInput]`` and
        ``list[ComponentConfigInput]`` — the two dict-shape→list-shape
        translations happen here so test scenarios keep their compact
        dict literals.

        Every other top-level key (``scheduling``, ``ip_whitelist``,
        ``dedicated_ingress``, ``fqdn_suffix``, scheme/port/dns enum
        fields, ``parameters``, ``service_name_overrides``, etc.) is
        passed through to ``UpdateDeploymentInput.model_validate``; the
        generated Pydantic model has ``populate_by_name=True`` so it
        accepts snake_case field names or their camelCase aliases
        transparently. Nested ``SchedulingInput`` / ``AffinityTermInput``
        / ``DeploymentReferenceInput`` etc. coerce automatically.
        """
        # Imported locally so importing the api_driver doesn't pull the
        # full SDK input-types graph at module-load time (the test suite
        # imports this driver from many fixtures).
        from styrmin_sdk.models import (
            ComponentConfigInput,
            EnvVarInput,
            UpdateDeploymentInput,
        )

        prepared: dict[str, Any] = _translate_scheduling_enums(dict(config))

        env_vars = prepared.pop("env_vars", None)
        if isinstance(env_vars, dict):
            prepared["envVars"] = [
                EnvVarInput(name=name, value=value) for name, value in env_vars.items()
            ]
        elif env_vars is not None:
            # already in list-shape (typed callers) — preserve as-is.
            prepared["envVars"] = env_vars

        components = prepared.pop("components", None)
        if isinstance(components, dict):
            prepared["components"] = [
                ComponentConfigInput(
                    name=name,
                    envVars=(
                        [
                            EnvVarInput(name=ev_name, value=ev_value)
                            for ev_name, ev_value in (
                                block.get("env_vars") or {}
                            ).items()
                        ]
                        if isinstance(block, dict) and block.get("env_vars") is not None
                        else None
                    ),
                    # Container overrides (014): carry command/args through
                    # from the test-friendly dict block. ``None``/absent stays
                    # absent so a full-replacement write omits the field
                    # (omit = clear, never []).
                    command=(block.get("command") if isinstance(block, dict) else None),
                    args=(block.get("args") if isinstance(block, dict) else None),
                )
                for name, block in components.items()
            ]
        elif components is not None:
            prepared["components"] = components

        input_obj = UpdateDeploymentInput.model_validate(prepared)

        try:
            await self._client.deployments.update(deployment_id, input=input_obj)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def update_environment_via_form(
        self,
        *,
        environment_id: str,
        env_vars: dict[str, str],
    ) -> None:
        """API-side parallel of the UI form's env-var save flow.

        Implementation per ``data-model.md`` §4.3 (011-env-config-input-
        hardening): read the existing config, round-trip it through
        ``EnvironmentConfig.model_validate(config)`` so Pydantic coerces
        ``Literal["http", "https"]`` (etc.) automatically during parsing,
        then construct a typed ``UpdateEnvironmentInput`` carrying every
        persisted scalar unchanged with only ``env_vars`` replaced.

        The ``EnvironmentConfig`` Pydantic ``Literal`` fields hold the
        backend-side string values (``"http"`` / ``"NodeExternalIP"``)
        whereas ``UpdateEnvironmentInput``'s GraphQL enum types use the
        codegen names (``ExternalUrlScheme.HTTPS`` /
        ``ExternalDnsEndpointsType.NODE_EXTERNAL_IP``). The mapping below
        is the api-side analogue of the frontend's ``transformEnumValue``
        helper in ``EnvironmentConfigurationTab.helpers.ts``; both sides
        produce the same canonical input shape so the dual-entrypoint
        parametrisation is the parity check for the persisted state
        (critique E1+E2).
        """
        # Imported locally so importing the api_driver doesn't pull the
        # full backend graph at module-load time (the test suite imports
        # this driver from many fixtures).
        from styrmin_backend.context.models.config import EnvironmentConfig
        from styrmin_sdk.graphql._generated.enums import (
            ExternalDnsEndpointsType,
            ExternalUrlScheme,
        )
        from styrmin_sdk.graphql._generated.input_types import (
            EnvVarInput,
            UpdateEnvironmentInput,
        )

        external_url_scheme_map: dict[str, ExternalUrlScheme] = {
            "http": ExternalUrlScheme.HTTP,
            "https": ExternalUrlScheme.HTTPS,
        }
        external_dns_endpoints_type_map: dict[str, ExternalDnsEndpointsType] = {
            "NodeExternalIP": ExternalDnsEndpointsType.NODE_EXTERNAL_IP,
            "ClusterIP": ExternalDnsEndpointsType.CLUSTER_IP,
        }

        try:
            existing = await self._client.environments.get(
                environment_id=environment_id
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc

        raw_config = existing.config or {}
        if not isinstance(raw_config, dict):
            raise ScenarioActionError(
                "update_environment_via_form: existing Environment.config "
                f"is not a dict (got {type(raw_config).__name__})"
            )
        # Pydantic round-trip: validates the raw JSON dict and coerces
        # Literal-typed fields (external_url_scheme etc.) to their proper
        # values. Surfaces config corruption loudly rather than as a 5xx
        # at the GraphQL boundary.
        validated = EnvironmentConfig.model_validate(raw_config)

        merged_env_vars = {**(validated.env_vars or {}), **env_vars}
        input_obj = UpdateEnvironmentInput(
            envVars=[
                EnvVarInput(name=name, value=value)
                for name, value in merged_env_vars.items()
            ],
            ipWhitelist=validated.ip_whitelist,
            # ``dedicated_ingress`` and ``scheduling`` would need a
            # nested-input round-trip; the v1 form does not edit them
            # either (see ``detectNestedOverridesBlock`` in
            # EnvironmentConfigurationTab) so we leave them at None to
            # match the UI driver's behaviour. Tests that need to set
            # them must use the typed SDK directly.
            fqdnSuffix=validated.fqdn_suffix,
            externalUrlScheme=(
                external_url_scheme_map[validated.external_url_scheme]
                if validated.external_url_scheme is not None
                else None
            ),
            externalUrlPort=validated.external_url_port,
            externalDnsEndpointsType=(
                external_dns_endpoints_type_map[validated.external_dns_endpoints_type]
                if validated.external_dns_endpoints_type is not None
                else None
            ),
            ingressClass=validated.ingress_class,
            dbSize=validated.db_size,
        )

        try:
            await self._client.environments.update(
                environment_id=environment_id, input=input_obj
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]:
        try:
            entries = await self._client.deployments.get_timeline(deployment_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return [
            TimelineEntry(
                task_id=str(entry.task.id),
                # SDK's generated Pydantic model renames ``type`` → ``type_``
                # to avoid shadowing the Python builtin.
                task_type=entry.task.type_,
                task_status=entry.task.status,
                application_version=entry.application_version,
                created_on=(
                    entry.task.created_on.isoformat()
                    if entry.task.created_on is not None
                    else None
                ),
            )
            for entry in entries
        ]

    # --- Backup / Restore -------------------------------------------------

    async def create_backup(self, *, instance_id: str) -> BackupRef:
        try:
            backup = await self._client.backups.create_backup(instance_id=instance_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BackupRef(id=str(backup.id), name=backup.name, status=backup.status)

    async def wait_for_backup(
        self, *, backup_id: str, max_wait: float = 300.0
    ) -> BackupRef:
        try:
            backup = await self._client.backups.wait_for_backup(
                backup_id, max_wait=max_wait
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BackupRef(id=str(backup.id), name=backup.name, status=backup.status)

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef:
        try:
            restore = await self._client.backups.create_restore(
                backup_id=backup_id, target_namespace=target_namespace
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return RestoreRef(id=str(restore.id), status=restore.status)

    async def wait_for_restore(
        self, *, restore_id: str, max_wait: float = 600.0
    ) -> RestoreRef:
        try:
            restore = await self._client.backups.wait_for_restore(
                restore_id, max_wait=max_wait
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return RestoreRef(id=str(restore.id), status=restore.status)

    async def delete_backup(self, *, backup_id: str) -> None:
        try:
            await self._client.backups.delete_backup(backup_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def get_backup(self, *, backup_id: str) -> BackupRef:
        try:
            backup = await self._client.backups.get_backup(backup_id)
        except ResourceNotFoundError as exc:
            raise ResourceNotFound(str(exc)) from exc
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BackupRef(id=str(backup.id), name=backup.name, status=backup.status)
