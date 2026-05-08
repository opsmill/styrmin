from __future__ import annotations

import strawberry

from styrmin_backend.api.scalars import JSON

from styrmin_backend.api.definitions.task.model import Task
from styrmin_backend.services.deployment_timeline import (
    ContextChange as ContextChangeData,
    ContextDiff as ContextDiffData,
    TimelineEntry as TimelineEntryData,
)


@strawberry.type
class ContextChange:
    """A single change within a context diff."""

    path: str
    action: str
    old_value: JSON | None = None
    new_value: JSON | None = None

    @classmethod
    def from_data(cls, data: ContextChangeData) -> ContextChange:
        return cls(
            path=data.path,
            action=data.action,
            old_value=data.old_value,
            new_value=data.new_value,
        )


@strawberry.type
class ContextDiff:
    """Diff between two ApplicationInstance context objects."""

    changes: list[ContextChange]

    @classmethod
    def from_data(cls, data: ContextDiffData) -> ContextDiff:
        return cls(changes=[ContextChange.from_data(c) for c in data.changes])


@strawberry.type
class DeploymentTimelineEntry:
    """A task enriched with version and diff data for the deployment timeline."""

    task: Task
    application_version: str | None = None
    context_diff: ContextDiff | None = None

    @classmethod
    def from_data(cls, entry: TimelineEntryData) -> DeploymentTimelineEntry:
        return cls(
            task=Task.from_instance(entry.task),
            application_version=entry.application_version,
            context_diff=(
                ContextDiff.from_data(entry.context_diff)
                if entry.context_diff
                else None
            ),
        )
