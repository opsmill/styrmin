"""Models built from task reads."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FailedStep(BaseModel):
    """A failed step: its name, the task that holds it, and its newest error."""

    model_config = ConfigDict(frozen=True)

    name: str
    task_id: UUID
    error: str | None = None
