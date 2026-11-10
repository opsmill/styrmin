"""Deployment resource operations."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import yaml
from pydantic import ValidationError

from styrmin_sdk._queries import load_query
from styrmin_sdk._wait import (
    DELETED_STATUS,
    TERMINAL_FAILURE_STATUSES,
    TERMINAL_SUCCESS_STATUSES,
    WAIT_POLL_INTERVAL_SECONDS,
    WAIT_TIMEOUT_SECONDS,
    is_terminal_failure,
    is_terminal_success,
)
from styrmin_sdk.exceptions import (
    ApplyError,
    BatchNameConflictError,
    DriverMismatchError,
    EnvironmentAmbiguityError,
    EnvironmentNotFoundError,
    IncompatibleServerError,
    ManifestValidationError,
    ResourceAlreadyExistsError,
    StyrminAPIError,
    StyrminError,
)
from styrmin_sdk.graphql._generated.delete_deployment import (
    DeleteDeployment,
    DeleteDeploymentDeleteDeployment,
)
from styrmin_sdk.graphql._generated.deploy import Deploy, DeployDeploy
from styrmin_sdk.graphql._generated.enums import TaskResult
from styrmin_sdk.graphql._generated.get_deployment import GetDeployment, GetDeploymentDeployment
from styrmin_sdk.graphql._generated.get_deployment_by_name import (
    GetDeploymentByName,
    GetDeploymentByNameDeployment,
)
from styrmin_sdk.graphql._generated.get_deployment_override_applicability import (
    GetDeploymentOverrideApplicability,
    GetDeploymentOverrideApplicabilityDeployment,
)
from styrmin_sdk.graphql._generated.get_deployment_pod_statuses import (
    GetDeploymentPodStatuses,
    GetDeploymentPodStatusesDeploymentPodStatuses,
)
from styrmin_sdk.graphql._generated.get_deployment_timeline import (
    GetDeploymentTimeline,
    GetDeploymentTimelineDeploymentTimeline,
)
from styrmin_sdk.graphql._generated.input_types import (
    ComponentConfigInput,
    DeploymentConfigInput,
    EnvVarInput,
    ParameterValueInput,
    ServiceConfigInput,
    ServiceNameOverride,
    UpdateDeploymentInput,
)
from styrmin_sdk.graphql._generated.list_deployments import (
    ListDeployments,
    ListDeploymentsEnvironmentDeployments,
)
from styrmin_sdk.graphql._generated.list_environments import ListEnvironments
from styrmin_sdk.graphql._generated.run_job import RunJob, RunJobRunJob
from styrmin_sdk.graphql._generated.start_components import StartComponents, StartComponentsStartComponents
from styrmin_sdk.graphql._generated.stop_components import StopComponents, StopComponentsStopComponents
from styrmin_sdk.graphql._generated.update_deployment import UpdateDeployment, UpdateDeploymentUpdateDeployment
from styrmin_sdk.graphql._generated.update_deployment_version import (
    UpdateDeploymentVersion,
    UpdateDeploymentVersionUpdateDeploymentVersion,
)
from styrmin_sdk.models.context import Context
from styrmin_sdk.models.deployment_manifest import (
    ApplyEvent,
    ApplyOutcome,
    ApplyOverrides,
    DeploymentManifest,
    OverrideKind,
    ResolvedManifest,
    resolve_overrides,
)
from styrmin_sdk.models.image_reference import pinned_image_components
from styrmin_sdk.models.task import FailedStep, TaskWait
from styrmin_sdk.resources._base import BaseResource, JsonValue
from styrmin_sdk.resources.tasks import TaskResource

if TYPE_CHECKING:
    from styrmin_sdk.graphql._generated.get_task import GetTaskTask


def _expand_paths(paths: Sequence[Path | str]) -> list[Path]:
    """Expand caller-supplied paths to a flat list of YAML files.

    Files are passed through verbatim. Directories are expanded to their
    immediate ``.yaml`` / ``.yml`` children (non-recursive), sorted by
    filename for deterministic ordering. A missing path is reported
    eagerly, before any per-file work, so callers can fail fast rather
    than discovering the typo halfway through a batch.
    """
    expanded: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(str(path))
        if path.is_dir():
            children = sorted(
                child for child in path.iterdir() if child.is_file() and child.suffix in {".yaml", ".yml"}
            )
            if not children:
                raise ApplyError(f"no manifests found in {path}")
            expanded.extend(children)
        else:
            expanded.append(path)
    return expanded


def _resolve_all(
    files: Sequence[Path],
    overrides: ApplyOverrides,
    env: Mapping[str, str],
) -> tuple[list[ResolvedManifest], list[ApplyOutcome]]:
    """Parse / validate / resolve every file, splitting into resolved + failures.

    Extracted from :meth:`DeploymentResource.apply_files` to keep that method's
    branch count below the lint threshold; behaviour is identical.
    """
    resolved_entries: list[ResolvedManifest] = []
    pending_failures: list[ApplyOutcome] = []
    for source_path in files:
        try:
            manifests = _load_documents(source_path)
        except ManifestValidationError as exc:
            pending_failures.append(
                ApplyOutcome(
                    name=source_path.stem,
                    action="failed",
                    failure_reason=f"manifest {source_path}: {exc}",
                )
            )
            continue
        for manifest in manifests:
            try:
                resolved = resolve_overrides(manifest, overrides, env, source_path=source_path)
            except ApplyError as exc:
                pending_failures.append(
                    ApplyOutcome(
                        name=manifest.metadata.name or source_path.stem,
                        action="failed",
                        failure_reason=str(exc),
                    )
                )
                continue
            resolved_entries.append(resolved)
    return resolved_entries, pending_failures


def _load_documents(path: Path) -> list[DeploymentManifest]:
    """Parse one file with ``safe_load_all`` and validate each ``---`` doc.

    Empty / null documents are rejected.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestValidationError(f"failed to read {path}: {exc}") from exc

    try:
        documents: list[Any] = list(yaml.safe_load_all(raw_text))
    except yaml.YAMLError as exc:
        raise ManifestValidationError(f"YAML parse error: {exc}") from exc

    if not documents:
        raise ManifestValidationError("empty document")

    manifests: list[DeploymentManifest] = []
    for index, doc in enumerate(documents):
        if doc is None:
            raise ManifestValidationError(f"document {index}: empty document")
        try:
            manifests.append(DeploymentManifest.model_validate(doc))
        except ValidationError as exc:
            raise ManifestValidationError(f"document {index}: {exc}") from exc
    return manifests


def check_replica_counts(config: object, *, source: str) -> None:
    """Reject a ``components[].replicas`` that is not a whole number.

    Runs before Pydantic, which would turn ``true`` into 1 and ``"3"`` into 3.

    Raises:
        ManifestValidationError: A replica count is a bool, a string, a float or another type.
    """
    components = config.get("components") if isinstance(config, Mapping) else None
    if not isinstance(components, list):
        return
    for block in components:
        if not isinstance(block, Mapping):
            continue
        value = block.get("replicas")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ManifestValidationError(
                f"{source}: components[{block.get('name')!r}].replicas must be a whole number, got {value!r}"
            )


def _stored_component_inputs(config: object) -> dict[str, ComponentConfigInput]:
    """The stored ``config.components`` blocks as inputs that resend each override unchanged."""
    stored = config.get("components") if isinstance(config, dict) else None
    blocks: dict[str, ComponentConfigInput] = {}
    for name, block in (stored or {}).items():
        if not isinstance(block, dict):
            continue
        env_vars = block.get("env_vars")
        blocks[name] = ComponentConfigInput(
            name=name,
            env_vars=([EnvVarInput(name=key, value=value) for key, value in env_vars.items()] if env_vars else None),
            command=block.get("command"),
            args=block.get("args"),
            image=block.get("image"),
            replicas=block.get("replicas"),
        )
    return blocks


def _stored_service_inputs(config: object) -> list[ServiceConfigInput]:
    """The stored ``config.services`` blocks as inputs that resend each ingress override unchanged."""
    stored = config.get("services") if isinstance(config, dict) else None
    return [
        ServiceConfigInput(
            name=name,
            ingress_class=block.get("ingress_class"),
            fqdn_suffix=block.get("fqdn_suffix"),
        )
        for name, block in (stored or {}).items()
        if isinstance(block, dict)
    ]


def _build_update_input(manifest: ResolvedManifest) -> UpdateDeploymentInput:
    """Convert a resolved manifest into a typed ``UpdateDeploymentInput``.

    The manifest's ``spec.config`` dict carries top-level deployment-config
    fields keyed by their GraphQL camelCase names (``envVars``,
    ``ipWhitelist``, ``dedicatedIngress``, ``scheduling``, …). We validate
    that dict directly against ``UpdateDeploymentInput`` so Pydantic enforces
    every leaf shape — invalid env-var rows, malformed scheduling blocks,
    etc. surface as ``ManifestValidationError`` before the mutation is
    dispatched.

    ``spec.parameters`` is flattened from the YAML's ``{name: value}`` map
    into the GraphQL ``[ParameterValueInput!]`` list shape; the typed input
    documents the merge semantics. The resolver-side error
    ``DUPLICATE_PARAMETER_NAME`` still fires for duplicates that slip through
    (the YAML mapping enforces uniqueness, so this is a no-op in practice).
    """
    config_payload: dict[str, Any] = dict(manifest.config)
    check_replica_counts(config_payload, source=f"manifest {manifest.source_path}: spec.config")
    # Refuse a malformed override, or both spellings, as the create path does
    _build_service_name_overrides(manifest)
    if manifest.parameters:
        config_payload.setdefault(
            "parameters",
            [{"name": name, "value": value} for name, value in manifest.parameters.items()],
        )
    try:
        return UpdateDeploymentInput.model_validate(config_payload)
    except ValidationError as exc:
        raise ManifestValidationError(
            f"manifest {manifest.source_path}: spec.config does not match UpdateDeploymentInput: {exc}",
        ) from exc


_VERSION_INPUT_UNKNOWN = "Unknown argument 'input' on field 'Mutation.updateDeploymentVersion'"


def _raise_if_server_lacks_version_input(result: dict[str, Any]) -> None:
    """Raise :class:`IncompatibleServerError` when the server predates ``updateDeploymentVersion(input:)``."""
    for error in result.get("errors") or []:
        if str(error.get("message", "")).startswith(_VERSION_INPUT_UNKNOWN):
            raise IncompatibleServerError(
                "this styrminctl or SDK sends the config with the version change, which the Styrmin "
                "server does not accept: updateDeploymentVersion has no 'input' argument before #388. "
                "Upgrade the Styrmin server before or together with styrminctl and the SDK.",
                "",
            )


def _error_code(exc: BaseException) -> str | None:
    """The server's ``extensions.code`` carried by ``exc``, if any."""
    if isinstance(exc, StyrminAPIError) and exc.typename:
        return exc.typename
    return None


#: ``Task.status`` of a failed task. :meth:`DeploymentResource.update_version` returns a task
#: with this status when the server refuses an upgrade before it writes anything (spec 029).
FAILED_TASK_STATUS = "failed"


def failed_task_reason(task_id: UUID, message: str | None) -> str:
    """Describe a failed task by its id and, when it has one, its message."""
    return f"task {task_id} failed: {message}" if message else f"task {task_id} failed"


def _failed_step_reason(step: FailedStep) -> str:
    """Describe a failed step by its name and, when it has one, its newest error."""
    return f'step "{step.name}" failed: {step.error}' if step.error else f'step "{step.name}" failed'


#: ``Task.type`` of the task that :meth:`DeploymentResource.delete` returns.
DELETE_DEPLOYMENT_TASK_TYPE = "delete_deployment"

#: ``Deployment.status`` values that end :meth:`DeploymentResource.wait_for_task` once the task result is final.
_SETTLED_STATUSES = TERMINAL_SUCCESS_STATUSES | TERMINAL_FAILURE_STATUSES | {DELETED_STATUS}


async def _sleep_before_next_poll(deadline: float) -> bool:
    """Sleep one poll interval, never past ``deadline``. Returns ``False``, without sleeping, once it has passed."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    await asyncio.sleep(min(WAIT_POLL_INTERVAL_SECONDS, remaining))
    return True


def _effective_image_overrides(update_input: UpdateDeploymentInput, stored_config: object) -> dict[str, str | None]:
    """Image override per component once ``update_input`` lands (research D-011).

    Manifest ``components`` replace the stored blocks; when the manifest omits them, the
    stored ``config.components`` (a dict keyed by component name) stay in effect.
    """
    if update_input.components is not None:
        return {block.name: block.image for block in update_input.components}
    stored = stored_config.get("components") if isinstance(stored_config, dict) else None
    if not isinstance(stored, dict):
        return {}
    return {
        name: block.get("image") if isinstance(block, dict) else None
        for name, block in stored.items()
        if isinstance(name, str)
    }


def _override_kinds(block: ComponentConfigInput) -> list[OverrideKind]:
    """The override kinds a component block sets, in a fixed order."""
    kinds: list[OverrideKind] = []
    if block.env_vars:
        kinds.append("env_vars")
    if block.image is not None:
        kinds.append("image")
    if block.command is not None:
        kinds.append("command")
    if block.args is not None:
        kinds.append("args")
    if block.replicas is not None:
        kinds.append("replicas")
    return kinds


_SERVICE_NAME_OVERRIDE_KEYS = ("service_name_overrides", "serviceNameOverrides")


def _build_service_name_overrides(manifest: ResolvedManifest) -> list[dict[str, str]] | None:
    """Read ``spec.config.service_name_overrides`` as the rows the ``deploy`` mutation takes.

    The ``deploy`` mutation takes the overrides as its own argument, not inside the typed
    deployment config, so the create path reads them from the manifest config here. The update
    path needs no such step: its input model already has the field. Both key spellings are
    accepted, as for the other config fields, but not both together. Returns ``None`` when the
    manifest sets none, or sets the key to null.

    Raises:
        ManifestValidationError: Both spellings are set, or the value is not a list of
            ``{driver_service_name, override_name}`` rows.
    """
    present = [candidate for candidate in _SERVICE_NAME_OVERRIDE_KEYS if candidate in manifest.config]
    if len(present) > 1:
        raise ManifestValidationError(
            f"manifest {manifest.source_path}: spec.config sets both {present[0]} and {present[1]}: keep one"
        )
    if not present or manifest.config[present[0]] is None:
        # A key with no value, such as a list whose entries are all commented out, sets nothing.
        return None
    key = present[0]
    rows = manifest.config[key]
    if not isinstance(rows, list):
        raise ManifestValidationError(
            f"manifest {manifest.source_path}: spec.config.{key} must be a list of "
            f"{{driver_service_name, override_name}} rows, got {type(rows).__name__}"
        )
    try:
        return [ServiceNameOverride.model_validate(row).model_dump(by_alias=True) for row in rows]
    except ValidationError as exc:
        raise ManifestValidationError(
            f"manifest {manifest.source_path}: spec.config.{key} does not match ServiceNameOverride: {exc}",
        ) from exc


def _build_config_input(manifest: ResolvedManifest) -> DeploymentConfigInput | None:
    """Build the typed ``DeploymentConfigInput`` for the create path.

    The ``deploy`` (create) mutation now takes the same typed config payload
    as ``updateDeployment`` (both share ``DeploymentConfigInput``), so the
    manifest's ``spec.config`` dict — keyed by GraphQL camelCase names with
    ``env_vars`` / ``components`` as ``[{name, value}]`` lists — validates
    directly against the generated model. Returns ``None`` for an empty
    config so the mutation omits it entirely.

    Invalid leaf shapes surface as :class:`ManifestValidationError` before
    the mutation is dispatched, mirroring :func:`_build_update_input`.
    """
    if not manifest.config:
        return None
    check_replica_counts(manifest.config, source=f"manifest {manifest.source_path}: spec.config")
    try:
        config = {key: value for key, value in manifest.config.items() if key not in _SERVICE_NAME_OVERRIDE_KEYS}
        return DeploymentConfigInput.model_validate(config) if config else None
    except ValidationError as exc:
        raise ManifestValidationError(
            f"manifest {manifest.source_path}: spec.config does not match DeploymentConfigInput: {exc}",
        ) from exc


def _build_parameters_input(manifest: ResolvedManifest) -> list[ParameterValueInput] | None:
    """Flatten the manifest's ``spec.parameters`` map into the list shape.

    The ``deploy`` mutation now takes ``[ParameterValueInput!]`` (matching
    ``updateDeployment``) instead of a freeform ``JSON`` map, so the YAML's
    ``{name: value}`` mapping is converted to ``[{name, value}]`` rows.
    Returns ``None`` when the manifest declares no parameters.
    """
    if not manifest.parameters:
        return None
    return [ParameterValueInput(name=name, value=value) for name, value in manifest.parameters.items()]


def _check_max_wait(max_wait: float | None) -> None:
    """Reject a ``max_wait`` that is not positive, before anything is submitted."""
    if max_wait is not None and max_wait <= 0:
        raise ValueError(f"max_wait must be positive, got {max_wait}")


class DeploymentResource(BaseResource):
    async def create(
        self,
        driver: str,
        version: str,
        environment_id: str | UUID | None = None,
        *,
        environment_name: str | None = None,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
        name: str | None = None,
        config: DeploymentConfigInput | None = None,
        parameters: list[ParameterValueInput] | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
        driver_version_id: str | UUID | None = None,
    ) -> DeployDeploy:
        """Create a deployment via the ``deploy`` mutation.

        ``config`` / ``parameters`` use the same typed shapes as
        :meth:`update` (``DeploymentConfigInput`` and the
        ``[ParameterValueInput!]`` list) so a single manifest config payload
        drives both the create and update paths of :meth:`apply`.
        """
        variables: dict[str, Any] = {
            "driver": driver,
            "version": version,
        }
        if environment_id is not None:
            variables["environmentId"] = str(environment_id)
        if environment_name is not None:
            variables["environmentName"] = environment_name
        if cluster_id is not None:
            variables["clusterId"] = str(cluster_id)
        if cluster_name is not None:
            variables["clusterName"] = cluster_name
        if name is not None:
            variables["name"] = name
        if config is not None:
            variables["config"] = config.model_dump(by_alias=True, exclude_none=True)
        if parameters is not None:
            variables["parameters"] = [p.model_dump(by_alias=True, exclude_none=True) for p in parameters]
        if service_name_overrides is not None:
            variables["serviceNameOverrides"] = service_name_overrides
        if driver_version_id is not None:
            variables["driverVersionId"] = str(driver_version_id)

        result = await self._transport.execute(load_query("deploy"), variables)
        self._check_graphql_errors(result)
        return self._parse(Deploy, result["data"], "deploy", DeployDeploy)

    async def get(self, deployment_id: str | UUID) -> GetDeploymentDeployment:
        result = await self._transport.execute(load_query("get_deployment"), {"deploymentId": str(deployment_id)})
        self._check_graphql_errors(result)
        return self._parse(GetDeployment, result["data"], "deployment", GetDeploymentDeployment)

    async def list(
        self,
        environment_id: str | UUID,
        *,
        include_deleted: bool = False,
        include_internal: bool = False,
    ) -> list[ListDeploymentsEnvironmentDeployments]:
        """List the deployments belonging to an environment.

        Each entry carries the deployment's active application instance
        (``application_instance``), or ``None`` when the deployment has no
        active instance yet. Internal deployments, such as the ingress
        controller of a dedicated ingress, are left out unless
        ``include_internal`` is true.
        """
        result = await self._transport.execute(
            load_query("list_deployments"),
            {
                "environmentId": str(environment_id),
                "includeDeleted": include_deleted,
                "includeInternal": include_internal,
            },
        )
        self._check_graphql_errors(result)
        validated = ListDeployments.model_validate(result["data"])
        return validated.environment.deployments if validated.environment else []

    async def get_by_name(self, name: str, *, environment_id: str | UUID) -> GetDeploymentByNameDeployment | None:
        """Look up a deployment by its natural identity ``(name, environment_id)``.

        Returns ``None`` cleanly when no deployment matches, including the
        internal-hidden case (the backend resolver collapses internal and
        soft-deleted rows to a null payload). Mirrors the selection set of
        :meth:`get`, so callers can use the two interchangeably once they have
        a deployment in hand.
        """
        result = await self._transport.execute(
            load_query("get_deployment_by_name"),
            {"name": name, "environmentId": str(environment_id)},
        )
        self._check_graphql_errors(result)
        validated = GetDeploymentByName.model_validate(result["data"])
        return validated.deployment

    async def update(
        self,
        deployment_id: str | UUID,
        *,
        input: UpdateDeploymentInput,
    ) -> UpdateDeploymentUpdateDeployment | None:
        """Update a deployment with a typed ``UpdateDeploymentInput``.

        ``input`` is the regenerated Pydantic model that mirrors the GraphQL
        ``UpdateDeploymentInput`` input type. The config fields of ``input``
        replace the whole stored deployment config: when at least one config
        field is set, every stored config key that ``input`` leaves out
        (``None``) is cleared, for example the ``components`` blocks or the
        ``services`` ingress overrides. When no config field is set, the stored
        config is kept. ``parameters`` and ``service_name_overrides`` are not
        part of the config: ``parameters`` uses merge semantics — entries in the
        list merge on top of the persisted parameters dict — and an omitted
        ``service_name_overrides`` leaves the service name overrides as they are.

        Returns ``None`` when the backend detects a no-op (the submitted state
        resolves to the current instance): the resolver returns ``null`` and no
        task is dispatched. The caller treats a ``None`` task as "nothing
        changed".
        """
        variables: dict[str, Any] = {
            "deploymentId": str(deployment_id),
            "input": input.model_dump(by_alias=True, exclude_none=True),
        }
        result = await self._transport.execute(
            load_query("update_deployment"),
            variables,
        )
        self._check_graphql_errors(result)
        if result["data"].get("updateDeployment") is None:
            return None
        return self._parse(UpdateDeployment, result["data"], "update_deployment", UpdateDeploymentUpdateDeployment)

    async def scale(
        self, deployment_id: str | UUID, component: str, replicas: int | None
    ) -> UpdateDeploymentUpdateDeployment | None:
        """Set the replica override of one component, or clear it with ``replicas=None``.

        ``components`` replaces every stored block, so the other stored blocks and the
        component's other overrides (env vars, image, ``command``, ``args``) are resent
        unchanged. The stored ``services`` ingress overrides are resent unchanged too,
        because the update replaces the whole stored config. A write between the read and
        the update is overwritten. Returns ``None`` when nothing changes, like :meth:`update`.
        """
        deployment = await self.get(deployment_id)
        blocks = _stored_component_inputs(deployment.config)
        target = blocks.pop(component, ComponentConfigInput(name=component))
        target = target.model_copy(update={"replicas": replicas})
        if target.model_dump(exclude={"name"}, exclude_none=True):
            blocks[component] = target
        services = _stored_service_inputs(deployment.config)
        return await self.update(
            deployment_id,
            input=UpdateDeploymentInput(components=list(blocks.values()), services=services or None),
        )

    async def delete(self, deployment_id: str | UUID) -> DeleteDeploymentDeleteDeployment:
        """Request deletion of a deployment.

        Patches the cluster-side StyrminDeployment CR to flip
        ``spec.deletionRequested`` to ``true``. Returns immediately
        with a born-complete ``DELETE_DEPLOYMENT`` task — poll
        ``Deployment.status`` to observe the lifecycle's
        ``DELETING -> DELETED`` progression.

        Idempotent: a second call against an already-DELETING
        deployment returns the existing in-flight task without
        duplicating side effects.

        Raises:
            ResourceNotFoundError: id is unknown OR the deployment is
                already DELETED (intentional conflation with unknown
                id; check ``error_code == "NOT_FOUND"`` to distinguish
                from a transport-level 404).
            DeploymentRestoringError: a restore is in progress on this
                deployment; deletion is refused for data-integrity
                reasons.
        """
        result = await self._transport.execute(
            load_query("delete_deployment"),
            {"deploymentId": str(deployment_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            DeleteDeployment,
            result["data"],
            "delete_deployment",
            DeleteDeploymentDeleteDeployment,
        )

    async def update_version(
        self,
        deployment_id: str | UUID,
        version: str,
        *,
        parameters: JsonValue | None = None,
        driver_version_id: str | UUID | None = None,
        input: UpdateDeploymentInput | None = None,
    ) -> UpdateDeploymentVersionUpdateDeploymentVersion | None:
        """Update a deployment's application version.

        Without ``driver_version_id`` the deployment is bound to the latest
        loaded driver version supporting ``version``; with it, the binding is
        pinned to that specific driver version.

        ``input`` takes the same fields as :meth:`update`. The backend validates
        them against the target driver version and writes them with the version,
        so one task reconciles both. ``input`` needs a Styrmin server that accepts
        it (#388); an older server raises :class:`IncompatibleServerError`.
        Without ``input`` the call works against older servers too.

        Returns ``None`` when the backend detects a no-op (the requested
        state equals the current one): the resolver returns ``null`` and no
        task is dispatched.

        The returned task can already have the status ``failed``
        (:data:`FAILED_TASK_STATUS`): the server refused the change before it
        wrote anything, for example an upgrade whose driver action has no
        registered flow, and the task's ``message`` says why. The deployment
        keeps its version. This method returns that task and does not raise;
        callers check ``status``. :meth:`apply` reports it as ``action="failed"``.
        """
        variables: dict[str, Any] = {
            "deploymentId": str(deployment_id),
            "version": version,
        }
        if parameters is not None:
            variables["parameters"] = parameters
        if driver_version_id is not None:
            variables["driverVersionId"] = str(driver_version_id)
        query = load_query("update_version")
        if input is not None:
            variables["input"] = input.model_dump(by_alias=True, exclude_none=True)
            query = load_query("update_deployment_version_with_input")
        result = await self._transport.execute(query, variables)
        if input is not None:
            _raise_if_server_lacks_version_input(result)
        self._check_graphql_errors(result)
        if result["data"].get("updateDeploymentVersion") is None:
            return None
        return self._parse(
            UpdateDeploymentVersion,
            result["data"],
            "update_deployment_version",
            UpdateDeploymentVersionUpdateDeploymentVersion,
        )

    async def start_components(
        self, deployment_id: str | UUID, components: list[str]
    ) -> StartComponentsStartComponents:
        result = await self._transport.execute(
            load_query("start_components"),
            {"deploymentId": str(deployment_id), "components": components},
        )
        self._check_graphql_errors(result)
        return self._parse(StartComponents, result["data"], "start_components", StartComponentsStartComponents)

    async def stop_components(self, deployment_id: str | UUID, components: list[str]) -> StopComponentsStopComponents:
        result = await self._transport.execute(
            load_query("stop_components"),
            {"deploymentId": str(deployment_id), "components": components},
        )
        self._check_graphql_errors(result)
        return self._parse(StopComponents, result["data"], "stop_components", StopComponentsStopComponents)

    async def run_job(
        self,
        deployment_id: str | UUID,
        image: str,
        commands: list[str],
        env: JsonValue,
    ) -> RunJobRunJob:
        result = await self._transport.execute(
            load_query("run_job"),
            {
                "deploymentId": str(deployment_id),
                "commands": commands,
                "image": image,
                "env": env,
            },
        )
        self._check_graphql_errors(result)
        return self._parse(RunJob, result["data"], "run_job", RunJobRunJob)

    async def wait_for_task(self, task_id: str | UUID, *, max_wait: float | None = None) -> TaskWait:
        """Wait until the change that a task of a deployment makes has finished.

        ``task_id`` is the id of the task that :meth:`create`, :meth:`update`, :meth:`scale`,
        :meth:`update_version`, :meth:`delete`, :meth:`start_components`,
        :meth:`stop_components` or :meth:`run_job` returns.

        1. Waits until the task result is no longer ``RUNNING``. The task result covers the
           task, the tasks that its hook steps started, and the operator's rollout steps.
        2. When the task result is ``SUCCEEDED``, waits until ``Deployment.status`` is
           ``running``, ``failed`` or ``deleted``. The change succeeded when it is ``deleted``
           after a ``delete_deployment`` task, and ``running`` after any other task.

        ``Deployment.status`` alone does not tell when a change has finished:
        :meth:`start_components` and :meth:`stop_components` leave it ``running`` until their
        flow starts, and a task's ``SUCCESS`` status does not set it to ``running``.

        Polls every ``WAIT_POLL_INTERVAL_SECONDS`` for at most ``max_wait`` seconds
        (``WAIT_TIMEOUT_SECONDS`` when ``None``). A failed change or a timeout does not raise:
        the returned :class:`~styrmin_sdk.models.TaskWait` gives the reason in
        ``failure_reason``, and ``timed_out`` is true after a timeout. A failed task result names
        the failed step of the task, or of a task it started.

        Raises:
            ValueError: ``max_wait`` is not positive.
            ResourceNotFoundError: no task has this id.
        """
        _check_max_wait(max_wait)
        deadline = time.monotonic() + (WAIT_TIMEOUT_SECONDS if max_wait is None else max_wait)
        tasks = TaskResource(self._transport)
        task = await tasks.get(task_id)
        while task.result is TaskResult.RUNNING:
            if not await _sleep_before_next_poll(deadline):
                return await self._task_wait(task, failure_reason="wait timeout", timed_out=True)
            task = await tasks.get(task_id)

        if task.result is TaskResult.FAILED:
            return await self._task_wait(task, failure_reason=await self._task_failure_reason(task))
        if task.result is TaskResult.SUPERSEDED:
            return await self._task_wait(
                task, failure_reason=f"task {task.id} was superseded by a later task of the deployment"
            )
        if task.deployment_id is None:
            return TaskWait(task_id=task.id, deployment_id=None, task_result=task.result)

        expected = DELETED_STATUS if task.type_ == DELETE_DEPLOYMENT_TASK_TYPE else "running"
        status = (await self.get(task.deployment_id)).status
        while status.lower() not in _SETTLED_STATUSES:
            if not await _sleep_before_next_poll(deadline):
                return TaskWait(
                    task_id=task.id,
                    deployment_id=task.deployment_id,
                    task_result=task.result,
                    deployment_status=status,
                    failure_reason="wait timeout",
                    timed_out=True,
                )
            status = (await self.get(task.deployment_id)).status
        return TaskWait(
            task_id=task.id,
            deployment_id=task.deployment_id,
            task_result=task.result,
            deployment_status=status,
            failure_reason=None
            if status.lower() == expected
            else f"deployment status is {status}, expected {expected}",
        )

    async def _task_wait(self, task: GetTaskTask, *, failure_reason: str, timed_out: bool = False) -> TaskWait:
        """A :class:`TaskWait` for a wait that ends on the task, with the deployment status read now."""
        status = None if task.deployment_id is None else (await self.get(task.deployment_id)).status
        return TaskWait(
            task_id=task.id,
            deployment_id=task.deployment_id,
            task_result=task.result,
            deployment_status=status,
            failure_reason=failure_reason,
            timed_out=timed_out,
        )

    async def _task_failure_reason(self, task: GetTaskTask) -> str:
        """Name the failed step of ``task`` or of a task it started, else the task's own message."""
        try:
            step = await TaskResource(self._transport).failed_step(task.id)
        except StyrminError:
            step = None
        return failed_task_reason(task.id, task.message) if step is None else _failed_step_reason(step)

    async def get_timeline(self, deployment_id: str | UUID) -> list[GetDeploymentTimelineDeploymentTimeline]:
        result = await self._transport.execute(
            load_query("get_deployment_timeline"),
            {"deploymentId": str(deployment_id)},
        )
        self._check_graphql_errors(result)
        validated = GetDeploymentTimeline.model_validate(result["data"])
        return validated.deployment_timeline

    async def get_context(self, deployment_id: str | UUID) -> Context:
        data = await self._transport.get(f"/deployments/{deployment_id}/context")
        return Context.model_validate({"context": data})

    async def get_pod_statuses(self, deployment_id: str | UUID) -> list[GetDeploymentPodStatusesDeploymentPodStatuses]:
        result = await self._transport.execute(
            load_query("get_deployment_pod_statuses"),
            {"deploymentId": str(deployment_id)},
        )
        self._check_graphql_errors(result)
        validated = GetDeploymentPodStatuses.model_validate(result["data"])
        return validated.deployment.pod_statuses if validated.deployment else []

    async def _resolve_environment_id(self, environment_name: str, cluster_name: str | None) -> UUID:
        """Resolve ``(environment_name, cluster_name)`` to a single ``environment_id``.

        Lists all environments and filters client-side so that we can detect
        cross-cluster ambiguity (same env name on multiple clusters) without
        relying on the backend, whose ``environment(name)`` resolver requires a
        cluster argument and therefore can't surface "exists in N clusters" as
        a single response. When ``cluster_name`` is provided, only that cluster
        is considered.

        Raises:
            EnvironmentAmbiguityError: ``cluster_name`` is None and the
                environment name matches in more than one cluster.
            EnvironmentNotFoundError: no environment matches the resolved
                ``(environment_name, cluster_name)`` pair. Distinct from
                ambiguity so callers can branch on the difference between
                "specify a cluster" and "the env doesn't exist".
        """
        result = await self._transport.execute(load_query("list_environments"))
        self._check_graphql_errors(result)
        envs = ListEnvironments.model_validate(result["data"]).environments
        candidates = [env for env in envs if env.name == environment_name]
        if cluster_name is not None:
            candidates = [env for env in candidates if env.cluster.name == cluster_name]
        if len(candidates) > 1:
            cluster_names = sorted(env.cluster.name for env in candidates)
            raise EnvironmentAmbiguityError(
                f"environment {environment_name!r} exists in multiple clusters: "
                f"{cluster_names}; specify --cluster or spec.cluster"
            )
        if not candidates:
            raise EnvironmentNotFoundError(
                f"environment {environment_name!r}"
                + (f" in cluster {cluster_name!r}" if cluster_name else "")
                + " not found"
            )
        return candidates[0].id

    async def apply(
        self, manifest: ResolvedManifest, *, wait: bool = False, max_wait: float | None = None
    ) -> ApplyOutcome:
        """Create-or-update a deployment from a resolved manifest.

        * resolve ``(environment, cluster)`` to a unique ``environment_id``
          (raising :class:`EnvironmentAmbiguityError` on multi-cluster
          collisions);
        * look up an existing non-internal deployment by
          ``(name, environment_id)``;
        * if absent, dispatch ``deploy()`` and return ``action="created"``;
        * if present, validate the driver matches (raise
          :class:`DriverMismatchError` otherwise), then dispatch one
          ``update_deployment_version`` carrying the config, parameters and
          version, so the config is validated against the version the
          manifest declares and the upgrade reconciles against the new config.

        The lookup-then-create branch is non-atomic: a concurrent ``apply``
        run could race past the "not found" branch and both call
        ``deploy()``. The DB unique constraint will reject the loser; we
        catch :class:`ResourceAlreadyExistsError` once, re-run the lookup,
        and pivot to the update path.

        With ``wait=True`` this method blocks after a successful submission
        until the deployment's ``applicationInstance.status`` reaches a
        terminal value, polling at the SDK-wide cadence, for at most
        ``max_wait`` seconds (``WAIT_TIMEOUT_SECONDS`` when ``None``).
        A ``max_wait`` that is not positive raises :class:`ValueError`
        before anything is submitted. On a terminal failure or wait timeout
        the returned outcome's ``action`` is flipped to ``"failed"`` and
        ``failure_reason`` is populated. An update that returns a failed task
        is a ``"failed"`` outcome at once, and ``apply`` does not wait. The
        submission itself is NOT undone — re-running ``apply`` against the
        same manifest is the recovery path.
        """
        _check_max_wait(max_wait)
        environment_id = await self._resolve_environment_id(manifest.environment, manifest.cluster)
        existing = await self.get_by_name(manifest.name, environment_id=environment_id)

        outcome: ApplyOutcome
        if existing is None:
            try:
                task = await self.create(
                    driver=manifest.driver,
                    version=manifest.version,
                    environment_id=environment_id,
                    name=manifest.name,
                    config=_build_config_input(manifest),
                    parameters=_build_parameters_input(manifest),
                    service_name_overrides=_build_service_name_overrides(manifest),
                )
            except ResourceAlreadyExistsError:
                # Concurrent apply: someone else won the create race. Re-look
                # up exactly once and fall through to the update path; if the
                # row still doesn't show, propagate the original error rather
                # than looping.
                existing = await self.get_by_name(manifest.name, environment_id=environment_id)
                if existing is None:
                    raise
                outcome = await self._apply_update(manifest, existing)
            else:
                outcome = ApplyOutcome(
                    name=manifest.name,
                    action="created",
                    deployment_id=task.deployment_id,
                    task_id=task.id,
                )
        else:
            outcome = await self._apply_update(manifest, existing)

        if wait and outcome.action in {"created", "updated"} and outcome.deployment_id is not None:
            outcome = await self._wait_for_terminal(outcome, max_wait)
        return outcome

    async def _apply_update(self, manifest: ResolvedManifest, existing: GetDeploymentByNameDeployment) -> ApplyOutcome:
        """Dispatch the update branch of :meth:`apply`.

        Config, parameters and version go in one ``update_deployment_version``
        call, so the backend validates the config against the driver version the
        manifest moves to and one task reconciles everything (#388). The call is
        dispatched even when the version is unchanged: the backend re-resolves the
        driver version and owns no-op detection, returning ``None`` when nothing
        changes (``action="unchanged"``). A rejected call returns ``action="failed"``
        with the server's message and ``error_code``; nothing was written. A call
        that returns a task whose status is already ``failed`` also returns
        ``action="failed"``, with the task's id and message as ``failure_reason``:
        the server refused the change before writing it, for example an upgrade
        whose driver action has no registered flow (spec 029, research R-009), so
        there is nothing to wait for. An
        ``updated`` outcome that changes the application version also carries
        ``target_version`` and the token-free ``pinned_image_components`` (FR-008),
        and ``inapplicable_overrides`` lists, per component, the manifest's overrides that
        the bound driver version cannot apply; ``apply`` never prompts.
        """
        existing_driver_name = existing.application_driver_version.application_driver.name
        if existing_driver_name != manifest.driver:
            raise DriverMismatchError(
                f"driver mismatch (manifest={manifest.driver!r}, existing={existing_driver_name!r}); "
                "driver changes require delete-and-recreate"
            )

        update_input = _build_update_input(manifest)
        try:
            task = await self.update_version(existing.id, manifest.version, input=update_input)
        except StyrminError as exc:
            return ApplyOutcome(
                name=manifest.name,
                action="failed",
                deployment_id=existing.id,
                failure_reason=str(exc),
                error_code=_error_code(exc),
            )
        if task is None:
            return ApplyOutcome(
                name=manifest.name,
                action="unchanged",
                deployment_id=existing.id,
            )
        if task.status == FAILED_TASK_STATUS:
            return ApplyOutcome(
                name=manifest.name,
                action="failed",
                deployment_id=existing.id,
                task_id=task.id,
                failure_reason=failed_task_reason(task.id, task.message),
            )

        version_changed = manifest.version != existing.application_version
        inapplicable, check_error = await self._inapplicable_overrides(existing.id, update_input)
        return ApplyOutcome(
            name=manifest.name,
            action="updated",
            deployment_id=existing.id,
            task_id=task.id,
            target_version=manifest.version if version_changed else None,
            pinned_image_components=(
                pinned_image_components(_effective_image_overrides(update_input, existing.config))
                if version_changed
                else []
            ),
            inapplicable_components=list(inapplicable),
            inapplicable_overrides=inapplicable,
            applicability_check_error=check_error,
        )

    async def _inapplicable_overrides(
        self, deployment_id: UUID, update_input: UpdateDeploymentInput
    ) -> tuple[dict[str, list[OverrideKind]], str | None]:
        """Per component, the env vars, image, ``command``, ``args`` or replica count in ``update_input`` that are stored but not applied.

        Unchanged values on a component that the bound driver version gives no component
        container, or no longer declares, pass validation, so they are read back once the update
        is written. A failed read never fails the apply: it returns no components and the error.
        """
        submitted = {block.name: kinds for block in update_input.components or [] if (kinds := _override_kinds(block))}
        if not submitted:
            return {}, None
        try:
            result = await self._transport.execute(
                load_query("get_deployment_override_applicability"), {"deploymentId": str(deployment_id)}
            )
            self._check_graphql_errors(result)
            deployment = self._parse(
                GetDeploymentOverrideApplicability,
                result["data"],
                "deployment",
                GetDeploymentOverrideApplicabilityDeployment,
            )
        except StyrminError as exc:
            return {}, str(exc)
        container_not_applied = {b.component for b in deployment.component_container_overrides if not b.is_applicable}
        not_applied: dict[OverrideKind, set[str]] = {
            "env_vars": {b.component for b in deployment.component_env_vars if not b.is_applicable},
            "image": {b.component for b in deployment.component_image_overrides if not b.is_applicable},
            "command": container_not_applied,
            "args": container_not_applied,
            "replicas": {b.component for b in deployment.component_replicas if not b.is_applicable},
        }
        result: dict[str, list[OverrideKind]] = {}
        for name in sorted(submitted):
            if kinds := [kind for kind in submitted[name] if name in not_applied[kind]]:
                result[name] = kinds
        return result, None

    async def _wait_for_terminal(self, outcome: ApplyOutcome, max_wait: float | None = None) -> ApplyOutcome:
        """Poll the deployment until its ``Deployment.status`` reaches a terminal state.

        Reuses the same convention (``WAIT_TIMEOUT_SECONDS`` /
        ``WAIT_POLL_INTERVAL_SECONDS``) shared with any other SDK
        ``--wait``-style helper, so callers see a uniform ceiling regardless of
        which method they invoked. ``max_wait`` replaces the ceiling when set.

        The poll target is the user-facing ``Deployment.status`` enum
        (``PENDING / DEPLOYING / RUNNING / FAILED / …``), not the task or
        the application-instance status. Rationale (see ``CONTEXT.md`` →
        "Deployment state"):

        * ``Deployment.status`` is the canonical user-visible state — the
          same field the API E2E driver's ``wait_for_deployment_running``
          polls. The user contract for ``--wait`` is "block until the
          deployment is RUNNING (or has failed)" — this is the field
          that means that.
        * Polling ``Task.status`` returns too early: per
          ``services/tasks.py:78-80``, the task's terminal ``SUCCESS``
          transition deliberately does NOT touch ``Deployment.status`` —
          that flip is owned by the CRD status reporter, which fires when
          the cluster-side CR reaches Ready. A task ``SUCCESS`` means
          "the apply flow finished", not "the deployment is ready".
        * Polling ``ApplicationInstance.status`` is racy: it can be
          touched by other reconciliation paths (CRD reporter, drift
          correction) so an isolated ``"running"`` reading isn't safe
          to interpret as "our submission has settled".

        On terminal success the original ``outcome`` is returned untouched.
        On terminal failure or wait timeout the action is flipped to
        ``"failed"`` and ``failure_reason`` is populated. A terminal failure
        names the failed step of the outcome's task (or of a task it started),
        read in the same poll, because a later report can end that step.
        """
        deployment_id = outcome.deployment_id
        if deployment_id is None:
            return outcome
        deadline = time.monotonic() + (WAIT_TIMEOUT_SECONDS if max_wait is None else max_wait)
        while time.monotonic() < deadline:
            deployment = await self.get(deployment_id)
            status = deployment.status
            if is_terminal_success(status):
                return outcome
            if is_terminal_failure(status):
                return outcome.model_copy(
                    update={"action": "failed", "failure_reason": await self._failure_reason(outcome, status)}
                )
            # Never sleep past the deadline, so a short ``max_wait`` ends on time.
            await asyncio.sleep(max(0.0, min(WAIT_POLL_INTERVAL_SECONDS, deadline - time.monotonic())))
        return outcome.model_copy(update={"action": "failed", "failure_reason": "wait timeout"})

    async def _failure_reason(self, outcome: ApplyOutcome, status: str) -> str:
        """Name the failed step of the outcome's task, or fall back to the deployment status."""
        fallback = f"deployment reconciliation failed (status: {status})"
        if outcome.task_id is None:
            return fallback
        try:
            step = await TaskResource(self._transport).failed_step(outcome.task_id)
        except StyrminError:
            # A server without task steps, or a read error, keeps the status reason.
            return fallback
        if step is None:
            return fallback
        return _failed_step_reason(step)

    async def apply_files(
        self,
        paths: Sequence[Path | str],
        *,
        overrides: ApplyOverrides | None = None,
        env: Mapping[str, str] | None = None,
        wait: bool = False,
        max_wait: float | None = None,
        on_event: Callable[[ApplyEvent], None] | None = None,
    ) -> list[ApplyOutcome]:
        """Load YAML manifest files (or directories) and apply each one.

        * Path expansion is eager and fail-fast.
        * Files are parsed with ``yaml.safe_load_all`` for multi-doc support.
        * Each manifest is resolved against ``overrides`` and ``env`` via
          :func:`styrmin_sdk.models.deployment_manifest.resolve_overrides`.
        * ``--name`` + multi-manifest is a whole-batch error
          (:class:`BatchNameConflictError`) BEFORE per-manifest dispatch.
        * Per-manifest exceptions are caught and turned into
          ``ApplyOutcome(action="failed", failure_reason=...)``.
        * ``max_wait`` bounds the wait of each manifest, as in :meth:`apply`.
        """
        _check_max_wait(max_wait)
        if overrides is None:
            overrides = ApplyOverrides()
        if env is None:
            env = os.environ

        files = _expand_paths(paths)
        resolved_entries, pending_failures = _resolve_all(files, overrides, env)

        if overrides.name is not None and len(resolved_entries) > 1:
            raise BatchNameConflictError("--name cannot be combined with multiple manifests")

        outcomes: list[ApplyOutcome] = list(pending_failures)
        if wait and on_event is not None:
            for failure in pending_failures:
                on_event(ApplyEvent(type="submitted", name=failure.name, outcome=failure))
        for resolved in resolved_entries:
            outcomes.append(await self._dispatch_one(resolved, wait=wait, max_wait=max_wait, on_event=on_event))
        return outcomes

    async def _dispatch_one(
        self,
        resolved: ResolvedManifest,
        *,
        wait: bool,
        max_wait: float | None,
        on_event: Callable[[ApplyEvent], None] | None,
    ) -> ApplyOutcome:
        """Submit one resolved manifest, optionally wait, and emit events.

        Split out of :meth:`apply_files` purely to keep that method's branch
        count below the lint threshold; the public contract is unchanged.
        """
        try:
            submitted = await self.apply(resolved)
        except Exception as exc:  # noqa: BLE001 — continue-on-error is the contract
            submitted = ApplyOutcome(
                name=resolved.name,
                action="failed",
                failure_reason=f"manifest {resolved.source_path}: {exc}",
                error_code=_error_code(exc),
            )

        if wait and on_event is not None:
            on_event(ApplyEvent(type="submitted", name=submitted.name, outcome=submitted))

        if not (wait and submitted.action in {"created", "updated"} and submitted.deployment_id is not None):
            return submitted

        try:
            terminal = await self._wait_for_terminal(submitted, max_wait)
        except Exception as exc:  # noqa: BLE001 — wait failures are per-manifest
            terminal = submitted.model_copy(update={"action": "failed", "failure_reason": f"wait error: {exc}"})

        if on_event is not None:
            on_event(ApplyEvent(type="terminal", name=terminal.name, outcome=terminal))
        return terminal
