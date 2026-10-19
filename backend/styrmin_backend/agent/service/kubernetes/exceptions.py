from styrmin_backend.agent.service.exceptions import AgentServiceError


class KubernetesError(AgentServiceError):
    """Base class for exceptions in the Kubernetes module."""


class CustomResourceNotFound(KubernetesError):
    """The custom resource could not be found."""


class CustomResourceWriteConflictError(KubernetesError):
    """Other writes changed a custom resource between each read and write of a flow."""


class JobFailedError(AgentServiceError):
    """A Kubernetes Job failed; carries the end of its output when it could be read."""

    def __init__(
        self, message: str, *, output: str | None = None, truncated: bool = False
    ) -> None:
        super().__init__(message)
        #: The end of the Job's output, or None when it could not be read.
        self.output = output
        #: True when earlier output was cut.
        self.truncated = truncated


class JobOutputUnreadableError(KubernetesError):
    """The output of a Job's pod could not be read; the message gives the reason."""


class JobNotDeletedError(KubernetesError):
    """The earlier Job of the same name, or its pods, still existed when the wait for their deletion ended."""


class JobAlreadyExistsError(KubernetesError):
    """A Job of the same name was created after Styrmin deleted the earlier one."""
