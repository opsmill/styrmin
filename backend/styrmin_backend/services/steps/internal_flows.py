"""Step writes from INTERNAL flows, which call the recorder directly (spec 019, research D2).

Each write runs in its own transaction. A failed write logs a warning and
never fails the flow.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from uuid import UUID

from loguru import logger

from styrmin_backend.domain.models import StepParent
from styrmin_backend.domain.steps import StepDefinition
from styrmin_backend.services.exceptions import TaskNotFoundError
from styrmin_backend.services.steps.exceptions import StepNotFoundError
from styrmin_backend.services.steps.recorder import (
    fail_open_flow_steps,
    fail_step,
    open_step,
    succeed_step,
)
from styrmin_backend.services.unit_of_work import get_unit_of_work

#: The caller commits the task row after it dispatches the flow (research D2).
TASK_ROW_WAIT_SECONDS = 10.0
RETRY_INTERVAL_SECONDS = 0.5


async def _open(task_id: UUID, step: StepDefinition) -> UUID:
    async with get_unit_of_work() as uow:
        if await uow.tasks.find(task_id) is None:
            raise TaskNotFoundError(f"Task with id {task_id} not found.")
        opened = await open_step(
            StepParent.of_task(task_id),
            step.key,
            step.name,
            step.kind,
            datetime.now(UTC),
            uow=uow,
        )
        await uow.commit()
        return opened.id


async def open_task_step(
    task_id: UUID,
    step: StepDefinition,
    *,
    wait_seconds: float = TASK_ROW_WAIT_SECONDS,
) -> UUID | None:
    """Open a step of the task and return its id, or None when it was not written.

    Retries while the task row does not exist yet, for up to ``wait_seconds``.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return await _open(task_id, step)
        except TaskNotFoundError:
            if time.monotonic() >= deadline:
                logger.warning(
                    "Step {} not recorded: task {} not found after {} seconds",
                    step.key,
                    task_id,
                    wait_seconds,
                )
                return None
            await asyncio.sleep(RETRY_INTERVAL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - a step write never fails the flow
            logger.warning(
                "Could not record step {} of task {}: {}", step.key, task_id, exc
            )
            return None


async def end_step(step_id: UUID | None, error: str | None = None) -> None:
    """Succeed the step, or fail it with ``error``; does nothing without a step id."""
    if step_id is None:
        return
    try:
        async with get_unit_of_work() as uow:
            step = await uow.steps.get(step_id)
            if step is None:
                raise StepNotFoundError(f"Step with id {step_id} not found.")
            at = datetime.now(UTC)
            if error is None:
                await succeed_step(step, at, uow=uow)
            else:
                await fail_step(step, error, at, uow=uow)
            await uow.commit()
    except Exception as exc:  # noqa: BLE001 - a step write never fails the flow
        logger.warning("Could not end step {}: {}", step_id, exc)


async def fail_open_steps(parent: StepParent, message: str) -> None:
    """Fail the parent's pending and running flow-kind steps, after the flow that owns them died."""
    try:
        async with get_unit_of_work() as uow:
            await fail_open_flow_steps(parent, message, datetime.now(UTC), uow=uow)
            await uow.commit()
    except Exception as exc:  # noqa: BLE001 - a step write never fails the flow
        logger.warning("Could not fail the open steps of {}: {}", parent, exc)
