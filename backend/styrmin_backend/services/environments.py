"""Provides the environment services."""

from __future__ import annotations

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
from styrmin_backend.services.clusters import resolve_cluster
from styrmin_backend.services.deployment import redeploy_for_environment_update
from styrmin_backend.services.env_vars.validator import validate_env_vars_dict
from styrmin_backend.services.exceptions import (
    AmbiguousIdentifierError,
    ClusterNotFoundError,
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
)
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
    pass


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
    name: str, cluster_id: UUID, uow: UnitOfWork, config: dict | None = None
) -> Environment:
    """Create an environment with the given name and cluster_id.

    Raises:
        InvalidContextError: If the environment context is invalid.
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


def _emit_fanout_metric(environment_id: UUID, outcome: str) -> None:
    """Emit a per-deployment fanout outcome metric (FR-023a).

    The target metric is
    ``env_config_fanout_deployments_total{environment, outcome}`` where
    ``outcome`` is one of ``dispatched``, ``skipped_noop``, or
    ``dispatch_failed``. The project does not yet wire a metrics backend
    (Prometheus / OTel exporter), so this helper is the call-site stub:
    it logs the would-be metric at ``info`` level with a clear marker so
    the data is recoverable from logs today and the wiring becomes a
    one-line edit once the backend lands. The call site existing is what
    FR-023a requires.

    TODO (metrics-backend): replace the ``logger.info`` with the real
    counter increment (e.g. ``METRIC.labels(...).inc()``) once a metrics
    client is registered with the backend.
    """
    logger.info(
        "metric=env_config_fanout_deployments_total environment_id={} outcome={}",
        environment_id,
        outcome,
    )


async def update_environment(
    environment_id: UUID, uow: UnitOfWork, config: dict | None = None
) -> Environment:
    """Update an environment's config and fan out redeploys to its deployments.

    Persists the validated ``EnvironmentConfig`` on the environment row,
    commits the row **before** entering the fanout loop (FR-009a so a
    crash mid-fanout never leaves the persisted config behind), then
    iterates over every non-tombstoned, non-internal deployment in the
    environment dispatching :func:`redeploy_for_environment_update`. Each
    iteration runs ``_deployment_already_at_config`` first; deployments
    whose active instance is already at ``new_config`` are skipped (no
    spurious Task / timeline entry, FR-010 / data-model.md §3). Per-
    deployment dispatch failures are caught, logged, counted, and do not
    propagate — the env-config row stays persisted and peer deployments
    are unaffected (FR-008 / Edge Cases "Per-deployment failure").

    Tombstoned (``deleted_at IS NOT NULL``) and internal deployments are
    excluded from the fanout per FR-012 / FR-013. They are NOT counted
    toward ``skipped_noop`` (which is reserved for "deployment evaluated
    and found already at config"); ``evaluated`` counts the total
    iteration including the excluded rows so operators can see the
    distinction between "no rows to consider" and "rows considered, all
    skipped".

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

        # Persist the env-config row. Per FR-009a this commit MUST run
        # before any Task dispatch so a crash mid-fanout never reverts
        # the config.
        environment.config = config
        environment.capabilities = compute_environment_capabilities(environment)
        await uow.commit()

        validated_config = EnvironmentConfig.model_validate(config)

        # Enumerate non-tombstoned deployments in the environment. We
        # rely on the repository to return domain entities; the fanout
        # filters internal rows in-loop (FR-013) so the counters
        # accurately reflect "evaluated".
        deployments = await uow.deployments.find_all_by_environment(environment_id)

        counts = {
            "evaluated": 0,
            "dispatched": 0,
            "skipped_noop": 0,
            "skipped_restoring": 0,
            "dispatch_failed": 0,
        }
        for deployment in deployments:
            counts["evaluated"] += 1
            # Tombstoned + internal deployments are excluded per FR-012 /
            # FR-013. They are NOT counted toward ``skipped_noop`` —
            # ``skipped_noop`` is reserved for "deployment evaluated and
            # already at the new config".
            if deployment.deleted_at is not None or deployment.internal:
                continue
            if _deployment_already_at_config(deployment, validated_config):
                counts["skipped_noop"] += 1
                _emit_fanout_metric(environment_id, "skipped_noop")
                continue
            try:
                task = await redeploy_for_environment_update(deployment, uow)
            except Exception:  # noqa: BLE001 — broad catch is intentional for per-deployment isolation (FR-008)
                counts["dispatch_failed"] += 1
                logger.exception(
                    "env_config_fanout_dispatch_error environment_id={} deployment_id={}",
                    environment_id,
                    deployment.id,
                )
                _emit_fanout_metric(environment_id, "dispatch_failed")
                continue
            if task is None:
                # ``redeploy_for_environment_update`` returns None only for a
                # ``RESTORING`` deployment, which it deliberately leaves alone
                # (010 research D8). Counting that as ``dispatched`` would have
                # the audit line claim a redeploy that never happened — most
                # visibly for a clone's counterparts, which sit in ``RESTORING``
                # for the whole clone.
                counts["skipped_restoring"] += 1
                _emit_fanout_metric(environment_id, "skipped_restoring")
                continue
            counts["dispatched"] += 1
            _emit_fanout_metric(environment_id, "dispatched")

        # Persist the per-deployment writes accumulated across the
        # fanout loop. ``redeploy_for_environment_update`` calls
        # ``uow.deployments.save(...)`` (refreshes
        # ``active_application_instance_id``) and ``uow.tasks.save(...)``
        # (the dispatched Task row) but does NOT commit — the helper is
        # invoked from inside this enclosing UoW context, so the caller
        # owns the commit cadence. ``UnitOfWork.__aexit__`` only rolls
        # back on exception; on a clean exit it is a no-op. Without this
        # explicit commit the persisted env-config row (committed above
        # per FR-009a) is intact but every Task row and every
        # ``active_application_instance_id`` flip from the loop is
        # silently dropped — operators see "fanout dispatched=N" in the
        # audit log but no Task rows in storage. Sibling write paths
        # (``update_deployment``, ``update_deployment_version``,
        # ``delete_deployment``) all explicitly commit at the end of
        # their ``async with uow:`` block; this commit puts
        # ``update_environment`` back in line with them. (FR-006/FR-009.)
        await uow.commit()

        # One audit log entry per fanout invocation regardless of
        # dispatched count — FR-023. True environment-wide no-ops still
        # produce an entry with ``dispatched=0``.
        logger.info(
            "env_config_fanout_dispatched environment_id={} evaluated={} "
            "dispatched={} skipped_noop={} skipped_restoring={} "
            "dispatch_failed={}",
            environment_id,
            counts["evaluated"],
            counts["dispatched"],
            counts["skipped_noop"],
            counts["skipped_restoring"],
            counts["dispatch_failed"],
        )

        refreshed = await uow.environments.get(environment_id)
        assert refreshed is not None, "Environment should still exist after update"
        return refreshed


async def delete_environment(environment_id: UUID, uow: UnitOfWork) -> None:
    """Delete an environment, cascading through its environment backups first.

    ``environmentbackup.environment_id`` is a non-nullable FK, so a snapshot
    outliving its environment is not representable: the environment's snapshots
    (and their environment restores, constituent backups, and constituent
    restores) are deleted with the same cascade as deleting a snapshot directly
    before the environment row goes (spec FR-015). Skipping the cascade would
    turn every delete of an environment that has ever been snapshotted into a
    constraint violation surfacing as an opaque ``INTERNAL_ERROR``.

    Raises:
        EnvironmentNotFoundError: When ``environment_id`` does not exist.
    """
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

    cascaded = await delete_environment_backups_for_environment(environment_id, uow)

    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            # A concurrent delete won the race; the requested end state holds.
            return
        await uow.environments.delete(environment)
        await uow.commit()

    logger.info(
        "environment_deleted environment_id={} environment_backups_deleted={}",
        environment_id,
        cascaded,
    )
