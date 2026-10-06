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
from styrmin_sdk.graphql._generated import (
    GetBackupBackup,
    GetBackupBackupSteps,
    GetDeploymentTimelineDeploymentTimelineTaskSteps,
    GetRestoreRestoreSteps,
)

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
    EnvironmentBackupConstituentRef,
    EnvironmentBackupRef,
    EnvironmentCloneDeploymentResultRef,
    EnvironmentCloneRef,
    EnvironmentRef,
    EnvironmentRestoreRef,
    EnvironmentRestoreSkipRef,
    RestoreRef,
    StepErrorRef,
    StepRef,
    TaskLinkRef,
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
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


def _constituent_outcome(constituent: Any) -> str:
    """Classify one constituent exactly as the frontend's ``classifyConstituent``.

    Keeping the two implementations in lock-step is what lets a scenario assert
    on ``EnvironmentBackupConstituentRef.outcome`` without a ``driver_mode``
    branch. Constituent backups are ordinary per-instance backups, so their
    ``status`` is the lowercase Backup string, not the parent's uppercase
    derived enum — compared case-insensitively for the same reason the frontend
    does it.
    """
    if constituent.error is not None:
        return "error"
    if constituent.backup is None:
        # Neither a backup nor a creation error: the constituent was deleted
        # individually after the snapshot was taken. The gap is deliberately
        # visible (spec FR-010 / US3) rather than folded into ``failed``.
        return "missing"
    match constituent.backup.status.lower():
        case "completed":
            return "completed"
        case "failed":
            return "failed"
        case _:
            return "in-flight"


def _step_ref(
    step: GetDeploymentTimelineDeploymentTimelineTaskSteps
    | GetBackupBackupSteps
    | GetRestoreRestoreSteps,
) -> StepRef:
    # Backup and restore steps have no FluxCD detail and are never superseded.
    superseded_by = getattr(step, "superseded_by", None)
    return StepRef(
        id=str(step.id),
        key=step.key,
        name=step.name,
        kind=step.kind.value,
        status=step.status.value,
        started_at=step.started_at.isoformat() if step.started_at else None,
        ended_at=step.ended_at.isoformat() if step.ended_at else None,
        attempt_count=step.attempt_count,
        errors=tuple(
            StepErrorRef(
                attempt=error.attempt,
                message=error.message,
                occurred_at=error.occurred_at.isoformat(),
            )
            for error in step.errors
        ),
        detail=getattr(step, "detail", None),
        has_output=step.has_output,
        superseded_by=str(superseded_by.id) if superseded_by else None,
    )


def _backup_ref(backup: GetBackupBackup) -> BackupRef:
    return BackupRef(
        id=str(backup.id),
        name=backup.name,
        status=backup.status,
        steps=tuple(_step_ref(step) for step in backup.steps),
    )


def _environment_backup_ref(environment_backup: Any) -> EnvironmentBackupRef:
    """Adapt any of the generated EnvironmentBackup payloads into a ref.

    ``create`` / ``get`` / ``list`` each produce a distinct generated Pydantic
    class with the same field names, so this reads them structurally.
    """
    return EnvironmentBackupRef(
        id=str(environment_backup.id),
        name=environment_backup.name,
        status=environment_backup.status.value,
        constituents=tuple(
            EnvironmentBackupConstituentRef(
                deployment_id=str(constituent.deployment_id),
                deployment_name=constituent.deployment_name,
                outcome=_constituent_outcome(constituent),
                backup_id=(
                    str(constituent.backup.id)
                    if constituent.backup is not None
                    else None
                ),
                backup_status=(
                    constituent.backup.status
                    if constituent.backup is not None
                    else None
                ),
                error=constituent.error,
            )
            for constituent in environment_backup.constituents
        ),
    )


def _environment_restore_ref(environment_restore: Any) -> EnvironmentRestoreRef:
    """Adapt any of the generated EnvironmentRestore payloads into a ref."""
    return EnvironmentRestoreRef(
        id=str(environment_restore.id),
        status=environment_restore.status.value,
        restore_ids=tuple(str(restore.id) for restore in environment_restore.restores),
        skipped=tuple(
            EnvironmentRestoreSkipRef(
                deployment_id=str(entry.deployment_id),
                deployment_name=entry.deployment_name,
                reason=entry.reason,
            )
            for entry in environment_restore.skipped_constituents
        ),
    )


#: The ``clone_errors`` step prefix the backend writes when the environment a
#: clone created is deleted through ordinary environment deletion — the
#: supported discard path (spec SC-005). Kept in lock-step with the frontend's
#: ``DISCARD_STEP_PREFIX`` in ``EnvironmentClonesSection.tsx``: the UI driver
#: reads ``data-environment-clone-discarded`` straight off the row, so this is
#: how the API driver arrives at the identical boolean.
_CLONE_DISCARD_STEP_PREFIX = "created_environment_deleted:"


def _environment_clone_ref(environment_clone: Any) -> EnvironmentCloneRef:
    """Adapt any of the generated EnvironmentClone payloads into a ref.

    ``create`` / ``get`` / ``list`` each produce a distinct generated Pydantic
    class with the same field names, so this reads them structurally — same
    approach as :func:`_environment_backup_ref`.

    ``list`` deliberately projects less than ``get`` (no ``counterpartDeployment
    Id`` / ``restoreId`` on the results), which is why every scenario read goes
    through ``get_environment_clone``; the ref shape stays uniform and the
    thinner projection simply reports ``None`` for what it did not ask for.
    """
    clone_errors = tuple(environment_clone.clone_errors)
    return EnvironmentCloneRef(
        id=str(environment_clone.id),
        name=environment_clone.name,
        status=environment_clone.status.value,
        created_environment_id=(
            str(environment_clone.created_environment.id)
            if environment_clone.created_environment is not None
            else None
        ),
        environment_backup_id=(
            str(environment_clone.environment_backup.id)
            if getattr(environment_clone, "environment_backup", None) is not None
            else None
        ),
        discarded=any(
            entry.startswith(_CLONE_DISCARD_STEP_PREFIX) for entry in clone_errors
        ),
        deployment_results=tuple(
            EnvironmentCloneDeploymentResultRef(
                deployment_id=str(result.deployment_id),
                deployment_name=result.deployment_name,
                outcome=result.outcome.value,
                reason=result.reason,
                counterpart_deployment_id=(
                    str(result.counterpart_deployment_id)
                    if getattr(result, "counterpart_deployment_id", None) is not None
                    else None
                ),
                restore_id=(
                    str(result.restore_id)
                    if getattr(result, "restore_id", None) is not None
                    else None
                ),
            )
            for result in environment_clone.deployment_results
        ),
        clone_errors=clone_errors,
    )


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

    async def upgrade_deployment(
        self,
        *,
        deployment_id: str,
        version: str,
        driver_version_id: str | None = None,
    ) -> None:
        try:
            await self._client.deployments.update_version(
                deployment_id, version, driver_version_id=driver_version_id
            )
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
                    image=(block.get("image") if isinstance(block, dict) else None),
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

    async def set_component_env_vars(
        self, *, deployment_id: str, component: str, env_vars: dict[str, str]
    ) -> None:
        await self._replace_component_slot(
            deployment_id=deployment_id,
            component=component,
            slot="env_vars",
            value=dict(env_vars) if env_vars else None,
        )

    async def set_component_image(
        self, *, deployment_id: str, component: str, image: str | None
    ) -> None:
        await self._replace_component_slot(
            deployment_id=deployment_id, component=component, slot="image", value=image
        )

    async def pinned_image_components(
        self,
        *,
        deployment_id: str,
        target_version: str,  # noqa: ARG002 — the UI types it; the listing ignores it
    ) -> list[str]:
        from styrmin_sdk.models import pinned_image_components

        try:
            deployment = await self._client.deployments.get(deployment_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        # Same filter as the upgrade dialog's notice: containerless overrides never apply.
        return pinned_image_components(
            {
                row.component: row.reference
                for row in deployment.component_image_overrides
                if row.is_applicable
            }
        )

    async def _replace_component_slot(
        self, *, deployment_id: str, component: str, slot: str, value: Any
    ) -> None:
        # ``updateDeployment`` is full-replacement: resubmit the stored config
        # with only this component slot swapped; ``None`` clears it.
        try:
            deployment = await self._client.deployments.get(deployment_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc

        config: dict[str, Any] = dict(deployment.config or {})
        components = {
            name: dict(block)
            for name, block in (config.get("components") or {}).items()
        }
        block = {
            key: existing
            for key, existing in components.pop(component, {}).items()
            if key != slot and existing is not None
        }
        if value is not None:
            block[slot] = value
        if block:
            components[component] = block
        config["components"] = components

        await self.update_deployment(deployment_id=deployment_id, config=config)

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
            # 016: carried for the same reason the UI's
            # ``buildFullReplacementInput`` carries it — ``updateEnvironment``
            # is full-replacement, so omitting the retention policy here would
            # clear it on every env-var save and break the api/ui parity this
            # dual-entrypoint driver pair exists to check.
            backupTtl=validated.backup_ttl,
        )

        try:
            await self._client.environments.update(
                environment_id=environment_id, input=input_obj
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def set_environment_backup_ttl(
        self,
        *,
        environment_id: str,
        ttl: str | None,
    ) -> None:
        """API-side parallel of the retention form's save flow (016 / FR-001).

        ``updateEnvironment`` is full-replacement (009-environment-update):
        every field omitted from the input is persisted as its unset state.
        Scenario environments are session-shared, so read the persisted config
        back, round-trip it through ``EnvironmentConfig`` (which coerces the
        ``Literal``-typed scalars), and resubmit it with only ``backup_ttl``
        replaced — the api-side equivalent of the frontend's
        ``buildFullReplacementInput`` called with a ``backupTtl`` override.

        ``ttl=None`` clears the policy, which is how a scenario reverts a
        shared environment to its pre-test state.
        """
        # Imported lazily for the same reason ``update_environment_via_form``
        # does: keep the backend graph and the regenerated SDK enums off the
        # module import path (many fixtures import this driver).
        from styrmin_backend.context.models.config import EnvironmentConfig
        from styrmin_sdk.graphql._generated.enums import (
            ExternalDnsEndpointsType,
            ExternalUrlScheme,
        )
        from styrmin_sdk.graphql._generated.input_types import (
            EnvVarInput,
            UpdateEnvironmentInput,
        )

        # ``EnvironmentConfig`` holds the backend-side Literal values ("http",
        # "NodeExternalIP") whereas the GraphQL input types use the codegen
        # enum names — the same mapping ``update_environment_via_form`` and
        # the frontend's ``transformEnumValue`` perform.
        url_scheme_map: dict[str, ExternalUrlScheme] = {
            "http": ExternalUrlScheme.HTTP,
            "https": ExternalUrlScheme.HTTPS,
        }
        dns_endpoints_type_map: dict[str, ExternalDnsEndpointsType] = {
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
                "set_environment_backup_ttl: existing Environment.config is "
                f"not a dict (got {type(raw_config).__name__})"
            )
        validated = EnvironmentConfig.model_validate(raw_config)

        # ``dedicated_ingress`` / ``scheduling`` would need a nested-input
        # round-trip that no scenario sets on these environments — and the UI
        # form refuses to submit at all when either is present. Fail loudly
        # rather than silently clearing them if that ever changes, so the two
        # entrypoints stay honest about the same limitation.
        assert validated.dedicated_ingress is None, (
            "scenario environment gained a dedicated_ingress block; this "
            "driver method would silently clear it — extend it with the "
            "nested input"
        )
        assert validated.scheduling is None, (
            "scenario environment gained a scheduling block; this driver "
            "method would silently clear it — extend it with the nested input"
        )

        input_obj = UpdateEnvironmentInput(
            envVars=[
                EnvVarInput(name=name, value=value)
                for name, value in (validated.env_vars or {}).items()
            ]
            or None,
            ipWhitelist=validated.ip_whitelist,
            fqdnSuffix=validated.fqdn_suffix,
            externalUrlScheme=(
                url_scheme_map[validated.external_url_scheme]
                if validated.external_url_scheme is not None
                else None
            ),
            externalUrlPort=validated.external_url_port,
            externalDnsEndpointsType=(
                dns_endpoints_type_map[validated.external_dns_endpoints_type]
                if validated.external_dns_endpoints_type is not None
                else None
            ),
            ingressClass=validated.ingress_class,
            dbSize=validated.db_size,
            backupTtl=ttl,
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
                steps=tuple(_step_ref(step) for step in entry.task.steps),
                started_by_step_id=(
                    str(entry.task.started_by_step_id)
                    if entry.task.started_by_step_id is not None
                    else None
                ),
                result=entry.task.result.value,
                # The timeline reads only the id and type of the starting task.
                started_by=(
                    TaskLinkRef(
                        id=str(entry.task.started_by.id),
                        type=entry.task.started_by.type_,
                        result=None,
                    )
                    if entry.task.started_by is not None
                    else None
                ),
                started_tasks=tuple(
                    TaskLinkRef(
                        id=str(started.id),
                        type=started.type_,
                        result=started.result.value,
                    )
                    for started in entry.task.started_tasks
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
        return _backup_ref(backup)

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
        return RestoreRef(
            id=str(restore.id),
            status=restore.status,
            steps=tuple(_step_ref(step) for step in restore.steps),
        )

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
        return _backup_ref(backup)

    # --- Environment-level backup / restore -------------------------------

    async def create_environment_backup(
        self, *, environment_id: str
    ) -> EnvironmentBackupRef:
        try:
            environment_backup = await self._client.environment_backups.create(
                environment_id
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return _environment_backup_ref(environment_backup)

    async def get_environment_backup(
        self, *, environment_backup_id: str
    ) -> EnvironmentBackupRef:
        try:
            environment_backup = await self._client.environment_backups.get(
                environment_backup_id
            )
        except ResourceNotFoundError as exc:
            raise ResourceNotFound(str(exc)) from exc
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return _environment_backup_ref(environment_backup)

    async def wait_for_environment_backup(
        self, *, environment_backup_id: str, max_wait: float = 600.0
    ) -> EnvironmentBackupRef:
        """Poll the derived parent status via the SDK's own waiter.

        ``EnvironmentBackupResource.wait_for_backup`` returns the last observed
        snapshot rather than raising on timeout, so the non-terminal case is
        converted into a ``ScenarioTimeout`` here — same failure mode the UI
        driver produces, with the observed status in the message.
        """
        try:
            environment_backup = await self._client.environment_backups.wait_for_backup(
                environment_backup_id, max_wait=max_wait
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        ref = _environment_backup_ref(environment_backup)
        if ref.status not in TERMINAL_ENVIRONMENT_OPERATION_STATUSES:
            raise ScenarioTimeout(
                f"environment backup {environment_backup_id} did not reach a "
                f"terminal derived status within {max_wait}s (status: {ref.status})"
            )
        return ref

    async def restore_environment_backup(
        self, *, environment_backup_id: str
    ) -> EnvironmentRestoreRef:
        try:
            environment_restore = await self._client.environment_backups.restore(
                environment_backup_id
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return _environment_restore_ref(environment_restore)

    async def wait_for_environment_restore(
        self, *, environment_restore_id: str, max_wait: float = 900.0
    ) -> EnvironmentRestoreRef:
        try:
            environment_restore = (
                await self._client.environment_backups.wait_for_restore(
                    environment_restore_id, max_wait=max_wait
                )
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        ref = _environment_restore_ref(environment_restore)
        if ref.status not in TERMINAL_ENVIRONMENT_OPERATION_STATUSES:
            raise ScenarioTimeout(
                f"environment restore {environment_restore_id} did not reach a "
                f"terminal derived status within {max_wait}s (status: {ref.status})"
            )
        return ref

    async def delete_environment_backup(self, *, environment_backup_id: str) -> None:
        try:
            await self._client.environment_backups.delete(environment_backup_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    # --- Environment clone ------------------------------------------------

    async def clone_environment(
        self,
        *,
        environment_id: str,
        name: str,
        deployment_ids: list[str] | None = None,
        config_override: dict[str, Any] | None = None,
        clear_config_fields: list[str] | None = None,
    ) -> EnvironmentCloneRef:
        """Submit one ``cloneEnvironment`` through the typed SDK resource.

        ``config_override`` arrives as the camelCase dict the protocol
        specifies and is validated through ``UpdateEnvironmentInput`` here — the
        generated model sets ``populate_by_name``, so the camelCase aliases the
        UI textarea also takes are accepted directly, and validating is the
        conversion.

        ``deployment_ids`` is forwarded as-is so the tri-state survives: the SDK
        omits the GraphQL argument for ``None`` and sends ``[]`` verbatim for the
        configuration-only request.
        """
        # Imported locally for the same reason ``update_environment_via_form``
        # defers its imports: keep the regenerated SDK input types off this
        # module's import path, which many fixtures pull in.
        from styrmin_sdk.graphql._generated.input_types import UpdateEnvironmentInput

        override = (
            UpdateEnvironmentInput.model_validate(config_override)
            if config_override is not None
            else None
        )
        try:
            environment_clone = await self._client.environment_clones.create(
                name,
                environment_id=environment_id,
                deployment_ids=deployment_ids,
                config_override=override,
                clear_config_fields=clear_config_fields,
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return _environment_clone_ref(environment_clone)

    async def get_environment_clone(
        self, *, environment_clone_id: str
    ) -> EnvironmentCloneRef:
        try:
            environment_clone = await self._client.environment_clones.get(
                environment_clone_id
            )
        except ResourceNotFoundError as exc:
            raise ResourceNotFound(str(exc)) from exc
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return _environment_clone_ref(environment_clone)

    async def wait_for_environment_clone(
        self, *, environment_clone_id: str, max_wait: float = 1800.0
    ) -> EnvironmentCloneRef:
        """Poll the derived status via the SDK's own waiter.

        ``EnvironmentCloneResource.wait_for_clone`` returns the last observed
        record rather than raising on timeout, so the non-terminal case is
        converted into a ``ScenarioTimeout`` here — the same failure mode the UI
        driver produces, with the observed status in the message.
        """
        try:
            environment_clone = await self._client.environment_clones.wait_for_clone(
                environment_clone_id, max_wait=max_wait
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        ref = _environment_clone_ref(environment_clone)
        if ref.status not in TERMINAL_ENVIRONMENT_OPERATION_STATUSES:
            raise ScenarioTimeout(
                f"environment clone {environment_clone_id} did not reach a "
                f"terminal derived status within {max_wait}s (status: {ref.status})"
            )
        return ref
