from __future__ import annotations

import strawberry

from styrmin_backend.api.scalars import JSON

from styrmin_backend.api.definitions.task.model import Task
from styrmin_backend.services.deployment_timeline import (
    ContextChange as ContextChangeData,
    ContextDiff as ContextDiffData,
    TimelineEntry as TimelineEntryData,
)
from styrmin_backend.services.env_vars.patch_builder import (
    ChartEnvCollision as ChartEnvCollisionData,
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


@strawberry.type(
    description=(
        "Collision between an operator-set env var and a chart-rendered env "
        "entry of the same name. The operator-set value wins; this record "
        "exposes the chart value for audit. v1 NOTE: the backend has no "
        "line-of-sight into the post-rendered manifest at the patch layer "
        "(Kustomize processes the post-render patch on-cluster), so this "
        "field is exposed for forward-compatibility but always returns an "
        "empty list in v1. Per FR-028 the conflict-detection path is allowed "
        "to degrade fully — no detection runs and no warnings are emitted "
        "today. A future iteration will add a post-apply rendered-manifest "
        "fetch + diff path; until then operators must inspect chart values "
        "directly (e.g. via `kubectl get` on the rendered workload). "
        "See ADR-019 §3."
    )
)
class EnvVarCollision:
    """GraphQL projection of :class:`ChartEnvCollision`."""

    component: str | None
    container: str
    name: str
    chart_value: str
    user_value: str

    @classmethod
    def from_data(cls, data: ChartEnvCollisionData) -> EnvVarCollision:
        return cls(
            component=data.component,
            container=data.container,
            name=data.name,
            chart_value=data.chart_value,
            user_value=data.user_value,
        )


@strawberry.type
class DeploymentTimelineEntry:
    """A task enriched with version and diff data for the deployment timeline."""

    task: Task
    application_version: str | None = None
    context_diff: ContextDiff | None = None
    env_var_collisions: list[EnvVarCollision] = strawberry.field(
        default_factory=list,
        description=(
            "Chart-vs-user env var collisions detected during the reconcile "
            "this entry represents. Empty in v1 — see :type:`EnvVarCollision` "
            "for the FR-028 degradation rationale; structured log entries "
            "are the authoritative source until the rendered-manifest "
            "detection seam lands."
        ),
    )

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
            env_var_collisions=[
                EnvVarCollision.from_data(c) for c in entry.env_var_collisions
            ],
        )
