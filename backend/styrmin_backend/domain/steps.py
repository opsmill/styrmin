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
    "resource:service-aliases",
    "Create and delete service aliases",
    StepKind.RESOURCE_WRITE,
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

RESTORE_NAMESPACE = StepDefinition(
    "restore:namespace", "Delete the namespace", StepKind.RESTORE
)
RESTORE_VELERO = StepDefinition(
    "restore:velero", "Run the Velero restore", StepKind.RESTORE
)
RESTORE_RECOVERY = StepDefinition(
    "restore:recovery", "Run the recovery", StepKind.RESTORE
)


def backup_component_step(component: str) -> StepDefinition:
    """The step that backs up one component of a backup."""
    return StepDefinition(
        f"backup:component:{component}",
        f"Back up {component}",
        StepKind.BACKUP_COMPONENT,
    )


#: The operator-phase steps of a rollout, in the order the operator runs them.
ROLLOUT_OPERATOR_STEPS = (
    OPERATOR_PREREQUISITES,
    OPERATOR_HELMRELEASE,
    OPERATOR_SERVICES,
    OPERATOR_READY,
)

#: The keys of the steps whose success ends the rollouts of the deployment's older tasks.
CR_WRITE_KEYS = (STYRMIN_DEPLOYMENT_WRITE.key, DELETE_REQUEST.key)

#: The server keeps at most the end of a command's output (spec FR-003).
MAX_OUTPUT_LINES = 200
MAX_OUTPUT_BYTES = 64 * 1024


def truncate_output(output: str) -> tuple[str, bool]:
    """Keep the last ``MAX_OUTPUT_LINES`` lines and ``MAX_OUTPUT_BYTES`` bytes.

    Returns the kept text and whether earlier output was cut. A byte cut drops
    the partial first line, unless that line is all that is left.
    """
    truncated = False
    trailing_newline = output.endswith("\n")
    lines = (output[:-1] if trailing_newline else output).split("\n")
    if len(lines) > MAX_OUTPUT_LINES:
        output = "\n".join(lines[-MAX_OUTPUT_LINES:]) + (
            "\n" if trailing_newline else ""
        )
        truncated = True
    encoded = output.encode()
    if len(encoded) > MAX_OUTPUT_BYTES:
        starts_on_line = encoded[-MAX_OUTPUT_BYTES - 1] == ord("\n")
        output = encoded[-MAX_OUTPUT_BYTES:].decode(errors="ignore")
        first_newline = output.find("\n")
        if not starts_on_line and 0 <= first_newline < len(output) - 1:
            output = output[first_newline + 1 :]
        truncated = True
    return output, truncated
