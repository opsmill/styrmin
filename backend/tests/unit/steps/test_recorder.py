"""Step recorder against a real database (spec 019, T011 and T012)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from styrmin_backend.domain.models import (
    Step,
    StepError,
    StepEvent,
    StepKind,
    StepParent,
    StepStatus,
)
from styrmin_backend.services.exceptions import (
    BackupNotFoundError,
    RestoreNotFoundError,
    TaskNotFoundError,
)
from styrmin_backend.services.steps.exceptions import (
    InvalidStepRecordError,
    StepNotFoundError,
)
from styrmin_backend.services.steps.recorder import (
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    StepRecord,
    fail_open_flow_steps,
    fail_step,
    open_step,
    record_event,
    succeed_step,
    truncate_output,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps.conftest import Parents

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(seconds=30)


def _parents(parents: Parents) -> dict[str, StepParent]:
    return {
        "task": StepParent.of_task(parents.task.id),
        "backup": StepParent.of_backup(parents.backup_id),
        "restore": StepParent.of_restore(parents.restore_id),
    }


def _started(parent: StepParent, key: str = "hook:upgrade:core", **extra) -> StepRecord:
    return StepRecord(
        event=StepEvent.STARTED,
        task_id=parent.task_id,
        backup_id=parent.backup_id,
        restore_id=parent.restore_id,
        key=key,
        name=f"Run {key}",
        kind=StepKind.HOOK,
        occurred_at=T0,
        **extra,
    )


def _event(step: Step, event: StepEvent, at: datetime = T1, **extra) -> StepRecord:
    return StepRecord(event=event, step_id=step.id, occurred_at=at, **extra)


def _fields(step: Step) -> dict:
    # ``updated_on`` is set by the database on each write.
    return step.model_dump(exclude={"updated_on"})


async def _stored(uow: SqlModelUnitOfWork, step: Step) -> Step:
    stored = await uow.steps.get(step.id)
    assert stored is not None
    return stored


async def _seed(
    uow: SqlModelUnitOfWork,
    parent: StepParent,
    key: str,
    kind: StepKind,
    status: StepStatus,
) -> Step:
    started_at = None if status is StepStatus.PENDING else T0
    step = Step.create(parent, key, f"Step {key}", kind, status, started_at)
    if status in (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SUPERSEDED):
        step = step.model_copy(update={"ended_at": T0})
    if status is StepStatus.FAILED:
        step = step.model_copy(
            update={"errors": [StepError(attempt=1, message="first", occurred_at=T0)]}
        )
    await uow.steps.save(step)
    await uow.session.flush()
    return step


# Events -----------------------------------------------------------------


@pytest.mark.parametrize("parent_type", ["task", "backup", "restore"])
async def test_started_creates_a_running_step_for_each_parent(
    uow: SqlModelUnitOfWork, parents: Parents, parent_type: str
) -> None:
    parent = _parents(parents)[parent_type]

    step = await record_event(_started(parent), uow)

    assert step.parent == parent
    assert step.status is StepStatus.RUNNING
    assert step.kind is StepKind.HOOK
    assert step.name == "Run hook:upgrade:core"
    assert step.started_at == T0
    assert step.ended_at is None
    assert step.attempt_count == 1
    assert _fields(await _stored(uow, step)) == _fields(step)


async def test_started_twice_returns_the_running_step_unchanged(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    first = await record_event(_started(parent), uow)

    retried = _started(parent).model_copy(update={"occurred_at": T1, "name": "Other"})
    second = await record_event(retried, uow)

    assert second.id == first.id
    assert _fields(second) == _fields(first)


async def test_started_without_name_and_kind_starts_an_existing_step(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    pending = await _seed(
        uow, parent, "operator:ready", StepKind.OPERATOR_PHASE, StepStatus.PENDING
    )

    step = await record_event(
        StepRecord(
            event=StepEvent.STARTED,
            task_id=parents.task.id,
            key="operator:ready",
            occurred_at=T1,
        ),
        uow,
    )

    assert step.id == pending.id
    assert step.status is StepStatus.RUNNING
    assert step.started_at == T1
    assert step.attempt_count == 1


async def test_succeeded_ends_a_running_step(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await record_event(_started(StepParent.of_task(parents.task.id)), uow)

    succeeded = await record_event(_event(step, StepEvent.SUCCEEDED), uow)

    assert succeeded.status is StepStatus.SUCCEEDED
    assert succeeded.ended_at == T1
    assert succeeded.attempt_count == 1
    assert succeeded.errors == []
    assert _fields(await _stored(uow, step)) == _fields(succeeded)


async def test_failed_ends_a_running_step_with_its_error_and_output(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await record_event(_started(StepParent.of_task(parents.task.id)), uow)

    failed = await record_event(
        _event(step, StepEvent.FAILED, error="exit code 1", output="line\n"), uow
    )

    assert failed.status is StepStatus.FAILED
    assert failed.ended_at == T1
    assert failed.errors == [
        StepError(attempt=1, message="exit code 1", occurred_at=T1)
    ]
    assert failed.output == "line\n"
    assert failed.output_truncated is False
    assert _fields(await _stored(uow, step)) == _fields(failed)


async def test_events_address_a_step_by_parent_and_key(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_restore(parents.restore_id)
    step = await record_event(_started(parent, "restore:velero"), uow)

    failed = await record_event(
        StepRecord(
            event=StepEvent.FAILED,
            restore_id=parents.restore_id,
            key="restore:velero",
            error="FailedValidation",
            occurred_at=T1,
        ),
        uow,
    )

    assert failed.id == step.id
    assert failed.status is StepStatus.FAILED


async def test_output_is_stored_whatever_the_status(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(uow, parent, "command", StepKind.COMMAND, StepStatus.SUCCEEDED)

    stored = await record_event(
        _event(step, StepEvent.OUTPUT, output="done\n", output_truncated=True), uow
    )

    assert stored.status is StepStatus.SUCCEEDED
    assert stored.output == "done\n"
    assert stored.output_truncated is True
    assert _fields(await _stored(uow, step)) == _fields(stored)


async def test_event_without_time_uses_the_server_time(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    before = datetime.now(UTC)
    record = _started(StepParent.of_task(parents.task.id)).model_copy(
        update={"occurred_at": None}
    )

    step = await record_event(record, uow)

    assert step.started_at is not None
    assert before <= step.started_at <= datetime.now(UTC)


async def test_naive_event_time_is_read_as_utc(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    record = _started(StepParent.of_task(parents.task.id)).model_copy(
        update={"occurred_at": T0.replace(tzinfo=None)}
    )

    step = await record_event(record, uow)

    assert step.started_at == T0


async def test_end_time_is_never_before_the_start_time(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await record_event(_started(StepParent.of_task(parents.task.id)), uow)

    early = T0 - timedelta(seconds=5)
    failed = await record_event(_event(step, StepEvent.FAILED, early, error="x"), uow)

    assert failed.ended_at == T0


# State rules ------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "event"),
    [
        (StepStatus.SUPERSEDED, StepEvent.SUCCEEDED),
        (StepStatus.SUPERSEDED, StepEvent.FAILED),
        (StepStatus.SUPERSEDED, StepEvent.STARTED),
        (StepStatus.SUCCEEDED, StepEvent.SUCCEEDED),
        (StepStatus.SUCCEEDED, StepEvent.FAILED),
        (StepStatus.SUCCEEDED, StepEvent.STARTED),
        (StepStatus.FAILED, StepEvent.SUCCEEDED),
        (StepStatus.FAILED, StepEvent.FAILED),
        (StepStatus.FAILED, StepEvent.STARTED),
    ],
)
async def test_forbidden_transitions_of_a_flow_step_are_ignored(
    uow: SqlModelUnitOfWork,
    parents: Parents,
    status: StepStatus,
    event: StepEvent,
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(uow, parent, "hook:upgrade:core", StepKind.HOOK, status)
    before = await _stored(uow, step)

    result = await record_event(_event(step, event, error="late"), uow)

    assert _fields(result) == _fields(before)
    assert _fields(await _stored(uow, step)) == _fields(before)


async def test_pending_step_is_not_succeeded_before_it_starts(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(
        uow, parent, "operator:services", StepKind.OPERATOR_PHASE, StepStatus.PENDING
    )

    result = await succeed_step(step, T1, uow=uow)

    assert result.status is StepStatus.PENDING
    assert (await _stored(uow, step)).status is StepStatus.PENDING


async def test_pending_step_fails_with_its_first_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(
        uow, parent, "operator:services", StepKind.OPERATOR_PHASE, StepStatus.PENDING
    )

    failed = await fail_step(step, "Failed", T1, uow=uow)

    assert failed.status is StepStatus.FAILED
    assert failed.started_at == T1
    assert failed.ended_at == T1
    assert failed.attempt_count == 1
    assert failed.errors == [StepError(attempt=1, message="Failed", occurred_at=T1)]


async def test_failed_operator_step_starts_again_with_a_new_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(
        uow,
        parent,
        "operator:prerequisites",
        StepKind.OPERATOR_PHASE,
        StepStatus.FAILED,
    )

    restarted = await open_step(
        parent, step.key, step.name, StepKind.OPERATOR_PHASE, T1, uow=uow
    )
    failed_again = await fail_step(restarted, "quota exceeded", T1, uow=uow)

    assert restarted.status is StepStatus.RUNNING
    assert restarted.attempt_count == 2
    assert restarted.started_at == T0
    assert restarted.ended_at is None
    assert [error.attempt for error in failed_again.errors] == [1, 2]


async def test_failed_operator_step_succeeds_with_a_new_attempt(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(
        uow, parent, "operator:helmrelease", StepKind.OPERATOR_PHASE, StepStatus.FAILED
    )

    succeeded = await succeed_step(step, T1, uow=uow)

    assert succeeded.status is StepStatus.SUCCEEDED
    assert succeeded.attempt_count == 2
    assert succeeded.ended_at == T1
    assert len(succeeded.errors) == 1


async def test_primitives_read_the_stored_step_not_the_given_copy(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    step = await _seed(uow, parent, "plan", StepKind.PLAN, StepStatus.RUNNING)
    stale = step.model_copy()
    await succeed_step(step, T1, uow=uow)

    result = await fail_step(stale, "late", T1, uow=uow)

    assert result.status is StepStatus.SUCCEEDED
    assert result.errors == []


# Output limits ----------------------------------------------------------


def test_short_output_is_kept_whole() -> None:
    assert truncate_output("a\nb\n") == ("a\nb\n", False)
    assert truncate_output("") == ("", False)


def test_output_keeps_the_last_lines() -> None:
    lines = [f"line {number}" for number in range(MAX_OUTPUT_LINES + 50)]

    kept, truncated = truncate_output("\n".join(lines) + "\n")

    assert truncated is True
    assert kept == "\n".join(lines[-MAX_OUTPUT_LINES:]) + "\n"
    assert truncate_output("\n".join(lines[:MAX_OUTPUT_LINES]) + "\n")[1] is False


def test_output_keeps_the_last_bytes_from_a_full_line() -> None:
    line = "é" * 1000 + "\n"  # Two bytes per character, so 40 lines exceed 64 KiB.
    output = "".join(f"{number:03d}{line}" for number in range(40))

    kept, truncated = truncate_output(output)

    assert truncated is True
    assert len(kept.encode()) <= MAX_OUTPUT_BYTES
    assert kept.endswith("039" + line)
    first_line = kept.split("\n", 1)[0]
    assert first_line[:3].isdigit()
    assert first_line[3:] == "é" * 1000
    assert output.endswith(kept)


def test_output_cut_on_a_line_boundary_keeps_that_line() -> None:
    tail = "x" * (MAX_OUTPUT_BYTES - 1) + "\n"

    kept, truncated = truncate_output("head\n" + tail)

    assert truncated is True
    assert kept == tail


def test_one_long_line_keeps_its_end() -> None:
    kept, truncated = truncate_output("y" * (MAX_OUTPUT_BYTES + 10))

    assert truncated is True
    assert kept == "y" * MAX_OUTPUT_BYTES


async def test_recorded_output_is_cut_and_marked(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await record_event(_started(StepParent.of_task(parents.task.id)), uow)
    output = "".join(f"{number}\n" for number in range(MAX_OUTPUT_LINES + 1))

    stored = await record_event(_event(step, StepEvent.OUTPUT, output=output), uow)
    failed = await record_event(
        _event(step, StepEvent.FAILED, error="x", output=output), uow
    )

    for result in (stored, failed):
        assert result.output_truncated is True
        assert result.output is not None
        assert result.output.startswith("1\n")
        assert result.output.count("\n") == MAX_OUTPUT_LINES


# Closing open steps -----------------------------------------------------


async def test_fail_open_flow_steps_leaves_operator_and_final_steps(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    parent = StepParent.of_task(parents.task.id)
    running_hook = await _seed(uow, parent, "hook", StepKind.HOOK, StepStatus.RUNNING)
    pending_write = await _seed(
        uow, parent, "resource", StepKind.RESOURCE_WRITE, StepStatus.PENDING
    )
    done = await _seed(uow, parent, "plan", StepKind.PLAN, StepStatus.SUCCEEDED)
    operator_running = await _seed(
        uow, parent, "operator:a", StepKind.OPERATOR_PHASE, StepStatus.RUNNING
    )
    operator_pending = await _seed(
        uow, parent, "operator:b", StepKind.OPERATOR_PHASE, StepStatus.PENDING
    )
    other_task = await _seed(
        uow,
        StepParent.of_task(parents.other_task.id),
        "hook",
        StepKind.HOOK,
        StepStatus.RUNNING,
    )

    failed = await fail_open_flow_steps(parent, "Flow run crashed", T1, uow=uow)

    assert {step.id for step in failed} == {running_hook.id, pending_write.id}
    for step in failed:
        stored = await _stored(uow, step)
        assert stored.status is StepStatus.FAILED
        assert stored.errors[-1].message == "Flow run crashed"
        assert stored.ended_at == T1
    assert (await _stored(uow, done)).status is StepStatus.SUCCEEDED
    assert (await _stored(uow, operator_running)).status is StepStatus.RUNNING
    assert (await _stored(uow, operator_pending)).status is StepStatus.PENDING
    assert (await _stored(uow, other_task)).status is StepStatus.RUNNING


@pytest.mark.parametrize("parent_type", ["backup", "restore"])
async def test_fail_open_flow_steps_of_a_backup_or_restore(
    uow: SqlModelUnitOfWork, parents: Parents, parent_type: str
) -> None:
    parent = _parents(parents)[parent_type]
    kind = StepKind.BACKUP_COMPONENT if parent_type == "backup" else StepKind.RESTORE
    running = await _seed(uow, parent, "a", kind, StepStatus.RUNNING)
    pending = await _seed(uow, parent, "b", kind, StepStatus.PENDING)

    failed = await fail_open_flow_steps(parent, "USER flow failed", T1, uow=uow)

    assert {step.id for step in failed} == {running.id, pending.id}


# Validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(StepRecord(event=StepEvent.SUCCEEDED, key="plan"), id="no-parent"),
        pytest.param(
            StepRecord(event=StepEvent.SUCCEEDED, task_id=uuid4()), id="no-key"
        ),
        pytest.param(
            StepRecord(
                event=StepEvent.SUCCEEDED,
                task_id=uuid4(),
                backup_id=uuid4(),
                key="plan",
            ),
            id="two-parents",
        ),
        pytest.param(
            StepRecord(event=StepEvent.FAILED, step_id=uuid4()), id="failed-no-error"
        ),
        pytest.param(
            StepRecord(event=StepEvent.OUTPUT, step_id=uuid4()), id="output-no-output"
        ),
    ],
)
async def test_invalid_records_are_rejected(
    uow: SqlModelUnitOfWork, record: StepRecord
) -> None:
    with pytest.raises(InvalidStepRecordError):
        await record_event(record, uow)


async def test_started_without_name_and_kind_for_a_new_step_is_rejected(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    record = StepRecord(event=StepEvent.STARTED, task_id=parents.task.id, key="new")

    with pytest.raises(InvalidStepRecordError):
        await record_event(record, uow)

    assert (
        await uow.steps.find_by_key(StepParent.of_task(parents.task.id), "new") is None
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        {"task_id": "other_task"},
        {"backup_id": "backup"},
        {"key": "another-key"},
    ],
)
async def test_step_id_with_another_parent_or_key_is_rejected(
    uow: SqlModelUnitOfWork, parents: Parents, mismatch: dict[str, str]
) -> None:
    step = await record_event(_started(StepParent.of_task(parents.task.id)), uow)
    values = {
        "other_task": parents.other_task.id,
        "backup": parents.backup_id,
        "another-key": "another-key",
    }
    fields = {name: values[value] for name, value in mismatch.items()}

    with pytest.raises(InvalidStepRecordError):
        await record_event(_event(step, StepEvent.SUCCEEDED, **fields), uow)


async def test_step_id_with_its_own_parent_and_key_is_accepted(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    step = await record_event(_started(StepParent.of_task(parents.task.id)), uow)

    result = await record_event(
        _event(step, StepEvent.SUCCEEDED, task_id=parents.task.id, key=step.key), uow
    )

    assert result.status is StepStatus.SUCCEEDED


async def test_unknown_step_id_is_not_found(uow: SqlModelUnitOfWork) -> None:
    with pytest.raises(StepNotFoundError):
        await record_event(StepRecord(event=StepEvent.SUCCEEDED, step_id=uuid4()), uow)


async def test_unknown_key_is_not_found(
    uow: SqlModelUnitOfWork, parents: Parents
) -> None:
    record = StepRecord(event=StepEvent.SUCCEEDED, task_id=parents.task.id, key="none")

    with pytest.raises(StepNotFoundError):
        await record_event(record, uow)


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("task_id", TaskNotFoundError),
        ("backup_id", BackupNotFoundError),
        ("restore_id", RestoreNotFoundError),
    ],
)
async def test_unknown_parent_is_not_found(
    uow: SqlModelUnitOfWork, field: str, error: type[Exception]
) -> None:
    record = StepRecord(
        event=StepEvent.STARTED,
        key="plan",
        name="Plan the changes",
        kind=StepKind.PLAN,
        **{field: uuid4()},
    )

    with pytest.raises(error):
        await record_event(record, uow)
