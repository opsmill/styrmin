"""Deployment management commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from styrmin_sdk.exceptions import ApplyError, BatchNameConflictError, StyrminError
from styrmin_sdk.models import ComponentReplicas, ReplicaSource, UpdateDeploymentInput
from styrmin_sdk.models.deployment_manifest import ApplyEvent, ApplyOutcome, ApplyOverrides
from styrmin_sdk.resources.deployments import check_replica_counts

from styrminctl import client
from styrminctl.labels import format_driver_version_label
from styrminctl.output import (
    console,
    parse_json_argument,
    print_error,
    print_success,
    print_table,
    styrmin_error_handler,
)
from styrminctl.types import (
    ClusterContextId,
    ClusterContextName,
    DeploymentId,
    EnvironmentName,
    MaxWait,
    OptionalEnvironmentId,
)

# ``version_flags=()`` disables cyclopts's default ``--version`` meta-flag on
# this sub-app so ``deployments apply --version <X>`` binds to the subcommand
# parameter (which overrides spec.version in a manifest) instead of triggering
# the parent App's version banner.
deployments_app = App(name="deployments", help="Manage deployments.", version_flags=())


@deployments_app.command
async def create(
    driver: Annotated[str, Parameter(help="Application driver name.")],
    version: Annotated[str, Parameter(help="Application version to deploy.")],
    environment: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
    name: Annotated[str | None, Parameter(help="Custom deployment name (auto-generated if omitted).")] = None,
    config: Annotated[str | None, Parameter(help="JSON config (inline or @filepath).")] = None,
    driver_version_id: Annotated[
        str | None,
        Parameter(
            help="Pin a specific driver version (UUID). Defaults to the latest loaded driver version supporting the application version."
        ),
    ] = None,
) -> None:
    """Create a new deployment (deploy an application)."""
    with styrmin_error_handler():
        if environment is not None and id is not None:
            raise ValueError("Provide either an environment name or --id, not both")
        if environment is None and id is None:
            raise ValueError("Either an environment name or --id is required")
        if cluster_id is not None and cluster != "default":
            raise ValueError("Provide either --cluster or --cluster-id, not both")

        parsed_config = parse_json_argument(config)
        async with client.get_client() as sdk:
            task = await sdk.deployments.create(
                driver=driver,
                version=version,
                environment_id=id,
                environment_name=environment,
                cluster_id=cluster_id,
                cluster_name=cluster if cluster_id is None and id is None else None,
                name=name,
                config=parsed_config,
                driver_version_id=driver_version_id,
            )

    print_success(f"Deployment in progress (deployment: {task.deployment_id}, task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command
async def get(deployment_id: DeploymentId) -> None:
    """Get a deployment by ID."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            deployment = await sdk.deployments.get(deployment_id)

    adv = getattr(deployment, "application_driver_version", None)
    adv_content_hash = getattr(adv, "content_hash", None) if adv is not None else None
    adv_source_commit_sha = getattr(adv, "source_commit_sha", None) if adv is not None else None
    version_label = format_driver_version_label(
        version=deployment.application_version,
        content_hash=adv_content_hash,
        source_commit_sha=adv_source_commit_sha,
    )

    console.print(f"  ID: {deployment.id}")
    console.print(f"  Name: {deployment.name}")
    console.print(f"  Status: {deployment.status}")
    console.print(f"  Application version: {version_label}")
    console.print(f"  Driver version ID: {deployment.application_driver_version_id}")
    if adv_content_hash:
        console.print(f"  Content hash: {adv_content_hash}")
    elif adv_source_commit_sha:
        console.print(f"  Commit SHA: {adv_source_commit_sha}")
    console.print(f"  Environment ID: {deployment.environment_id}")
    console.print(f"  Config: {deployment.config or ''}")

    if deployment.application_instance:
        instance = deployment.application_instance
        console.print(f"  Instance: {instance.id} (status: {instance.status})")

    replicas = {row.component: row for row in deployment.component_replicas}
    rows = [
        {
            "id": str(c.id),
            "name": c.name,
            "enabled": str(c.enabled),
            "replicas": _replicas_cell(replicas.get(c.name), enabled=c.enabled),
        }
        for c in deployment.components
    ]
    rows.extend(
        {"id": "-", "name": row.component, "enabled": "-", "replicas": _replicas_cell(row, enabled=True)}
        for row in deployment.component_replicas
        if row.is_orphaned
    )
    if rows:
        print_table(rows, columns=["id", "name", "enabled", "replicas"], title="Components")


def _replicas_cell(row: ComponentReplicas | None, *, enabled: bool) -> str:
    """Replica count and its source for the Components table (contracts/cli-and-ui.md)."""
    if row is None:
        return ""
    if row.is_orphaned:
        return f"{row.override} (override, not applied: no longer declared)"
    if row.count is None:
        cell = "chart"
    else:
        labels = ["override" if row.source == ReplicaSource.OVERRIDE else "driver default"]
        if row.singleton:
            labels.append("singleton")
        cell = f"{row.count} ({', '.join(labels)})"
    if row.override is not None and not row.is_applicable:
        cell += f", override {row.override} not applied"
    return cell if enabled else f"{cell}, stopped: 0 pods"


@deployments_app.command
async def update(
    deployment_id: DeploymentId,
    *,
    config: Annotated[
        str,
        Parameter(
            help="JSON UpdateDeploymentInput payload (inline or @filepath); snake_case or camelCase keys accepted."
        ),
    ],
) -> None:
    """Update a deployment's configuration."""
    with styrmin_error_handler():
        parsed_config = parse_json_argument(config)
        check_replica_counts(parsed_config, source="--config")
        update_input = UpdateDeploymentInput.model_validate(parsed_config)
        async with client.get_client() as sdk:
            task = await sdk.deployments.update(deployment_id, input=update_input)

    if task is None:
        print_success("Deployment already up to date; no changes applied.")
        return
    print_success(f"Deployment update in progress (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command
async def scale(
    deployment_id: DeploymentId,
    component: Annotated[str, Parameter(help="Name of the component to scale.")],
    replicas: Annotated[
        int | None,
        Parameter(help="Replica count of the component, 1 or more. Leave out with --clear."),
    ] = None,
    *,
    clear: Annotated[
        bool,
        Parameter(help="Remove the replica override: the driver default or the chart's count applies."),
    ] = False,
) -> None:
    """Set or clear the replica override of one component.

    The component's other overrides and the other components' overrides are kept.
    """
    if (replicas is None) == (not clear):
        print_error("Give either a replica count or --clear.")
        sys.exit(1)
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.deployments.scale(deployment_id, component, None if clear else replicas)

    if task is None:
        print_success("Deployment already up to date; no changes applied.")
        return
    target = "the driver default or the chart's count" if clear else f"{replicas} replicas"
    print_success(f"Scaling {component} to {target} (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="update-version")
async def update_version(
    deployment_id: DeploymentId,
    version: Annotated[str, Parameter(help="New application version.")],
    *,
    driver_version_id: Annotated[
        str | None,
        Parameter(
            help="Pin a specific driver version (UUID). Defaults to the latest loaded driver version supporting the application version."
        ),
    ] = None,
    config: Annotated[
        str | None,
        Parameter(
            help="JSON UpdateDeploymentInput payload (inline or @filepath) written with the version and "
            "validated against the target driver version. Needs a Styrmin server with #388."
        ),
    ] = None,
) -> None:
    """Update a deployment's application version (internal API)."""
    with styrmin_error_handler():
        update_input = None
        if config:
            parsed_config = parse_json_argument(config)
            check_replica_counts(parsed_config, source="--config")
            update_input = UpdateDeploymentInput.model_validate(parsed_config)
        async with client.get_client() as sdk:
            task = await sdk.deployments.update_version(
                deployment_id, version=version, driver_version_id=driver_version_id, input=update_input
            )

    if task is None:
        print_success("Deployment already on the requested version; no changes applied.")
        return
    print_success(f"Version update in progress (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="start-components")
async def start_components(
    deployment_id: DeploymentId,
    *,
    component: Annotated[list[str], Parameter(help="Component name (repeat for multiple).")],
) -> None:
    """Start components of a deployment (internal API)."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.deployments.start_components(deployment_id, components=component)

    print_success(f"Components starting (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="stop-components")
async def stop_components(
    deployment_id: DeploymentId,
    *,
    component: Annotated[list[str], Parameter(help="Component name (repeat for multiple).")],
) -> None:
    """Stop components of a deployment (internal API)."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            task = await sdk.deployments.stop_components(deployment_id, components=component)

    print_success(f"Components stopping (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command(name="run-job")
async def run_job(
    deployment_id: DeploymentId,
    *,
    image: Annotated[str, Parameter(help="Container image to use.")],
    command: Annotated[list[str], Parameter(help="Command to run (repeat for multiple).")],
    env: Annotated[str, Parameter(help="Environment variables as JSON (inline or @filepath).")],
) -> None:
    """Run a job on a deployment (internal API)."""
    with styrmin_error_handler():
        parsed_env = parse_json_argument(env)
        async with client.get_client() as sdk:
            task = await sdk.deployments.run_job(deployment_id, image=image, commands=command, env=parsed_env)

    print_success(f"Job running (task: {task.id})")
    console.print(f"  Status: {task.status}")


@deployments_app.command
async def context(deployment_id: DeploymentId) -> None:
    """Get the context of a deployment."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            ctx = await sdk.deployments.get_context(deployment_id)

    console.print_json(data=ctx.context)


# Per-request HTTP timeout for `apply`. Lower than the global default (30s)
# so the command fails fast against an unreachable server instead of making
# the operator wait out the full budget. Each ``--wait`` poll is an
# individual request bounded by this value; ``--max-wait`` bounds the whole wait.
_APPLY_REQUEST_TIMEOUT_SECONDS = 10.0


def _failed_line(outcome: ApplyOutcome) -> str:
    code = f" [{outcome.error_code}]" if outcome.error_code else ""
    return f"failed {outcome.name}: {outcome.failure_reason or 'unknown error'}{code}"


def _format_outcome_line(outcome: ApplyOutcome) -> str:
    if outcome.action == "failed":
        return _failed_line(outcome)
    return f"{outcome.action} {outcome.name}"


def _format_wait_event_line(event: ApplyEvent) -> str | None:
    """Translate a streaming ``ApplyEvent`` into the ``--wait`` two-line format.

    Returns ``None`` if the event is a redundant ``terminal`` event for an
    outcome that already failed at submission — that failure has already
    been printed by the matching ``submitted`` event, so we suppress the
    duplicate to keep the two-line cadence honest.
    """
    outcome = event.outcome
    if event.type == "submitted":
        if outcome.action == "failed":
            return _failed_line(outcome)
        # An ``unchanged`` outcome dispatched no mutation, so no ``terminal``
        # event follows — report its final state on the submitted line.
        if outcome.action == "unchanged":
            return f"unchanged {outcome.name}"
        return f"submitted {outcome.name}"
    if outcome.action == "failed":
        return _failed_line(outcome)
    return f"running {outcome.name}"


def _print_pinned_image_warning(outcome: ApplyOutcome) -> None:
    """Warn on stderr that token-free image overrides stay pinned (FR-008); never changes the exit code."""
    components = outcome.pinned_image_components
    if not components:
        return
    noun = "override" if len(components) == 1 else "overrides"
    # Flush stdout first so the warning follows its outcome line in a combined CI log.
    sys.stdout.flush()
    print(
        f"warning: {outcome.name}: pinned image {noun} on {', '.join(components)} "
        f"will not follow version {outcome.target_version} (no {{{{ app.version }}}} token)",
        file=sys.stderr,
        flush=True,
    )


_OVERRIDE_KIND_LABELS = {
    "env_vars": "env var",
    "image": "image",
    "command": "command",
    "args": "args",
    "replicas": "replica",
}


def _join_words(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def _print_inapplicable_warning(outcome: ApplyOutcome) -> None:
    """Warn on stderr, per component, about overrides stored but not applied; never changes the exit code."""
    if not outcome.inapplicable_overrides:
        return
    sys.stdout.flush()
    for component, kinds in outcome.inapplicable_overrides.items():
        container_kinds = [kind for kind in kinds if kind != "replicas"]
        if container_kinds:
            overrides = f"{_join_words([_OVERRIDE_KIND_LABELS[kind] for kind in container_kinds])} override"
            plural = len(container_kinds) > 1
            stored, pronoun = (f"{overrides}s are", "them") if plural else (f"{overrides} is", "it")
            print(
                f"warning: {outcome.name}: {stored} stored on {component} but not applied: the driver "
                f"version declares no component container for {component}. Remove {pronoun} from the "
                f"manifest, or load a driver version that declares components.{component}.container "
                "and apply again",
                file=sys.stderr,
                flush=True,
            )
        if "replicas" in kinds:
            # A replica override needs no container; it is not applied only on an undeclared component.
            print(
                f"warning: {outcome.name}: {_OVERRIDE_KIND_LABELS['replicas']} override is stored on "
                f"{component} but not applied: the driver version does not declare {component}. "
                f"Remove it from the manifest, or load a driver version that declares "
                f"components.{component} and apply again",
                file=sys.stderr,
                flush=True,
            )


def _print_applicability_check_warning(outcome: ApplyOutcome) -> None:
    if outcome.applicability_check_error is None:
        return
    sys.stdout.flush()
    print(
        f"warning: {outcome.name}: could not check which overrides the driver version applies, "
        f"so overrides that are stored but not applied are not listed: {outcome.applicability_check_error}",
        file=sys.stderr,
        flush=True,
    )


def _print_warnings(outcome: ApplyOutcome) -> None:
    _print_pinned_image_warning(outcome)
    _print_inapplicable_warning(outcome)
    _print_applicability_check_warning(outcome)


def _summary_line(outcomes: list[ApplyOutcome]) -> str:
    created = sum(1 for o in outcomes if o.action == "created")
    updated = sum(1 for o in outcomes if o.action == "updated")
    unchanged = sum(1 for o in outcomes if o.action == "unchanged")
    failed = sum(1 for o in outcomes if o.action == "failed")
    return f"{created} created, {updated} updated, {unchanged} unchanged, {failed} failed"


@deployments_app.command
async def apply(
    *,
    file: Annotated[
        list[Path],
        Parameter(
            name=["-f", "--file"],
            help="Path to a YAML manifest file or a directory of YAML files (repeatable).",
        ),
    ],
    name: Annotated[str | None, Parameter(help="Override metadata.name (env: STYRMIN_NAME).")] = None,
    version: Annotated[str | None, Parameter(help="Override spec.version (env: STYRMIN_VERSION).")] = None,
    environment: Annotated[
        str | None,
        Parameter(help="Override spec.environment (env: STYRMIN_ENVIRONMENT)."),
    ] = None,
    cluster: Annotated[str | None, Parameter(help="Override spec.cluster (env: STYRMIN_CLUSTER).")] = None,
    wait: Annotated[bool, Parameter(help="Block until each deployment reaches a terminal state.")] = False,
    max_wait: MaxWait = 600,
) -> None:
    """Create or update deployments from one or more YAML manifests.

    Manifests use ``apiVersion: styrmin/v1`` / ``kind: Deployment``. Each ``-f``
    argument may point at a YAML file or a directory of YAML files; pass
    ``-f`` more than once to combine sources. A single file may contain
    multiple ``---``-separated documents; each is applied independently.

    Override precedence: CLI flag > environment variable > manifest field.
    The env vars are ``STYRMIN_NAME``, ``STYRMIN_VERSION``,
    ``STYRMIN_ENVIRONMENT``, ``STYRMIN_CLUSTER``. ``--name`` cannot be
    combined with batch input (more than one manifest).

    The ``spec.config`` block follows the typed ``UpdateDeploymentInput``
    semantics on update: top-level fields use full-replacement (omitting a
    field leaves the persisted state untouched, an empty list explicitly
    clears it), while ``spec.parameters`` uses merge semantics (entries
    merge on top of the persisted parameters dict).

    When a manifest changes an existing deployment's application version, a
    ``warning:`` line on stderr names the components whose image override has
    no ``{{ app.version }}`` token (they stay pinned). The exit code is unchanged.

    Example::

        styrminctl deployments apply -f my-app.yaml --version 1.2.3
        styrminctl deployments apply -f manifests/ -f extra.yaml
    """
    overrides = ApplyOverrides(name=name, version=version, environment=environment, cluster=cluster)

    def _stream_event(event: ApplyEvent) -> None:
        line = _format_wait_event_line(event)
        if line is not None:
            print(line)
        # Warn with the submitted line, before the wait, so it is not lost behind a long poll.
        if event.type == "submitted":
            _print_warnings(event.outcome)

    on_event = _stream_event if wait else None

    try:
        async with client.get_client(timeout=_APPLY_REQUEST_TIMEOUT_SECONDS) as sdk:
            outcomes = await sdk.deployments.apply_files(
                file, overrides=overrides, wait=wait, max_wait=max_wait, on_event=on_event
            )
    except (BatchNameConflictError, ApplyError, FileNotFoundError, StyrminError) as exc:
        prefix = "file not found: " if isinstance(exc, FileNotFoundError) else ""
        print(f"failed: {prefix}{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not wait:
        for outcome in outcomes:
            print(_format_outcome_line(outcome))
            _print_warnings(outcome)
    print(_summary_line(outcomes))

    if any(o.action == "failed" for o in outcomes):
        raise SystemExit(1)
