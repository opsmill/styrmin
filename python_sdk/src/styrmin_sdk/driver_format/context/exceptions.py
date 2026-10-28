"""Errors of the context model."""


class ContextError(Exception):
    """Base class for exceptions in this module."""


class InvalidClusterContextError(ContextError):
    """The cluster context is invalid."""


class InvalidEnvironmentContextError(ContextError):
    """The environment context is invalid."""


class InvalidApplicationContextError(ContextError):
    """The application context is invalid."""


class InvalidDeploymentContextError(ContextError):
    """The instance context is invalid."""


class InvalidContextError(ContextError):
    """The context is invalid."""
