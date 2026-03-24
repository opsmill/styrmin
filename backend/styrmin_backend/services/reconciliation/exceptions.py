from styrmin_backend.services.exceptions import ServiceError


class ReconciliationError(ServiceError):
    """Base class for all reconciliation-related exceptions."""
