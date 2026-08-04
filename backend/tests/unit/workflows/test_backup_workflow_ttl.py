"""Unit tests for the retention wiring inside ``execute_backup_workflow``.

The backup flow is the only place where retention resolution, the ``ttl`` /
``ttl_source`` audit record, and Velero's ``expires_at`` are actually joined up
(016-backup-retention-ttl / FR-001, FR-002, FR-006). Everything below it is
already covered — ``services.backup.ttl`` by
``tests/unit/services/test_backup_ttl_resolution.py``, the merge semantics of
``metadata_updates`` by ``tests/unit/services/backup/test_backup_service.py`` —
so this module pins the wiring itself, which is what a refactor can silently
break:

* deleting ``metadata_updates=metadata_updates`` from the FAILED branch would
  leave every PartiallyFailed backup permanently without an expiry;
* moving the retention write after ``build_velero_backup`` would lose the audit
  record whenever the build or dispatch fails;
* reordering the BSL / cluster reads inside the best-effort config block would
  silently divert backups to the cluster-default storage location.

The flow's Python body is exercised through ``Flow.fn`` — the undecorated
coroutine — so no Prefect engine, work pool, or ephemeral API server is
involved. Every boundary the body touches (unit of work, backup service,
Velero builder, ``arun_deployment``, Prefect ``Variable``) is patched at the
module under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from prefect.client.schemas.objects import StateType

from styrmin_backend.services.backup.ttl import DEFAULT_BACKUP_TTL
from styrmin_backend.workflows.templates.backup import execute_backup_workflow

MODULE = "styrmin_backend.workflows.templates.backup"

# A Velero expiration timestamp as the CRD status reports it.
VELERO_EXPIRATION = "2026-09-02T12:00:00Z"


@dataclass
class WorkflowRun:
    """What the flow body did, as seen from its patched boundaries."""

    backup_id: UUID
    logger: MagicMock
    #: ``update_backup_status`` kwargs, in call order.
    status_calls: list[dict[str, Any]] = field(default_factory=list)
    #: ``build_velero_backup`` kwargs (the flow calls it at most once).
    velero_kwargs: dict[str, Any] | None = None
    #: Ordered trace of the two operations whose relative order is a contract.
    events: list[str] = field(default_factory=list)

    def metadata_writes(self) -> list[dict[str, Any]]:
        return [
            call["metadata_updates"]
            for call in self.status_calls
            if call.get("metadata_updates")
        ]

    def warnings(self) -> str:
        return "\n".join(
            str(call.args[0]) for call in self.logger.warning.call_args_list
        )


async def _run_backup_workflow(
    *,
    deployment_config: dict[str, Any] | None = None,
    environment_config: dict[str, Any] | None = None,
    cluster_config: dict[str, Any] | None = None,
    deployment_read_error: Exception | None = None,
    environment_read_error: Exception | None = None,
    cluster_read_error: Exception | None = None,
    deployment_missing: bool = False,
    environment_missing: bool = False,
    cluster_missing: bool = False,
    backup_storage_location_name: str | None = None,
    velero_phase: str = "Completed",
    velero_expiration: str | None = VELERO_EXPIRATION,
) -> WorkflowRun:
    """Drive the flow body once with every boundary faked.

    Args:
        deployment_config: Persisted deployment ``config``.
        environment_config: Persisted environment ``config``.
        cluster_config: Persisted cluster ``config``.
        deployment_read_error: Raised by the deployment lookup, to simulate a
            config read that fails before any scope is known.
        environment_read_error: Raised by the environment lookup, to simulate a
            *partial* read that already yielded the deployment scope.
        cluster_read_error: Raised by the cluster lookup, the read the feature
            added to the pre-existing best-effort block.
        deployment_missing: The deployment lookup returns ``None`` — a row that
            is simply not there, which raises nothing. Distinct from
            ``deployment_read_error`` and the case the flow used to swallow.
        environment_missing: The environment lookup returns ``None``.
        cluster_missing: The cluster lookup returns ``None``.
        backup_storage_location_name: Name of the environment's assigned BSL,
            or None for "no BSL assigned".
        velero_phase: ``status.phase`` the USER flow reports back.
        velero_expiration: ``status.expiration`` the USER flow reports back.

    Returns:
        A :class:`WorkflowRun` recording what the body did.
    """
    backup_uuid = uuid4()
    deployment_uuid = uuid4()
    run = WorkflowRun(backup_id=backup_uuid, logger=MagicMock())

    backup = MagicMock()
    backup.name = "styrmin-backup-1"
    backup.instance_id = uuid4()
    backup.component_statuses = None
    backup.metadata_ = {"timeout": 1800}

    deployment = MagicMock()
    deployment.config = deployment_config
    deployment.environment_id = uuid4()

    environment = MagicMock()
    environment.config = environment_config
    environment.cluster_id = uuid4()
    if backup_storage_location_name is None:
        environment.backup_storage_location = None
    else:
        environment.backup_storage_location = MagicMock()
        environment.backup_storage_location.name = backup_storage_location_name

    cluster = MagicMock()
    cluster.config = cluster_config

    uow = MagicMock()
    uow.deployments.find = AsyncMock(
        return_value=None if deployment_missing else deployment,
        side_effect=deployment_read_error,
    )
    uow.environments.get = AsyncMock(
        return_value=None if environment_missing else environment,
        side_effect=environment_read_error,
    )
    uow.clusters.get = AsyncMock(
        return_value=None if cluster_missing else cluster,
        side_effect=cluster_read_error,
    )

    def _record_status(**kwargs: Any) -> None:
        run.status_calls.append(kwargs)
        if kwargs.get("metadata_updates"):
            run.events.append("metadata_write")

    def _record_build(**kwargs: Any) -> MagicMock:
        run.velero_kwargs = kwargs
        run.events.append("build_velero_backup")
        built = MagicMock()
        built.render.return_value = {"kind": "Backup"}
        return built

    flow_run = MagicMock()
    flow_run.id = uuid4()
    flow_run.state = MagicMock()
    flow_run.state.type = StateType.COMPLETED
    flow_run.state.is_failed.return_value = False

    velero_result = {
        "status": {
            "phase": velero_phase,
            "failureReason": "velero said no",
            "backupItemOperationsCompleted": 7,
            "expiration": velero_expiration,
        }
    }

    variable = MagicMock()
    variable.get = AsyncMock(return_value=velero_result)
    variable.unset = AsyncMock()

    with (
        patch(f"{MODULE}.config", MagicMock()),
        patch(f"{MODULE}.get_run_logger", return_value=run.logger),
        patch(f"{MODULE}.get_unit_of_work", AsyncMock(return_value=uow)),
        patch(f"{MODULE}.get_backup", AsyncMock(return_value=backup)),
        patch(f"{MODULE}.update_backup_status", AsyncMock(side_effect=_record_status)),
        patch(f"{MODULE}.build_velero_backup", MagicMock(side_effect=_record_build)),
        patch(f"{MODULE}.arun_deployment", AsyncMock(return_value=flow_run)),
        patch(f"{MODULE}.Variable", variable),
    ):
        await execute_backup_workflow.fn(
            backup_id=str(backup_uuid),
            deployment_id=str(deployment_uuid),
        )

    return run


# ---------------------------------------------------------------------------
# Resolution is wired from every scope (FR-001, FR-002)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scopes", "expected_ttl", "expected_source"),
    [
        pytest.param(
            {
                "deployment_config": {"backup_ttl": "8760h"},
                "environment_config": {"backup_ttl": "2160h"},
                "cluster_config": {"backup_ttl": "720h"},
            },
            "8760h",
            "deployment",
            id="deployment-scope-wins",
        ),
        pytest.param(
            {
                "environment_config": {"backup_ttl": "2160h"},
                "cluster_config": {"backup_ttl": "720h"},
            },
            "2160h",
            "environment",
            id="environment-scope",
        ),
        pytest.param(
            {"cluster_config": {"backup_ttl": "4320h"}},
            "4320h",
            "cluster",
            id="cluster-scope",
        ),
        pytest.param({}, DEFAULT_BACKUP_TTL, "default", id="built-in-default"),
    ],
)
async def test_resolved_ttl_reaches_velero_and_the_audit_record(
    scopes: dict[str, Any], expected_ttl: str, expected_source: str
) -> None:
    """Each scope's value reaches ``spec.ttl`` *and* the backup's metadata.

    The workflow reads all three scopes' config and hands the resolved value to
    ``build_velero_backup(ttl=...)``; the same value plus its provenance is
    recorded on the backup. Both halves are asserted together because either
    one alone can regress silently.
    """
    run = await _run_backup_workflow(**scopes)

    assert run.velero_kwargs is not None
    assert run.velero_kwargs["ttl"] == expected_ttl
    assert {"ttl": expected_ttl, "ttl_source": expected_source} in run.metadata_writes()


@pytest.mark.anyio
async def test_ttl_is_recorded_before_the_velero_object_is_built() -> None:
    """The audit record must survive a failure in the build or dispatch.

    Recording after the build would lose ``ttl`` / ``ttl_source`` for exactly
    the backups whose failure an operator most wants to explain.
    """
    run = await _run_backup_workflow(environment_config={"backup_ttl": "2160h"})

    assert run.events.index("metadata_write") < run.events.index(
        "build_velero_backup"
    ), f"expected the retention write before the Velero build, got {run.events}"


# ---------------------------------------------------------------------------
# expires_at on both terminal branches (FR-006)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "velero_phase",
    ["Completed", "PartiallyFailed"],
    ids=["completed-branch", "partially-failed-branch"],
)
async def test_expiration_is_recorded_on_both_terminal_branches(
    velero_phase: str,
) -> None:
    """A stored backup records its expiry whichever branch it lands on.

    ``PartiallyFailed`` is stored, does expire, and this workflow folds it into
    ``BackupStatus.FAILED`` — so the FAILED branch has to carry
    ``metadata_updates`` too. Dropping it there leaves every partially-failed
    backup permanently without an expiry in the UI and CLI.
    """
    run = await _run_backup_workflow(
        environment_config={"backup_ttl": "2160h"}, velero_phase=velero_phase
    )

    assert {"expires_at": VELERO_EXPIRATION} in run.metadata_writes()


@pytest.mark.anyio
async def test_failed_backup_without_an_expiration_records_nothing_quietly() -> None:
    """A genuinely Failed backup stored nothing, so it has no expiry to record.

    This is the expected shape of the FAILED branch, so it must not warn — the
    noise would fire on every real failure.
    """
    run = await _run_backup_workflow(velero_phase="Failed", velero_expiration=None)

    assert run.metadata_writes() == [
        {"ttl": DEFAULT_BACKUP_TTL, "ttl_source": "default"}
    ]
    assert "expiration" not in run.warnings()


@pytest.mark.anyio
async def test_completed_backup_without_an_expiration_warns() -> None:
    """A Completed backup with no expiration silently loses FR-006's record.

    Velero always dates a backup it stored, so this combination means something
    went wrong upstream and the UI will show no expiry for a backup that does
    expire. Say so rather than dropping it.
    """
    run = await _run_backup_workflow(velero_phase="Completed", velero_expiration=None)

    warnings = run.warnings()
    assert "expiration" in warnings
    assert str(run.backup_id) in warnings


# ---------------------------------------------------------------------------
# Config-read failures (research §R3: resolution stays outside the try)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_total_config_read_failure_falls_back_to_the_default_and_warns() -> None:
    """A read that fails before any scope is known applies the built-in default.

    The BSL block swallows every exception, so the failure is invisible to the
    rest of the flow; resolution deliberately runs *outside* it, and the
    warning is the only signal that a configured policy may have been missed.
    """
    run = await _run_backup_workflow(
        environment_config={"backup_ttl": "2160h"},
        deployment_read_error=RuntimeError("pool timeout"),
    )

    assert run.velero_kwargs is not None
    assert run.velero_kwargs["ttl"] == DEFAULT_BACKUP_TTL
    assert {
        "ttl": DEFAULT_BACKUP_TTL,
        "ttl_source": "default",
    } in run.metadata_writes()
    assert DEFAULT_BACKUP_TTL in run.warnings()


@pytest.mark.anyio
async def test_partial_config_read_does_not_claim_the_default_was_applied() -> None:
    """A read that failed *after* yielding a scope value keeps that value.

    The deployment scope was already read when the environment lookup threw, so
    resolution correctly returns it. The warning must say so instead of
    claiming the built-in default was applied — which the INFO line
    immediately afterwards would contradict.
    """
    run = await _run_backup_workflow(
        deployment_config={"backup_ttl": "8760h"},
        environment_read_error=RuntimeError("connection reset"),
    )

    assert run.velero_kwargs is not None
    assert run.velero_kwargs["ttl"] == "8760h"
    assert {"ttl": "8760h", "ttl_source": "deployment"} in run.metadata_writes()

    warnings = run.warnings()
    assert "8760h" in warnings
    assert "deployment" in warnings
    assert DEFAULT_BACKUP_TTL not in warnings, (
        "a partial read that still resolved a scope value must not claim the "
        f"built-in default was applied: {warnings}"
    )


# ---------------------------------------------------------------------------
# The cluster read the feature added must not cost us the environment's BSL
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cluster_read_failure_keeps_the_environment_bsl() -> None:
    """A failing cluster read must not divert the backup to the default BSL.

    The cluster lookup exists only to resolve cluster-scope retention, and it
    sits inside a block that swallows everything. If it runs before the BSL is
    assigned, its failure silently sends the backup to the cluster-default
    storage location — a regression in behaviour that predates this feature.
    """
    run = await _run_backup_workflow(
        environment_config={"backup_ttl": "2160h"},
        cluster_config={"backup_ttl": "720h"},
        cluster_read_error=RuntimeError("pool timeout"),
        backup_storage_location_name="primary",
    )

    assert run.velero_kwargs is not None
    assert run.velero_kwargs["storage_location"] == "styrmin-bsl-primary"
    # The environment scope was read before the failure, so retention still
    # comes from it rather than the built-in default.
    assert run.velero_kwargs["ttl"] == "2160h"


# ---------------------------------------------------------------------------
# A missing row is not an exception — and must not read as "no policy set"
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("missing", "scopes", "expected_ttl", "expected_source"),
    [
        pytest.param(
            {"deployment_missing": True},
            {"environment_config": {"backup_ttl": "2160h"}},
            DEFAULT_BACKUP_TTL,
            "default",
            id="deployment-row-gone",
        ),
        pytest.param(
            {"environment_missing": True},
            {
                "deployment_config": {"backup_ttl": "8760h"},
                "environment_config": {"backup_ttl": "2160h"},
            },
            "8760h",
            "deployment",
            id="environment-row-gone",
        ),
        pytest.param(
            {"cluster_missing": True},
            {
                "environment_config": {"backup_ttl": "2160h"},
                "cluster_config": {"backup_ttl": "720h"},
            },
            "2160h",
            "environment",
            id="cluster-row-gone",
        ),
    ],
)
async def test_a_missing_row_warns_and_names_the_lookup(
    missing: dict[str, Any],
    scopes: dict[str, Any],
    expected_ttl: str,
    expected_source: str,
) -> None:
    """An empty lookup raises nothing, so it needs its own signal.

    All three lookups are guarded by a truthiness check, so a deleted row leaves
    ``config_read_failed`` False, every scope None, and only the routine INFO
    line — which reads exactly like a deployment that never set a policy. The
    concrete case: a deployment row deleted between backup-record creation and
    workflow start silently discards the environment's configured retention.

    Each lookup reaches the next one through its own result, so the warning has
    to name *which* lookup came back empty for the operator to know how much of
    the chain was invisible.
    """
    scope_name = next(iter(missing)).removesuffix("_missing")
    run = await _run_backup_workflow(**missing, **scopes)

    warnings = run.warnings()
    assert scope_name in warnings, warnings
    assert str(run.backup_id) in warnings, warnings
    assert "backup_ttl" in warnings, warnings

    # Not fatal: the backup still runs, with whatever retention was readable.
    assert run.velero_kwargs is not None
    assert run.velero_kwargs["ttl"] == expected_ttl
    assert {
        "ttl": expected_ttl,
        "ttl_source": expected_source,
    } in run.metadata_writes()


@pytest.mark.anyio
async def test_a_genuinely_unconfigured_deployment_does_not_warn() -> None:
    """The other half of "distinguishable": no policy anywhere is not a problem.

    Every row is present and none carries ``backup_ttl``, so the built-in
    default is the correct, expected outcome. Warning here would fire on every
    backup of every deployment that never set a retention policy — which is
    most of them — and drown the signal the test above depends on.
    """
    run = await _run_backup_workflow()

    assert run.velero_kwargs is not None
    assert run.velero_kwargs["ttl"] == DEFAULT_BACKUP_TTL
    assert {
        "ttl": DEFAULT_BACKUP_TTL,
        "ttl_source": "default",
    } in run.metadata_writes()
    assert run.logger.warning.call_args_list == [], run.warnings()
