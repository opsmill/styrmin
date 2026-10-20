import shlex
from typing import Any, Literal

from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.exceptions import ServiceError


class DriverError(ServiceError):
    """Base class for driver errors."""

    error_code = "VALIDATION_ERROR"
    default_message = "A driver error occurred"


class DriverDefinitionError(DriverError):
    """An error occurred while defining the driver.

    This error indicates an error in the driver definition itself.
    It is not related to the driver data and therefore not imputable to the user data.
    """


class ParsingError(DriverError):
    """An error occurred while parsing the driver data."""


class ValidationError(DriverError):
    """An error occurred while validating the driver data."""


class DeserializationError(DriverError):
    """An error occurred while deserializing the driver data."""


class DriverLoadingError(DriverError):
    """An error occurred while loading the driver."""


class MissingDriverSpecificationError(DriverError):
    """A piece of driver data is missing."""


def describe_agent_pod(agent_pod: str | None) -> str:
    """The words that name the pod where an action runs, in the errors of the local driver check.

    ``the Styrmin agent pod <agent_pod>`` when the pod is known; otherwise
    ``the Styrmin agent pod``. The agent's Prefect process worker runs every
    action as a process in the agent pod; an action's ``image:`` has no
    effect, so the errors do not name an image.
    """
    return (
        f"the Styrmin agent pod {agent_pod}" if agent_pod else "the Styrmin agent pod"
    )


def _load_local_command(path: str) -> str:
    return shlex.join(["styrminctl", "drivers", "load-local-version", path])


class DriverFilesNotFoundError(DriverError):
    """The driver files of a local driver version are not at its path where its action runs.

    Raised by the check that runs before an action of a driver version loaded
    from a local directory (spec 029, FR-004). ``missing`` holds the missing
    file names, or the path itself when the directory is missing.
    ``agent_pod`` names the pod where the check ran, or is ``None`` when it is
    not known.
    """

    error_code = "NOT_FOUND"
    default_message = "The driver files are not in the agent pod, where the action runs"

    def __init__(
        self,
        *,
        path: str,
        missing: list[str],
        agent_pod: str | None = None,
    ) -> None:
        self.path = path
        self.missing = missing
        self.agent_pod = agent_pod
        super().__init__(
            f"The driver files are not at {path} in {describe_agent_pod(agent_pod)}: "
            f"{', '.join(missing)} not found. The agent pod runs every driver action, "
            "so it must hold the driver at the same path as the Styrmin server. Mount "
            f"or copy the driver into the agent pod at {path}, or load the driver from "
            "a path that both the server and the agent pod hold."
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "agent_pod": self.agent_pod,
            "missing": self.missing,
        }


class DriverFingerprintMismatchError(DriverError):
    """The driver files at the path where an action runs are not those of the driver version.

    Raised by the check that runs before an action of a driver version loaded
    from a local directory (spec 029, FR-003). ``expected`` and ``actual`` are
    full provenance fingerprints; the message shows their first 7 characters,
    as driver version labels do. ``agent_pod`` is as for
    :class:`DriverFilesNotFoundError`.
    """

    error_code = "VALIDATION_ERROR"
    default_message = (
        "The driver files in the agent pod, where the action runs, differ from the "
        "driver version"
    )

    def __init__(
        self,
        *,
        path: str,
        expected: str,
        actual: str,
        agent_pod: str | None = None,
    ) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        self.agent_pod = agent_pod
        super().__init__(
            f"The driver files at {path} in {describe_agent_pod(agent_pod)} are not "
            "the files of this driver version: their provenance fingerprint is "
            f"{actual[:7]}, and the driver version was loaded with {expected[:7]}. If "
            "the files changed after the driver was loaded, load the driver again and "
            f"use the new driver version: {_load_local_command(path)}. If the agent "
            f"pod holds other files at {path} than the Styrmin server, give both the "
            "same files first."
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "agent_pod": self.agent_pod,
            "expected": self.expected,
            "actual": self.actual,
        }


class ActionNotRegisteredError(DriverError):
    """A driver version declares an action for a hook and mode, and no flow is registered for it.

    Raised by hook resolution (spec 029, FR-005). ``hook`` and ``mode`` name
    the hook step that cannot run. ``load_command`` is the ``styrminctl``
    command that loads the driver again and registers its actions.
    """

    error_code = "NOT_FOUND"
    default_message = "A declared action has no registered flow"

    def __init__(
        self,
        *,
        driver_name: str,
        driver_version_label: str,
        actions: list[str],
        hook: HookKind,
        mode: Literal["pre", "core", "post"],
        load_command: str,
    ) -> None:
        self.driver_name = driver_name
        self.driver_version_label = driver_version_label
        self.actions = actions
        self.hook = hook
        self.mode = mode
        self.load_command = load_command
        super().__init__(
            f"Driver version {driver_name} {driver_version_label} declares the action "
            f"{', '.join(actions)} for the {hook.value} hook, mode {mode}, but no flow is "
            "registered for it, so the hook cannot run. Load the driver again to "
            f"register its actions: {load_command}. Then request the change again; a "
            "deployment whose creation failed must be deleted and created again. If the "
            "driver's files or commit changed since it was loaded, the load creates a "
            "new driver version; use that version instead."
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "driver": self.driver_name,
            "driver_version": self.driver_version_label,
            "actions": self.actions,
            "hook": self.hook.value,
            "mode": self.mode,
        }
