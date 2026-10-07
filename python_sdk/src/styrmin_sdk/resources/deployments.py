"""Deployment resource operations."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import ValidationError

from styrmin_sdk._queries import load_query
from styrmin_sdk._wait import (
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
    ManifestValidationError,
    ResourceAlreadyExistsError,
    StyrminError,
)
from styrmin_sdk.graphql._generated.delete_deployment import (
    DeleteDeployment,
    DeleteDeploymentDeleteDeployment,
)
from styrmin_sdk.graphql._generated.deploy import Deploy, DeployDeploy
from styrmin_sdk.graphql._generated.get_deployment import GetDeployment, GetDeploymentDeployment
from styrmin_sdk.graphql._generated.get_deployment_by_name import (
    GetDeploymentByName,
    GetDeploymentByNameDeployment,
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
    DeploymentConfigInput,
    ParameterValueInput,
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
    ResolvedManifest,
    resolve_overrides,
)
from styrmin_sdk.models.image_reference import pinned_image_components
from styrmin_sdk.resources._base import BaseResource, JsonValue
from styrmin_sdk.resources.tasks import TaskResource


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
    try:
        return DeploymentConfigInput.model_validate(dict(manifest.config))
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
    ) -> list[ListDeploymentsEnvironmentDeployments]:
        """List the deployments belonging to an environment.

        Each entry carries the deployment's active application instance
        (``application_instance``), or ``None`` when the deployment has no
        active instance yet.
        """
        result = await self._transport.execute(
            load_query("list_deployments"),
            {"environmentId": str(environment_id), "includeDeleted": include_deleted},
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
        ``UpdateDeploymentInput`` input type. Top-level fields use
        full-replacement semantics: any field omitted (``None``) leaves the
        corresponding persisted state untouched; an empty list/dict explicitly
        clears it. The single exception is ``parameters``, which uses merge
        semantics — entries in the list merge on top of the persisted
        parameters dict.

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
    ) -> UpdateDeploymentVersionUpdateDeploymentVersion | None:
        """Update a deployment's application version.

        Without ``driver_version_id`` the deployment is bound to the latest
        loaded driver version supporting ``version``; with it, the binding is
        pinned to that specific driver version.

        Returns ``None`` when the backend detects a no-op (the requested
        state equals the current one): the resolver returns ``null`` and no
        task is dispatched.
        """
        variables: dict[str, Any] = {
            "deploymentId": str(deployment_id),
            "version": version,
        }
        if parameters is not None:
            variables["parameters"] = parameters
        if driver_version_id is not None:
            variables["driverVersionId"] = str(driver_version_id)
        result = await self._transport.execute(
            load_query("update_version"),
            variables,
        )
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
          :class:`DriverMismatchError` otherwise), then dispatch
          ``update_deployment`` for config/parameters and, if the version
          differs, ``update_deployment_version``. The two run sequentially,
          config-first — never parallel — so the upgraded version
          reconciles against the new config rather than the stale one.

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
        ``failure_reason`` is populated. The
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

        ``update_deployment`` (config/parameters) MUST run before
        ``update_deployment_version`` so the upgraded version reconciles
        against the new config rather than briefly observing stale values.

        The client is intentionally thin: it does NOT guess what changed.
        Both ``update`` and ``update_version`` are dispatched unconditionally
        and the backend owns no-op detection — each resolver returns ``null``
        (mapped here to ``None``) when the submitted state already matches the
        current instance. When BOTH calls return ``None`` the apply is a true
        no-op and returns ``action="unchanged"``; otherwise it is ``"updated"``
        with ``task_id`` set to the last non-null task (the version task when a
        version change happened, else the config task). An ``updated`` outcome that
        changes the application version also carries ``target_version`` and the
        token-free ``pinned_image_components`` (FR-008); ``apply`` never prompts.
        """
        existing_driver_name = existing.application_driver_version.application_driver.name
        if existing_driver_name != manifest.driver:
            raise DriverMismatchError(
                f"driver mismatch (manifest={manifest.driver!r}, existing={existing_driver_name!r}); "
                "driver changes require delete-and-recreate"
            )

        update_input = _build_update_input(manifest)
        update_task = await self.update(existing.id, input=update_input)

        try:
            version_task = await self.update_version(existing.id, manifest.version)
        except Exception as exc:  # noqa: BLE001 — wrap so apply_files can attribute
            # When the version mutation fails after the config/parameters update
            # was dispatched, flag the partial-update state explicitly so the
            # operator knows the deployment may now be half-updated.
            prefix = "config/parameters were updated; " if update_task is not None else ""
            return ApplyOutcome(
                name=manifest.name,
                action="failed",
                deployment_id=existing.id,
                task_id=update_task.id if update_task is not None else None,
                failure_reason=f"{prefix}version upgrade failed: {exc}",
            )

        # Backend-driven no-op: both mutations reported nothing to do.
        if update_task is None and version_task is None:
            return ApplyOutcome(
                name=manifest.name,
                action="unchanged",
                deployment_id=existing.id,
            )

        # At least one mutation dispatched a task. The version task is the last
        # non-null task (it runs after the config update), so prefer it.
        last_task = version_task if version_task is not None else update_task
        version_changed = manifest.version != existing.application_version
        return ApplyOutcome(
            name=manifest.name,
            action="updated",
            deployment_id=existing.id,
            task_id=last_task.id if last_task is not None else None,
            target_version=manifest.version if version_changed else None,
            pinned_image_components=(
                pinned_image_components(_effective_image_overrides(update_input, existing.config))
                if version_changed
                else []
            ),
        )

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
            await asyncio.sleep(WAIT_POLL_INTERVAL_SECONDS)
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
        return f'step "{step.name}" failed: {step.error}' if step.error else f'step "{step.name}" failed'

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
