"""Unit tests for the failure handler of ``execute_restore_workflow``.

The restore flow marks its record IN_PROGRESS, then runs the whole Velero
round-trip — two DB reads, a CRD build, a dispatched USER flow, a Prefect
Variable read — before writing the terminal status. If the restore row is
deleted anywhere in that window, the terminal write raises
``RestoreNotFoundError`` and lands in the flow's ``except`` handler, which
*also* calls ``update_restore_status``. That call raises too, from inside the
handler, so without the guard what escapes the flow is the handler's own
bookkeeping error and the original cause is gone.

This is the same hazard ``execute_backup_workflow`` carries with
``BackupNotFoundError`` (pinned by
``test_backup_workflow_ttl.py::test_a_record_deleted_mid_flight_propagates_the_original_failure``),
and it is fixed the same way — so the two are kept deliberately alike.

The restore handler has one extra guarantee the backup handler does not: it
writes the *deployment* status after the restore status. The deployment outlives
the restore record, so that write must stay reachable when the restore write
fails — otherwise a vanished restore record leaves the deployment stuck in
RESTORING indefinitely.

The flow's Python body is exercised through ``Flow.fn`` — the undecorated
coroutine — so no Prefect engine, work pool, or ephemeral API server is
involved. Every boundary the body touches is patched at the module under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from prefect.client.schemas.objects import StateType

from styrmin_backend.services.exceptions import RestoreNotFoundError
from styrmin_backend.workflows.templates.backup import execute_restore_workflow

MODULE = "styrmin_backend.workflows.templates.backup"

#: ``get_restore`` is imported inside the flow body, so it is patched where it
#: is defined rather than on the module under test.
SERVICE_MODULE = "styrmin_backend.services.backup.service"


@dataclass
class RestoreRun:
    """What the flow body did, as seen from its patched boundaries."""

    restore_id: UUID
    deployment_id: UUID
    logger: MagicMock
    #: ``update_restore_status`` kwargs, in call order.
    status_calls: list[dict[str, Any]] = field(default_factory=list)
    #: ``build_velero_restore`` kwargs (the flow calls it at most once).
    velero_kwargs: dict[str, Any] | None = None
    #: ``arun_deployment`` parameters handed to the USER flow.
    dispatch_parameters: dict[str, Any] | None = None
    #: ``_set_deployment_status_failed`` kwargs, in call order.
    deployment_failed_calls: list[dict[str, Any]] = field(default_factory=list)
    #: ``_set_deployment_status_running`` kwargs, in call order.
    deployment_running_calls: list[dict[str, Any]] = field(default_factory=list)
    #: What the flow body raised, when the caller asked for it to be captured.
    raised: BaseException | None = None

    def warnings(self) -> str:
        return "\n".join(
            str(call.args[0]) for call in self.logger.warning.call_args_list
        )


async def _run_restore_workflow(
    *,
    velero_phase: str = "Completed",
    recovered: bool = True,
    record_deleted_after_status_writes: int | None = None,
    capture_exception: bool = False,
    source_deployment_id: UUID | None = None,
    target_instance_id: UUID | None = None,
) -> RestoreRun:
    """Drive the flow body once with every boundary faked.

    Args:
        velero_phase: ``status.phase`` the USER flow reports back.
        recovered: Whether the post-Velero reapply reports success.
        record_deleted_after_status_writes: Simulate the restore row being
            deleted after this many successful ``update_restore_status`` calls —
            every call from then on raises ``RestoreNotFoundError``, including
            the one the flow's own ``except`` handler makes. Each raised error
            names its call index so a test can tell which write's failure
            propagated.
        capture_exception: Store what the body raised on ``run.raised`` instead
            of letting it escape, so the run record stays inspectable.
        source_deployment_id: Drive the flow as a **cross-target** restore
            (environment clone) whose backup came from this deployment while
            ``deployment_id`` names the counterpart (research D2.2). ``None``
            drives the shipped in-place path.
        target_instance_id: The counterpart instance recorded on the restore
            row, used for the cross-target Restore CR label (research D2.6).

    Returns:
        A :class:`RestoreRun` recording what the body did.
    """
    restore_uuid = uuid4()
    backup_uuid = uuid4()
    deployment_uuid = uuid4()
    run = RestoreRun(
        restore_id=restore_uuid,
        deployment_id=deployment_uuid,
        logger=MagicMock(),
    )

    backup = MagicMock()
    backup.name = "styrmin-backup-1"
    backup.instance_id = uuid4()
    backup.component_statuses = None

    restore = MagicMock()
    restore.name = "styrmin-restore-1"
    restore.metadata_ = {"timeout": 1800}
    restore.target_instance_id = target_instance_id

    def _record_status(**kwargs: Any) -> None:
        run.status_calls.append(kwargs)
        if (
            record_deleted_after_status_writes is not None
            and len(run.status_calls) > record_deleted_after_status_writes
        ):
            raise RestoreNotFoundError(
                f"Restore {restore_uuid} not found (status write "
                f"#{len(run.status_calls)})"
            )

    def _record_build(**kwargs: Any) -> MagicMock:
        run.velero_kwargs = kwargs
        built = MagicMock()
        built.render.return_value = {"kind": "Restore"}
        return built

    async def _record_deployment_failed(**kwargs: Any) -> None:
        run.deployment_failed_calls.append(kwargs)

    async def _record_deployment_running(**kwargs: Any) -> None:
        run.deployment_running_calls.append(kwargs)

    counterpart_crd_body = {
        "metadata": {"name": f"styrmin-{deployment_uuid}"},
        "spec": {"deploymentId": str(deployment_uuid)},
    }

    async def _record_dispatch(**kwargs: Any) -> MagicMock:
        run.dispatch_parameters = kwargs.get("parameters")
        return flow_run

    flow_run = MagicMock()
    flow_run.id = uuid4()
    flow_run.state = MagicMock()
    flow_run.state.type = StateType.COMPLETED
    flow_run.state.is_failed.return_value = False

    velero_result = {
        "status": {"phase": velero_phase, "failureReason": "velero said no"},
        "recovery": {"recovered": recovered, "error": "reapply said no"},
    }

    variable = MagicMock()
    variable.get = AsyncMock(return_value=velero_result)
    variable.unset = AsyncMock()

    with (
        patch(f"{MODULE}.config", MagicMock()),
        patch(f"{MODULE}.get_run_logger", return_value=run.logger),
        patch(f"{MODULE}.get_unit_of_work", AsyncMock(return_value=MagicMock())),
        patch(f"{MODULE}.get_backup", AsyncMock(return_value=backup)),
        patch(f"{SERVICE_MODULE}.get_restore", AsyncMock(return_value=restore)),
        patch(f"{MODULE}.update_restore_status", AsyncMock(side_effect=_record_status)),
        patch(f"{MODULE}.build_velero_restore", MagicMock(side_effect=_record_build)),
        patch(f"{MODULE}.arun_deployment", AsyncMock(side_effect=_record_dispatch)),
        patch(f"{MODULE}.Variable", variable),
        patch(
            f"{MODULE}._set_deployment_status_running",
            AsyncMock(side_effect=_record_deployment_running),
        ),
        patch(
            f"{MODULE}._set_deployment_status_failed",
            AsyncMock(side_effect=_record_deployment_failed),
        ),
        patch(
            f"{MODULE}._build_counterpart_crd_body",
            AsyncMock(return_value=counterpart_crd_body),
        ),
    ):
        if capture_exception:
            try:
                await execute_restore_workflow.fn(
                    restore_id=str(restore_uuid),
                    backup_id=str(backup_uuid),
                    deployment_id=str(deployment_uuid),
                    target_namespace=f"styrmin-{deployment_uuid}",
                    source_deployment_id=(
                        str(source_deployment_id)
                        if source_deployment_id is not None
                        else None
                    ),
                )
            except BaseException as exc:  # noqa: BLE001 - the test inspects it
                run.raised = exc
        else:
            await execute_restore_workflow.fn(
                restore_id=str(restore_uuid),
                backup_id=str(backup_uuid),
                deployment_id=str(deployment_uuid),
                target_namespace=f"styrmin-{deployment_uuid}",
                source_deployment_id=(
                    str(source_deployment_id)
                    if source_deployment_id is not None
                    else None
                ),
            )

    return run


# ---------------------------------------------------------------------------
# The harness itself must reach the terminal write on the happy path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_successful_restore_writes_in_progress_then_completed() -> None:
    """Guards the fault-injection tests below from becoming vacuous.

    Both of them count ``update_restore_status`` calls, which only means
    anything if an unperturbed run reaches the *second* write. If a future
    boundary change made the body bail out early, the counts would still hold
    while testing nothing.
    """
    run = await _run_restore_workflow()

    assert len(run.status_calls) == 2, run.status_calls
    assert run.velero_kwargs is not None
    assert run.deployment_failed_calls == []


# ---------------------------------------------------------------------------
# A record deleted mid-flight must not lose the real failure
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_record_deleted_mid_flight_propagates_the_original_failure() -> None:
    """The handler's own status write must not replace the cause of the failure.

    The terminal ``update_restore_status`` happens after the entire Velero
    round-trip, so there is a long window in which the restore row can be
    deleted. When it is, that write raises ``RestoreNotFoundError`` and lands in
    the flow's ``except`` handler, which *also* calls
    ``update_restore_status``. That call raises too, from inside the handler, so
    what escapes the flow is the handler's bookkeeping error and the original
    cause is gone.

    Here the row disappears after the first write, so write #2 (terminal) and
    write #3 (the handler's FAILED) both raise. What must propagate is #2.
    """
    run = await _run_restore_workflow(
        record_deleted_after_status_writes=1,
        capture_exception=True,
    )

    assert isinstance(run.raised, RestoreNotFoundError), run.raised
    assert "#2" in str(run.raised), (
        f"the handler's own write failure replaced the original cause: {run.raised!r}"
    )

    # The handler still tried, and said why it could not report the failure.
    assert len(run.status_calls) == 3
    assert "no longer exists" in run.warnings(), run.warnings()


@pytest.mark.anyio
async def test_a_deleted_restore_record_still_marks_the_deployment_failed() -> None:
    """The deployment write sits after the restore write and must stay reachable.

    A restore leaves its deployment in RESTORING; only the handler moves it out
    of that state on failure. The deployment outlives the restore record, so a
    restore row deleted mid-flight must not cost the deployment its terminal
    status — an escaping ``RestoreNotFoundError`` from the handler's first write
    would skip this one and leave the deployment stuck in RESTORING for good.
    """
    run = await _run_restore_workflow(
        record_deleted_after_status_writes=1,
        capture_exception=True,
    )

    assert len(run.deployment_failed_calls) == 1, run.deployment_failed_calls
    call = run.deployment_failed_calls[0]
    assert call["deployment_id"] == run.deployment_id
    # And it reports the original cause, not the handler's bookkeeping failure.
    assert "#2" in call["error_message"], call


# ---------------------------------------------------------------------------
# Source identity vs status-write target (research D2.2 / D2.3 / D2.6)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_in_place_restore_dispatch_is_unchanged() -> None:
    """Omitting ``source_deployment_id`` reproduces the shipped in-place call.

    Source namespace, restored CR name and target namespace all collapse to the
    same string, no counterpart CR body is built, and the Restore CR keeps the
    source instance label.
    """
    run = await _run_restore_workflow()

    assert run.velero_kwargs is not None
    namespace = f"styrmin-{run.deployment_id}"
    assert run.velero_kwargs["source_namespace"] == namespace
    assert run.velero_kwargs["target_namespace"] == namespace
    assert run.velero_kwargs["target_instance_id"] is None

    assert run.dispatch_parameters is not None
    assert run.dispatch_parameters["restored_crd_name"] == namespace
    assert run.dispatch_parameters["counterpart_crd_body"] is None

    assert [call["deployment_id"] for call in run.deployment_running_calls] == [
        run.deployment_id
    ]


@pytest.mark.anyio
async def test_cross_target_restore_splits_source_from_status_target() -> None:
    """A clone restore reads the *source* namespace and writes the counterpart.

    Velero's ``namespaceMapping`` preserves object names, so the recreated CR
    is still ``styrmin-<source_deployment_id>`` even though it now lives in the
    counterpart's namespace — the flow must hand that name to the USER flow
    rather than assuming ``crd_name == target_namespace`` (research D2.3).
    """
    source_deployment_id = uuid4()
    counterpart_instance_id = uuid4()

    run = await _run_restore_workflow(
        source_deployment_id=source_deployment_id,
        target_instance_id=counterpart_instance_id,
    )

    source_namespace = f"styrmin-{source_deployment_id}"
    counterpart_namespace = f"styrmin-{run.deployment_id}"
    assert run.velero_kwargs is not None
    assert run.velero_kwargs["source_namespace"] == source_namespace
    assert run.velero_kwargs["target_namespace"] == counterpart_namespace
    # research D2.6 — the Restore CR is attributed to the counterpart instance.
    assert run.velero_kwargs["target_instance_id"] == str(counterpart_instance_id)

    assert run.dispatch_parameters is not None
    assert run.dispatch_parameters["restored_crd_name"] == source_namespace
    # research D2.4 — the counterpart's own CR body rides along to the recovery.
    assert run.dispatch_parameters["counterpart_crd_body"] == {
        "metadata": {"name": counterpart_namespace},
        "spec": {"deploymentId": str(run.deployment_id)},
    }

    # The status-write target is the counterpart, never the source (SC-002).
    assert [call["deployment_id"] for call in run.deployment_running_calls] == [
        run.deployment_id
    ]
    assert run.deployment_failed_calls == []


@pytest.mark.anyio
async def test_cross_target_failure_marks_the_counterpart_not_the_source() -> None:
    """A failed clone restore must not push the source deployment to FAILED."""
    source_deployment_id = uuid4()

    run = await _run_restore_workflow(
        velero_phase="Failed",
        recovered=False,
        source_deployment_id=source_deployment_id,
    )

    assert [call["deployment_id"] for call in run.deployment_failed_calls] == [
        run.deployment_id
    ]
    assert run.deployment_running_calls == []
