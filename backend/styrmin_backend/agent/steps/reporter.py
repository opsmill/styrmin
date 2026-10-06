"""Record the steps of a USER flow or a driver action through ``recordStep``.

See specs/019-task-steps/contracts/flow-step-reporter.md. The reporter calls the
API with the action token (ADR-059) for the step parent named in the Job's
environment (research D3). A failed write logs a warning and never fails the
work (research D2).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from loguru import logger
from prefect.states import format_exception
from pydantic import ValidationError

from styrmin_backend import config
from styrmin_backend.agent.steps.queries import load_query
from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from styrmin_backend.domain.models import StepEvent, StepKind, StepParent

_RECORD_STEP = load_query("record_step")
#: Bounds how long the work waits on one step write.
REQUEST_TIMEOUT_SECONDS = 10.0


class StepReportError(Exception):
    """The API answered a step write with GraphQL errors."""


@dataclass
class ReportedStep:
    """A step opened by ``StepReporter.step``."""

    key: str
    #: The server's id for the step; None in no-op mode or when the write failed.
    id: UUID | None = None


class StepReporter:
    """Writes step events for one parent; a no-op without a token or a parent."""

    def __init__(
        self,
        token: str | None,
        parent: StepParent | None,
        step_id: UUID | None = None,
    ) -> None:
        self._token = token
        self._parent = parent
        #: The hook step that runs this driver action (``STYRMIN_STEP_ID``).
        self.step_id = step_id

    @classmethod
    def from_env(cls) -> StepReporter:
        """Build the reporter from ``STYRMIN_TOKEN``, the parent variables and ``STYRMIN_STEP_ID``."""
        token = os.environ.get(API_TOKEN_ENV) or None
        parent = _parent_from_env()
        if token is None or parent is None:
            logger.info(
                "Step reporting is off: the Job has no action token or step parent"
            )
        return cls(token, parent, _uuid_from_env(STEP_ID_ENV))

    @property
    def enabled(self) -> bool:
        return self._token is not None and self._parent is not None

    @asynccontextmanager
    async def step(
        self, key: str, name: str, kind: StepKind
    ) -> AsyncIterator[ReportedStep]:
        """Record the block as a step: started, then succeeded, or failed and re-raised."""
        step = ReportedStep(key=key)
        step.id = await self._send(
            StepEvent.STARTED, key=key, fields={"name": name, "kind": kind.name}
        )
        try:
            yield step
        except Exception as exc:
            await self._send(
                StepEvent.FAILED,
                key=key,
                step_id=step.id,
                fields={"error": format_exception(exc)},
            )
            raise
        await self._send(StepEvent.SUCCEEDED, key=key, step_id=step.id)

    async def record_output(
        self, step_id: UUID | None, output: str, truncated: bool
    ) -> None:
        """Store the end of a command's output on a step (``OUTPUT``)."""
        if step_id is None:
            logger.info("Command output not recorded: no step to record it on")
            return
        await self._send(
            StepEvent.OUTPUT,
            step_id=step_id,
            fields={"output": output, "outputTruncated": truncated},
        )

    async def fail_step(
        self,
        key: str,
        error: str,
        output: str | None = None,
        *,
        output_truncated: bool = False,
    ) -> None:
        """Record ``FAILED`` for a step of this parent that was opened earlier."""
        fields: dict[str, Any] = {"error": error}
        if output is not None:
            fields |= {"output": output, "outputTruncated": output_truncated}
        await self._send(StepEvent.FAILED, key=key, fields=fields)

    async def _send(
        self,
        event: StepEvent,
        *,
        key: str | None = None,
        step_id: UUID | None = None,
        fields: dict[str, Any] | None = None,
    ) -> UUID | None:
        """Send one event, addressed by step id when known, else by parent and key."""
        if self._token is None or self._parent is None:
            return None
        address = (
            {"stepId": str(step_id)}
            if step_id is not None
            else {**_parent_variables(self._parent), "key": key}
        )
        record = {
            **address,
            "event": event.name,
            "occurredAt": datetime.now(UTC).isoformat(),
            **(fields or {}),
        }
        try:
            return await self._post(record)
        except Exception as exc:  # noqa: BLE001 - a step write never fails the work (D2)
            logger.warning(
                "Could not record {} for step {}: {}", event.name, step_id or key, exc
            )
            return None

    async def _post(self, record: dict[str, Any]) -> UUID:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                config.SETTINGS.url.graphql,
                json={"query": _RECORD_STEP, "variables": {"input": record}},
            )
        payload = response.json()
        if errors := payload.get("errors"):
            raise StepReportError(f"GraphQL error: {errors[0].get('message', errors)}")
        return UUID(payload["data"]["recordStep"]["id"])


def _parent_variables(parent: StepParent) -> dict[str, str]:
    ids = {
        "taskId": parent.task_id,
        "backupId": parent.backup_id,
        "restoreId": parent.restore_id,
    }
    return {name: str(value) for name, value in ids.items() if value is not None}


def _parent_from_env() -> StepParent | None:
    given = {
        field: value
        for field, name in (
            ("task_id", TASK_ID_ENV),
            ("backup_id", BACKUP_ID_ENV),
            ("restore_id", RESTORE_ID_ENV),
        )
        if (value := os.environ.get(name))
    }
    if not given:
        return None
    try:
        return StepParent.model_validate(given)
    except ValidationError as exc:
        logger.warning("Ignoring the step parent in the environment: {}", exc)
        return None


def _uuid_from_env(name: str) -> UUID | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        logger.warning("Ignoring {}: {!r} is not a UUID", name, value)
        return None
