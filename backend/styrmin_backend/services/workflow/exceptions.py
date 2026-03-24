from styrmin_backend.services.exceptions import ServiceError


class WorkflowError(ServiceError):
    """Base class for exceptions in this module."""


class ContextRedefinitionError(WorkflowError):
    """The context was redefined in the workflow function."""


class ContextInCallParametersError(WorkflowError):
    """The context was passed as a parameter to the workflow function execution."""
