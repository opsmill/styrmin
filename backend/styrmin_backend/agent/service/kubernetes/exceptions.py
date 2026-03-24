from styrmin_backend.agent.service.exceptions import AgentServiceError


class KubernetesError(AgentServiceError):
    """Base class for exceptions in the Kubernetes module."""


class CustomResourceNotFound(KubernetesError):
    """The custom resource could not be found."""


class JobFailedError(AgentServiceError):
    """Exception raised when a job fails to complete successfully."""
