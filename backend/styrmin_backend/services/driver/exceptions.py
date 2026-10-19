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


def describe_action_image(image: str | None, work_pool: str | None) -> str:
    """The words that name the action's image in the errors of the local driver check.

    ``the image <image>`` when the image is known; otherwise ``the default image
    of the work pool <work_pool>`` when the work pool is known; otherwise
    ``the image of this action's Job``. Each reads correctly after "in".
    """
    if image:
        return f"the image {image}"
    if work_pool:
        return f"the default image of the work pool {work_pool}"
    return "the image of this action's Job"


class DriverFilesNotFoundError(DriverError):
    """The driver files of a local driver version are not at its path where its action runs.

    Raised by the check that runs before an action of a driver version loaded
    from a local directory (spec 029, FR-004). ``missing`` holds the missing
    file names, or the path itself when the directory is missing. ``image`` and
    ``work_pool`` are ``None`` when the Prefect API does not give them; the
    message then names the image as :func:`describe_action_image` does.
    """

    error_code = "NOT_FOUND"
    default_message = "The driver files are not in the action's image"

    def __init__(
        self,
        *,
        path: str,
        image: str | None,
        missing: list[str],
        work_pool: str | None = None,
    ) -> None:
        self.path = path
        self.image = image
        self.work_pool = work_pool
        self.missing = missing
        super().__init__(
            f"The driver files are not at {path} in "
            f"{describe_action_image(image, work_pool)}: {', '.join(missing)} not "
            "found. An action's image must hold the driver at the same path as the "
            f"Styrmin server. Add the driver to the image at {path}, or load the "
            "driver from a path that the image holds."
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "image": self.image,
            "work_pool": self.work_pool,
            "missing": self.missing,
        }


class DriverFingerprintMismatchError(DriverError):
    """The driver files at the path where an action runs are not those of the driver version.

    Raised by the check that runs before an action of a driver version loaded
    from a local directory (spec 029, FR-003). ``expected`` and ``actual`` are
    full provenance fingerprints; the message shows their first 7 characters,
    as driver version labels do. ``image`` and ``work_pool`` are as for
    :class:`DriverFilesNotFoundError`.
    """

    error_code = "VALIDATION_ERROR"
    default_message = (
        "The driver files in the action's image differ from the driver version"
    )

    def __init__(
        self,
        *,
        path: str,
        image: str | None,
        expected: str,
        actual: str,
        work_pool: str | None = None,
    ) -> None:
        self.path = path
        self.image = image
        self.work_pool = work_pool
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"The driver files at {path} in {describe_action_image(image, work_pool)} "
            "are not the files of this driver version: their provenance fingerprint "
            f"is {actual[:7]}, and "
            f"the driver version was loaded with {expected[:7]}. The files changed "
            "after the driver was loaded. Rebuild the image with the files you loaded "
            f"and load the driver again, or load the driver again from {path} and use "
            "the new driver version."
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "image": self.image,
            "work_pool": self.work_pool,
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
