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
DELETE_REQUEST = StepDefinition(
    "resource:delete-request", "Request the deletion", StepKind.RESOURCE_WRITE
)

OPERATOR_PREREQUISITES = StepDefinition(
    "operator:prerequisites",
    "Create network policies and secrets",
    StepKind.OPERATOR_PHASE,
)
OPERATOR_HELMRELEASE = StepDefinition(
    "operator:helmrelease",
    "Install or upgrade the HelmRelease",
    StepKind.OPERATOR_PHASE,
)
OPERATOR_SERVICES = StepDefinition(
    "operator:services", "Create services and middlewares", StepKind.OPERATOR_PHASE
)
OPERATOR_READY = StepDefinition(
    "operator:ready", "Wait for the deployment to be ready", StepKind.OPERATOR_PHASE
)
OPERATOR_TEARDOWN = StepDefinition(
    "operator:teardown",
    "Remove the deployment's resources and namespace",
    StepKind.OPERATOR_PHASE,
)

#: The operator-phase steps of a rollout, in the order the operator runs them.
ROLLOUT_OPERATOR_STEPS = (
    OPERATOR_PREREQUISITES,
    OPERATOR_HELMRELEASE,
    OPERATOR_SERVICES,
    OPERATOR_READY,
)
