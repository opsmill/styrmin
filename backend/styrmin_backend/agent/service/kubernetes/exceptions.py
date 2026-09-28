from styrmin_backend.agent.service.exceptions import AgentServiceError


class KubernetesError(AgentServiceError):
    """Base class for exceptions in the Kubernetes module."""


class CustomResourceNotFound(KubernetesError):
    """The custom resource could not be found."""


class JobAlreadyExistsError(KubernetesError):
    """A Job with the requested name already exists in the namespace."""


class JobFailedError(AgentServiceError):
    """Exception raised when a job fails to complete successfully."""
