"""Environment clone commands.

``env-clones create`` copies a live environment into a *new* environment on the
same cluster, built entirely from a fresh environment backup of the source. The
parent ``status`` is *derived* from the clone's own steps on every read, so
``--wait`` polls for a terminal derived status (``COMPLETED`` / ``PARTIAL`` /
``FAILED``) rather than for a stored column — the same contract as
``env-backups``.

One difference from ``env-backups`` worth knowing: a clone can come back
``IN_PROGRESS`` from the mutation itself, because any deployment skipped upfront
is recorded together with the clone row and that alone moves the derivation off
``PENDING``. Nothing here treats ``PENDING`` as the guaranteed first status.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Protocol

from cyclopts import App, Parameter
from styrmin_sdk import UpdateEnvironmentInput

from styrminctl import client
from styrminctl.output import (
    console,
    parse_json_argument,
    print_error,
    print_success,
    print_table,
    styrmin_error_handler,
)
from styrminctl.resolve import resolve_environment_id
from styrminctl.types import (
    ClusterContextId,
    ClusterContextName,
    EnvironmentCloneId,
    EnvironmentName,
    MaxWait,
    OptionalEnvironmentId,
    PollInterval,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from styrmin_sdk import EnvironmentCloneDeploymentOutcome, EnvironmentCloneStatus, StyrminClient

environment_clones_app = App(name="env-clones", help="Clone environments and track clone operations.")


#: Terminal clone statuses that mean "not everything made it into the clone".
#: The status is derived synchronously, so the mutation can already return one of
#: these — see :func:`create`.
_FAILED_STATUSES = frozenset({"FAILED", "PARTIAL"})


class _DeploymentResultLike(Protocol):
    """The per-source-deployment outcome fields every clone projection carries."""

    @property
    def deployment_name(self) -> str: ...

    @property
    def outcome(self) -> EnvironmentCloneDeploymentOutcome: ...

    @property
    def reason(self) -> str | None: ...


class _DetailedDeploymentResultLike(_DeploymentResultLike, Protocol):
    """A per-deployment outcome that also names the counterpart it produced.

    The create and get projections select ``counterpartDeploymentId`` and
    ``restoreId``; the list projection does not (it only renders counts), which
    is why this is a separate protocol.
    """

    @property
    def counterpart_deployment_id(self) -> object | None: ...

    @property
    def restore_id(self) -> object | None: ...


class _EnvironmentCloneLike(Protocol):
    """A clone as returned by either the clone mutation or the get query.

    Both carry the same derived status, per-deployment attribution and
    operation-level errors, and the terminal report is reached from both paths
    (the mutation can already return a terminal status), so the reporter is
    typed structurally rather than against one of the two generated shapes.
    """

    @property
    def status(self) -> EnvironmentCloneStatus: ...

    @property
    def deployment_results(self) -> Sequence[_DetailedDeploymentResultLike]: ...

    @property
    def clone_errors(self) -> Sequence[str]: ...


async def _resolve_deployment_ids(
    sdk: StyrminClient,
    *,
    environment_id: str,
    deployments: Sequence[str] | None,
) -> list[str] | None:
    """Turn ``--deployment`` values into the UUID list the mutation takes.

    Each value is either a deployment UUID (used as-is) or a deployment name
    resolved within the *source* environment. ``None`` means "no selection" and
    is passed through as ``None`` — which the backend reads as "every eligible
    deployment" (FR-003), a different thing from an empty selection.

    Raises ``ValueError`` for a name with no match in the source environment,
    rather than letting it reach the mutation as nothing at all.
    """
    if deployments is None:
        return None

    names = [value for value in deployments if not _is_uuid(value)]
    by_name: dict[str, str] = {}
    if names:
        by_name = {deployment.name: str(deployment.id) for deployment in await sdk.deployments.list(environment_id)}

    resolved: list[str] = []
    for value in deployments:
        if _is_uuid(value):
            resolved.append(value)
            continue
        if value not in by_name:
            raise ValueError(f"No deployment named '{value}' in the source environment")
        resolved.append(by_name[value])
    return resolved


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _deployment_counts(deployment_results: Sequence[_DeploymentResultLike]) -> tuple[int, int, int, int]:
    """Return ``(cloned, skipped, failed, total)`` for a clone's per-deployment outcomes.

    Every source deployment considered is in exactly one bucket or still
    ``PENDING`` (SC-003); pending entries show up only in the total.
    """
    cloned = sum(1 for result in deployment_results if result.outcome.value == "CLONED")
    skipped = sum(1 for result in deployment_results if result.outcome.value == "SKIPPED")
    failed = sum(1 for result in deployment_results if result.outcome.value == "FAILED")
    return cloned, skipped, failed, len(deployment_results)


def _print_deployment_results(deployment_results: Sequence[_DetailedDeploymentResultLike]) -> None:
    """Print every source deployment with its outcome and, for a skip or failure, its reason.

    ``reason`` is free text from the backend, not a closed vocabulary, so it is
    printed verbatim rather than mapped through a lookup table that would drop
    unknown values.
    """
    if not deployment_results:
        console.print("  Deployments: none")
        return

    console.print("  Deployments:")
    for result in deployment_results:
        detail = result.outcome.value
        if result.reason is not None:
            detail = f"{detail} — {result.reason}"
        if result.counterpart_deployment_id is not None:
            detail = f"{detail} (counterpart {result.counterpart_deployment_id})"
        if result.restore_id is not None:
            detail = f"{detail} (restore {result.restore_id})"
        console.print(f"    - {result.deployment_name}: {detail}")


def _print_clone_errors(clone_errors: Sequence[str]) -> None:
    """Print the operation-level events, which arrive pre-flattened as ``step: error``."""
    if not clone_errors:
        return

    console.print("  Clone errors:")
    for clone_error in clone_errors:
        console.print(f"    - {clone_error}")


def _report_terminal_status(environment_clone: _EnvironmentCloneLike) -> None:
    """Print the polled outcome and exit non-zero unless every deployment was cloned.

    ``PARTIAL`` exits non-zero too: the clone exists and its cloned deployments
    are real, but a script that asked for a copy of an environment did not get
    one for every deployment, and the exit code is the only machine-readable
    place to say so.
    """
    status = environment_clone.status.value
    if status == "COMPLETED":
        print_success("Environment clone completed")
        return

    if status == "PARTIAL":
        console.print("[yellow]Warning:[/yellow] Environment clone PARTIAL — some deployments were not cloned")
    else:
        print_error(f"Environment clone {status}")
    _print_deployment_results(environment_clone.deployment_results)
    _print_clone_errors(environment_clone.clone_errors)
    raise SystemExit(1)


@environment_clones_app.command
async def create(
    environment: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
    name: Annotated[str, Parameter(help="Name of the new environment to create.")],
    deployment: Annotated[
        list[str] | None,
        Parameter(
            name="--deployment",
            help="Source deployment to include, by name or UUID (repeat for multiple). Omit to include all eligible.",
        ),
    ] = None,
    config_override: Annotated[
        str | None,
        Parameter(
            help="JSON UpdateEnvironmentInput merged over the captured config (inline or @filepath); snake_case or camelCase keys accepted."
        ),
    ] = None,
    clear_config_field: Annotated[
        list[str] | None,
        Parameter(
            name="--clear-config-field",
            help="Captured config field to remove before the override merge, by snake_case EnvironmentConfig field name (repeat for multiple).",
        ),
    ] = None,
    wait: Annotated[bool, Parameter(help="Wait for the clone to reach a terminal state.")] = False,
    max_wait: MaxWait = 1800,
    interval: PollInterval = 5,
) -> None:
    """Clone an environment into a new environment on the same cluster.

    Target the source environment by name (optionally with --cluster/--cluster-id)
    or by --id. A fresh environment backup of the source is captured first and
    the clone is built entirely from it, so the copy holds the source's data as
    of capture time. Requires the ADMIN role.
    """
    with styrmin_error_handler():
        parsed_override = parse_json_argument(config_override)
        override_input = UpdateEnvironmentInput.model_validate(parsed_override) if parsed_override is not None else None

        async with client.get_client() as sdk:
            environment_id = await resolve_environment_id(
                sdk,
                name=environment,
                environment_id=id,
                cluster=cluster,
                cluster_id=cluster_id,
            )
            deployment_ids = await _resolve_deployment_ids(sdk, environment_id=environment_id, deployments=deployment)
            environment_clone = await sdk.environment_clones.create(
                name=name,
                environment_id=environment_id,
                deployment_ids=deployment_ids,
                config_override=override_input,
                clear_config_fields=clear_config_field,
            )

            cloned, skipped, failed, total = _deployment_counts(environment_clone.deployment_results)
            summary = (
                f"Environment clone '{environment_clone.name}' started "
                f"(id: {environment_clone.id}, status: {environment_clone.status.value}, "
                f"source: {environment_clone.source_environment_name}, "
                f"deployments: {cloned}/{skipped}/{failed}/{total} cloned/skipped/failed/total)"
            )

            if environment_clone.status.value in _FAILED_STATUSES:
                # The status is derived synchronously, so a clone that failed at
                # registration (or one whose only deployments were skipped
                # upfront) comes back terminal from the mutation itself.
                # Printing "Success" and exiting 0 there would report a clone
                # that does not exist as one that does. Nothing is polled:
                # FAILED and PARTIAL are terminal already.
                console.print(summary)
                _report_terminal_status(environment_clone)

            print_success(summary)
            _print_deployment_results(environment_clone.deployment_results)
            _print_clone_errors(environment_clone.clone_errors)

            if wait:
                console.print("Waiting for the clone to complete...")
                environment_clone = await sdk.environment_clones.wait_for_clone(
                    environment_clone.id, max_wait=max_wait, interval=interval
                )
                _report_terminal_status(environment_clone)


@environment_clones_app.command
async def get(environment_clone_id: EnvironmentCloneId) -> None:
    """Get environment clone details, including per-deployment outcomes."""
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_clone = await sdk.environment_clones.get(environment_clone_id)

    console.print(f"  ID: {environment_clone.id}")
    console.print(f"  Name: {environment_clone.name}")
    console.print(f"  Status: {environment_clone.status.value}")
    console.print(f"  Source environment: {environment_clone.source_environment_name}")
    if environment_clone.source_environment is None:
        # A terminal clone outlives its source; the denormalised name keeps the
        # provenance readable, so say so rather than printing a bare "None".
        console.print("    (source environment deleted)")
    else:
        console.print(f"    ID: {environment_clone.source_environment.id}")
    if environment_clone.environment_backup is None:
        console.print("  Environment backup: none (never linked, or deleted after the clone finished)")
    else:
        console.print(
            f"  Environment backup: {environment_clone.environment_backup.name} "
            f"(id: {environment_clone.environment_backup.id}, "
            f"status: {environment_clone.environment_backup.status.value})"
        )
    if environment_clone.created_environment is None:
        console.print("  Created environment: none yet")
    else:
        console.print(
            f"  Created environment: {environment_clone.created_environment.name} "
            f"(id: {environment_clone.created_environment.id})"
        )
        console.print(f"    Config: {environment_clone.created_environment.config}")
    requested = environment_clone.requested_deployment_ids
    console.print(f"  Requested deployments: {', '.join(str(d) for d in requested) if requested else 'all eligible'}")
    # Stored and returned as canonical snake_case EnvironmentConfig JSON, even
    # though it is *sent* as a camelCase UpdateEnvironmentInput.
    console.print(f"  Config override: {environment_clone.config_override or 'none'}")
    cleared = environment_clone.clear_config_fields
    console.print(f"  Cleared config fields: {', '.join(cleared) if cleared else 'none'}")
    console.print(f"  Created on: {environment_clone.created_on}")
    _print_deployment_results(environment_clone.deployment_results)
    _print_clone_errors(environment_clone.clone_errors)


@environment_clones_app.command(name="list")
async def list_environment_clones(
    environment: EnvironmentName = None,
    *,
    id: OptionalEnvironmentId = None,
    cluster: ClusterContextName = "default",
    cluster_id: ClusterContextId = None,
) -> None:
    """List the clones taken of an environment, newest first.

    Scoped by *source* environment: a clone-born environment's own provenance is
    the source-side record, not an entry in its own list.
    """
    with styrmin_error_handler():
        async with client.get_client() as sdk:
            environment_id = await resolve_environment_id(
                sdk,
                name=environment,
                environment_id=id,
                cluster=cluster,
                cluster_id=cluster_id,
            )
            environment_clones = await sdk.environment_clones.list(environment_id=environment_id)

    if not environment_clones:
        console.print("No environment clones found.")
        return

    rows = []
    for environment_clone in environment_clones:
        cloned, skipped, failed, total = _deployment_counts(environment_clone.deployment_results)
        rows.append(
            {
                "id": str(environment_clone.id),
                "name": environment_clone.name,
                "status": environment_clone.status.value,
                "created_environment": (
                    str(environment_clone.created_environment.id)
                    if environment_clone.created_environment is not None
                    else ""
                ),
                "deployments": f"{cloned}/{skipped}/{failed}/{total}",
                "created_on": str(environment_clone.created_on),
            }
        )
    print_table(
        rows,
        columns=["id", "name", "status", "created_environment", "deployments", "created_on"],
        title="Environment clones (deployments: cloned/skipped/failed/total)",
    )
