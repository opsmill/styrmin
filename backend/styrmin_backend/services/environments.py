"""Provides the environment services."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, Sequence
from uuid import UUID

from loguru import logger

from styrmin_backend.context.exceptions import InvalidEnvironmentContextError
from styrmin_backend.context.models.config import EnvironmentConfig
from styrmin_backend.context.validators import validate_environment_config
from styrmin_backend.db.models import Environment
from styrmin_backend.domain.models import Deployment
from styrmin_backend.services.backup.environment import (
    delete_environment_backups_for_environment,
    guard_no_clone_occupying_environment,
)
from styrmin_backend.services.capabilities import compute_environment_capabilities
from styrmin_backend.services.cluster_config_fanout import fan_out_environment_config
from styrmin_backend.services.clusters import resolve_cluster
from styrmin_backend.services.deployment import request_cluster_teardown
from styrmin_backend.services.env_vars.validator import validate_env_vars_dict
from styrmin_backend.services.exceptions import (
    AmbiguousIdentifierError,
    ClusterNotFoundError,
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
)
from styrmin_backend.services.scheduling.references import bind_deployment_references
from styrmin_backend.services.unit_of_work import UnitOfWork


def _prevalidate_environment_env_vars(config: dict | None) -> None:
    """Pre-validate environment-scope env vars so typed error codes survive.

    See :func:`styrmin_backend.services.deployment._prevalidate_deployment_env_vars`
    for the full rationale; in short, Pydantic's ``ValidationError`` collapses
    typed env-var errors into the generic ``INVALID_CONTEXT`` code, breaking
    FR-006/FR-007/FR-008/FR-009 and SC-003. Calling
    :func:`validate_env_vars_dict` here lets the typed errors propagate intact.
    """
    if not config:
        return
    env_vars = config.get("env_vars")
    if isinstance(env_vars, dict):
        validate_env_vars_dict("environment", env_vars)


if TYPE_CHECKING:
    from collections.abc import Mapping


def _extract_environment_slice_from_context(
    context: Any,
) -> dict[str, Any] | None:
    """Extract the environment-scope config dict from a persisted instance context.

    The instance ``context`` carries a serialised :class:`GlobalContext`
    (built by :func:`_resolve_instance_context` in
    ``backend/styrmin_backend/context/resolvers.py``). The environment-scope
    slice — the :class:`EnvironmentConfig` that was active when the instance
    was generated — is reachable as ``context.environment.config``.

    The helper accepts both the in-memory shape (a :class:`GlobalContext`
    Pydantic model on the domain :class:`Instance` entity) and the
    JSON-serialised shape (a plain ``dict`` as returned by SQLModel for the
    raw JSON column). Returns the env-config slice as a plain dict suitable
    for round-tripping through :meth:`EnvironmentConfig.model_validate`.
    Returns ``None`` when the context is missing or doesn't carry an
    environment slice (older instances written before the slice was
    persisted, hypothetical malformed rows). Callers treat ``None`` as
    "always redeploy" — see :func:`_deployment_already_at_config`.
    """
    if context is None:
        return None
    # Domain shape: GlobalContext Pydantic model.
    environment = getattr(context, "environment", None)
    if environment is not None:
        config = getattr(environment, "config", None)
        if config is None:
            return None
        # EnvironmentConfig is a Pydantic model; dump preserves None-vs-missing
        # the same way model_validate accepts on the way back.
        if hasattr(config, "model_dump"):
            return config.model_dump(mode="json")
        if isinstance(config, dict):
            return config
        return None
    # Raw JSON shape (dict from the JSON column).
    if isinstance(context, dict):
        env_block = context.get("environment")
        if not isinstance(env_block, dict):
            return None
        config = env_block.get("config")
        if isinstance(config, dict):
            return config
        return None
    return None


def _deployment_already_at_config(
    deployment: Deployment,
    new_config: EnvironmentConfig,
) -> bool:
    """Return True iff the deployment's active instance is already at ``new_config``.

    Per FR-010 / data-model.md §3, the env-config fanout decides whether
    each deployment needs a redeploy by comparing the active instance's
    embedded environment-config slice against the just-persisted config.
    Equality means the deployment is fully converged and the redeploy is
    skipped (no spurious Task / timeline entry); inequality means the
    deployment is a laggard and a redeploy is dispatched.

    Both sides are normalised through the canonical Pydantic round-trip
    (``EnvironmentConfig.model_validate(...).model_dump(exclude_none=True,
    mode="json")``) to flatten ``None``-vs-missing drift — a slice that
    omits ``ip_whitelist`` compares equal to a slice that explicitly sets
    ``ip_whitelist=None``.

    Returns ``False`` when:

    * the deployment has no active instance (must dispatch the first
      reconcile);
    * the active instance carries no extractable environment-config slice
      (older row, malformed shape — err on the side of redeploying);
    * the canonical comparison disagrees.
    """
    active = deployment.active_instance
    if active is None:
        return False
    instance_env_config_dict = _extract_environment_slice_from_context(active.context)
    if instance_env_config_dict is None:
        return False
    instance_env_config = EnvironmentConfig.model_validate(instance_env_config_dict)
    new_canon = new_config.model_dump(exclude_none=True, mode="json")
    instance_canon = instance_env_config.model_dump(exclude_none=True, mode="json")
    return new_canon == instance_canon


async def resolve_environment(
    uow: UnitOfWork,
    environment_id: UUID | None = None,
    environment_name: str | None = None,
    cluster_id: UUID | None = None,
    cluster_name: str | None = None,
) -> Environment:
    """Resolve an environment by ID or name. When using name, cluster context is required."""
    if environment_id is not None and environment_name is not None:
        raise AmbiguousIdentifierError(
            "Provide either environment_id or environment_name, not both"
        )
    if environment_id is not None:
        async with uow:
            environment = await uow.environments.get(environment_id)
            if environment is None:
                raise EnvironmentNotFoundError(
                    f"Environment not found: {environment_id}"
                )
            return environment
    if environment_name is not None:
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
        async with uow:
            environment = await uow.environments.get_by_name_in_cluster(
                environment_name, cluster.id
            )
            if environment is None:
                raise EnvironmentNotFoundError(
                    f"Environment not found: {environment_name!r} in cluster {cluster.name!r}"
                )
            return environment
    raise AmbiguousIdentifierError(
        "Either environment_id or environment_name is required"
    )


async def create_environment(
    name: str,
    cluster_id: UUID,
    uow: UnitOfWork,
    config: dict | None = None,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> Environment:
    """Create an environment with the given name and cluster_id.

    The new environment has no deployment, so an affinity term in ``config``
    may name only one of ``upcoming_deployments``: the deployments, by id with
    their names, that the caller is about to create in it (an environment clone).

    Raises:
        InvalidContextError: If the environment context is invalid.
        UnresolvableAffinityReferenceError: If an affinity term in ``config``
            names a deployment that is not in ``upcoming_deployments``.
    """
    async with uow:
        cluster = await uow.clusters.get(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(f"Cluster not found: {cluster_id}")

        if await uow.environments.get_by_name_in_cluster(name, cluster_id):
            raise EnvironmentAlreadyExistsError(
                "An environment with this name already exists in this cluster."
            )

        if config is None:
            config = {}

        # Pre-validate env-var bundles so typed error codes survive the
        # GraphQL boundary (FR-006/FR-007/FR-008/FR-009 / SC-003).
        _prevalidate_environment_env_vars(config)

        try:
            validate_environment_config(config)
        except InvalidEnvironmentContextError as e:
            raise InvalidContextError(str(e)) from e
        config = await bind_deployment_references(
            uow,
            None,
            config,
            path_prefix="environment.config",
            upcoming_deployments=upcoming_deployments,
        )

        environment = Environment(name=name, cluster_id=cluster_id, config=config)
        environment.capabilities = compute_environment_capabilities(environment)
        await uow.environments.create(environment)
        await uow.commit()
        returned_environment = await uow.environments.get_by_name_in_cluster(
            name, cluster_id
        )
        assert returned_environment is not None, (
            "Environment should be created successfully"
        )
        return returned_environment


async def get_environment(environment_id: UUID, uow: UnitOfWork) -> Environment:
    """Get an environment by its id."""
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        return environment


async def get_environments(uow: UnitOfWork) -> Sequence[Environment]:
    """Get all the environments."""
    async with uow:
        return await uow.environments.get_all()


def _emit_fanout_metric(environment_id: UUID, outcome: str, count: int) -> None:
    """Emit the number of deployments of one fanout outcome (FR-023a).

    The target metric is
    ``env_config_fanout_deployments_total{environment, outcome}`` where
    ``outcome`` is one of ``dispatched``, ``skipped_noop``,
    ``skipped_restoring``, ``skipped_waiting_for_ingress``,
    ``evaluation_failed`` or ``dispatch_failed``. The project does not yet wire a metrics backend
    (Prometheus / OTel exporter), so this helper is the call-site stub:
    it logs the would-be metric at ``info`` level with a clear marker so
    the data is recoverable from logs today and the wiring becomes a
    one-line edit once the backend lands. The call site existing is what
    FR-023a requires.

    TODO (metrics-backend): replace the ``logger.info`` with the real
    counter increment (e.g. ``METRIC.labels(...).inc(count)``) once a metrics
    client is registered with the backend.
    """
    logger.info(
        "metric=env_config_fanout_deployments_total environment_id={} outcome={} count={}",
        environment_id,
        outcome,
        count,
    )


_FANOUT_METRIC_OUTCOMES = (
    "dispatched",
    "skipped_noop",
    "skipped_restoring",
    "skipped_waiting_for_ingress",
    "evaluation_failed",
    "dispatch_failed",
)


async def update_environment(
    environment_id: UUID,
    uow: UnitOfWork,
    config: dict | None = None,
    *,
    acting_user_id: UUID,
) -> Environment:
    """Update an environment's config and fan out redeploys to its deployments.

    Persists the validated ``EnvironmentConfig`` on the environment row,
    commits the row **before** the fanout starts (FR-009a so a
    crash mid-fanout never leaves the persisted config behind), then
    redeploys every live, non-internal deployment whose active instance
    stores another environment config (``_deployment_already_at_config``,
    FR-010 / data-model.md §3) through :func:`fan_out_environment_config`.
    Each redeploy runs in its own savepoint, so a failure rolls back only
    that deployment's writes; it is caught, logged, counted, and does not
    propagate — the env-config row stays persisted and peer deployments
    are unaffected (FR-008 / Edge Cases "Per-deployment failure", #452).

    The fanout manages the environment's dedicated ingress controller as the
    cluster config fan-out does (ADR-066, #424): it creates the controller,
    attributed to ``acting_user_id``, or redeploys it when its values differ,
    and an application that moves onto the controller waits until the
    controller is RUNNING with the new values; the status reporter then
    redeploys it. The controller is removed once no application uses it.

    Tombstoned (``deleted_at IS NOT NULL``), ``DELETING`` and internal
    deployments get no redeploy. They are NOT counted toward ``skipped_noop``
    (which is reserved for "deployment evaluated and found already at
    config"); ``evaluated`` counts every listed deployment so operators can
    see the distinction between "no rows to consider" and "rows considered,
    all skipped".

    An environment a non-terminal clone is still building is refused outright
    (010 research D8): its counterpart deployments are mid-restore, and this
    fan-out's ``redeploy_for_environment_update`` would race the restore flow's
    namespace delete-and-wait for the same objects — the one race ADR-0055
    decision 4 excluded by construction and cannot exclude here. Only the clone
    half of the environment-level guard applies: an in-flight environment
    backup or restore has never blocked a config update and must not start to.

    Raises:
        EnvironmentNotFoundError: When ``environment_id`` does not exist.
        EnvironmentOperationInProgressError: When a non-terminal clone is still
            building this environment (010 research D8).
        InvalidContextError: When the new config fails ``EnvironmentConfig``
            validation (e.g. invalid env var names, oversized dicts).
        UnresolvableAffinityReferenceError: When an affinity term in the new
            config names a deployment that is not a live deployment of the
            environment; nothing is saved.
    """
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        # Before the ``config is None`` short-circuit on purpose: "busy" is a
        # property of the environment, not of the payload, so a no-op update
        # must not read as accepted while a clone owns it.
        await guard_no_clone_occupying_environment(environment_id, uow)

        if config is None:
            # Idempotent no-op: nothing to validate, nothing to fan out.
            # Commit is a no-op but kept for API symmetry.
            await uow.commit()
            refreshed = await uow.environments.get(environment_id)
            assert refreshed is not None, "Environment should still exist after update"
            return refreshed

        # Pre-validate env-var bundles so typed error codes survive the
        # GraphQL boundary (FR-006/FR-007/FR-008/FR-009 / SC-003).
        _prevalidate_environment_env_vars(config)
        try:
            validate_environment_config(config)
        except InvalidEnvironmentContextError as e:
            raise InvalidContextError(str(e)) from e
        # Before the save, so a refused term leaves the stored config unchanged.
        config = await bind_deployment_references(
            uow, environment_id, config, path_prefix="environment.config"
        )

        # Persist the env-config row. Per FR-009a this commit MUST run
        # before any Task dispatch so a crash mid-fanout never reverts
        # the config.
        environment.config = config
        environment.capabilities = compute_environment_capabilities(environment)
        await uow.commit()

        result = await fan_out_environment_config(
            environment,
            uow,
            acting_user_id,
            at_config=partial(
                _deployment_already_at_config,
                new_config=EnvironmentConfig.model_validate(config),
            ),
        )

        # ``redeploy_for_environment_update`` and the controller actions save
        # the Task rows and the active-instance pointers but do NOT commit;
        # ``UnitOfWork.__aexit__`` does not commit either, so without this
        # commit they are dropped (FR-006/FR-009).
        await uow.commit()

        counts = result.counts()
        for outcome in _FANOUT_METRIC_OUTCOMES:
            if counts[outcome]:
                _emit_fanout_metric(environment_id, outcome, counts[outcome])
        # One audit log entry per fanout invocation regardless of
        # dispatched count — FR-023. True environment-wide no-ops still
        # produce an entry with ``dispatched=0``.
        logger.info(
            "env_config_fanout_dispatched environment_id={} evaluated={} "
            "dispatched={} skipped_noop={} skipped_restoring={} "
            "dispatch_failed={} skipped_waiting_for_ingress={} "
            "evaluation_failed={} ingress_controllers_created={} "
            "ingress_controllers_redeployed={} ingress_controllers_removed={} "
            "ingress_controller_failed={} ingress_controller_removal_failed={}",
            environment_id,
            result.evaluated,
            result.dispatched,
            result.skipped_noop,
            result.skipped_restoring,
            result.dispatch_failed,
            result.skipped_waiting_for_ingress,
            result.evaluation_failed,
            result.ingress_controllers_created,
            result.ingress_controllers_redeployed,
            result.ingress_controllers_removed,
            result.ingress_controller_failed,
            result.ingress_controller_removal_failed,
        )

        refreshed = await uow.environments.get(environment_id)
        assert refreshed is not None, "Environment should still exist after update"
        return refreshed


async def delete_environment(environment_id: UUID, uow: UnitOfWork) -> None:
    """Delete an environment, settling its clone records and snapshots first.

    Four steps, and the order is load-bearing.

    1. **Clone records are settled before anything else** (010 research D9).
       An environment can appear on a clone record in two roles, and each has
       its own rule:

       * as the clone's **source** — a clone that has a created environment
         survives with ``source_environment_id`` nulled, because that
         environment is an ordinary environment which outlives the source and
         must keep its provenance (``source_environment_name`` keeps it
         readable); if it was still building, it also picks up a fatal
         ``source_environment_deleted`` marker so it comes to rest instead of
         reporting progress it can no longer make. A non-terminal clone that
         never created anything is deleted outright, and the clone flow
         tolerates its row vanishing mid-flight.
       * as the clone's **created** environment — this is the *discard* path
         (spec SC-005) and is always allowed. The record survives as history
         with ``created_environment_id`` nulled plus a
         ``created_environment_deleted`` marker, fatal iff the clone was still
         non-terminal, which is what drives a stuck clone terminal.

       Settling first is what keeps step 2 from wedging: deleting an environment
       backup refuses while a clone's capture of it is in flight (FR-008), and
       after this step every clone the guard can still see is terminal — the
       others are gone.

    2. **Environment backups cascade.** ``environmentbackup.environment_id`` is
       a non-nullable FK, so a snapshot outliving its environment is not
       representable: the environment's snapshots (and their environment
       restores, constituent backups, and constituent restores) are deleted with
       the same cascade as deleting a snapshot directly (spec FR-015). Skipping
       it would turn every delete of an environment that has ever been
       snapshotted into a constraint violation surfacing as an opaque
       ``INTERNAL_ERROR``.

    3. **Deployments cascade.** ``deployment.environment_id`` is non-nullable
       too, so the same reasoning applies one level down: every deployment of
       the environment is asked to tear its cluster resources down (the
       operator's ``deletionRequested`` path, which ends by deleting the
       namespace) and then its rows — instances, components, services, tasks,
       pod/CRD status, schedules and its own backups — are deleted. Without
       this, deleting *any* environment that ever held a deployment fails on a
       NOT NULL violation, which is what made the clone discard path (spec
       SC-005) unreachable: a clone's created environment always holds at least
       its counterparts and an internal ingress controller.

    4. **The environment row goes.**

    Raises:
        EnvironmentNotFoundError: When ``environment_id`` does not exist.
    """
    # Deferred: ``services.backup.clone`` imports this module for
    # ``resolve_environment``, so hoisting these would make the two a cycle —
    # the same reason ``guard_no_clone_occupying_environment`` defers its import.
    from styrmin_backend.services.backup.clone import (
        detach_clones_from_created_environment,
        resolve_clones_of_deleted_source_environment,
    )

    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        # Both clone roles are settled in one transaction, before the backup
        # cascade: the discard marker and the FK release have to land together,
        # and the non-terminal source clones have to be gone before the FR-008
        # guard can see them.
        discarded_clones = await detach_clones_from_created_environment(
            environment_id, uow
        )
        source_clones = await resolve_clones_of_deleted_source_environment(
            environment_id, uow
        )
        await uow.commit()

    cascaded = await delete_environment_backups_for_environment(environment_id, uow)

    # Cluster teardown is requested before the rows go, because the request is
    # keyed by deployment id and there is nothing left to enumerate afterwards.
    # It is best-effort (see ``request_cluster_teardown``): a deployment whose
    # CR never existed must not keep the environment undeletable.
    async with uow:
        live_deployments = await uow.deployments.find_all_by_environment(environment_id)
    # Counted, not assumed: the rows below are deleted whether or not the
    # cluster answered, so a teardown that failed is a namespace left running
    # with nothing in the database pointing at it. The audit line has to say how
    # many actually got the signal — reporting the number of *attempts* as
    # ``teardown_requested`` made an unreachable cluster indistinguishable from
    # a clean teardown.
    teardown_requested = 0
    teardown_failed: list[UUID] = []
    for deployment in live_deployments:
        if await request_cluster_teardown(deployment.id):
            teardown_requested += 1
        else:
            teardown_failed.append(deployment.id)
    if teardown_failed:
        logger.warning(
            "environment_delete_teardown_incomplete environment_id={} "
            "teardown_failed={} deployment_ids={} cluster resources may remain; "
            "their database rows are being removed anyway",
            environment_id,
            len(teardown_failed),
            [str(deployment_id) for deployment_id in teardown_failed],
        )

    async with uow:
        deleted_deployment_ids = await uow.deployments.delete_all_for_environment(
            environment_id
        )
        await uow.commit()

    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            # A concurrent delete won the race; the requested end state holds.
            return
        await uow.environments.delete(environment)
        await uow.commit()

    logger.info(
        "environment_deleted environment_id={} environment_backups_deleted={} "
        "deployments_deleted={} teardown_requested={} teardown_failed={} "
        "clones_discarded={} source_clones_kept={} source_clones_deleted={} "
        "source_clones_failed={}",
        environment_id,
        cascaded,
        len(deleted_deployment_ids),
        teardown_requested,
        len(teardown_failed),
        discarded_clones,
        source_clones.kept,
        source_clones.deleted,
        source_clones.failed,
    )
