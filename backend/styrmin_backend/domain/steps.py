"""Keys, names and kinds of the steps that flows record (spec 019, data-model "Step keys and names")."""

from __future__ import annotations

from typing import NamedTuple

from styrmin_backend.domain.models import StepKind


class StepDefinition(NamedTuple):
    """A step's stable key within its parent, the name users view, and its kind."""

    key: str
    name: str
    kind: StepKind


PLAN = StepDefinition("plan", "Plan the changes", StepKind.PLAN)
SETUP_PRE_HOOK = StepDefinition(
    "hook:setup:pre", "Run the setup pre-hook", StepKind.HOOK
)
SETUP_POST_HOOK = StepDefinition(
    "hook:setup:post", "Run the setup post-hook", StepKind.HOOK
)
UPGRADE_PRE_HOOK = StepDefinition(
    "hook:upgrade:pre", "Run the upgrade pre-hook", StepKind.HOOK
)
UPGRADE_CORE_HOOK = StepDefinition(
    "hook:upgrade:core", "Run the upgrade hook", StepKind.HOOK
)
UPGRADE_POST_HOOK = StepDefinition(
    "hook:upgrade:post", "Run the upgrade post-hook", StepKind.HOOK
)
STYRMIN_DEPLOYMENT_WRITE = StepDefinition(
    "resource:styrmindeployment",
    "Write the StyrminDeployment resource",
    StepKind.RESOURCE_WRITE,
)
SERVICE_ALIASES = StepDefinition(
    "resource:service-aliases", "Create service aliases", StepKind.RESOURCE_WRITE
)
COMMAND = StepDefinition("command", "Run the job's command", StepKind.COMMAND)
