"""Errors of the step recorder and step reads (spec 019, data-model "Validation rules")."""

from styrmin_backend.services.exceptions import ServiceError


class StepNotFoundError(ServiceError):
    """The step was not found."""

    error_code = "NOT_FOUND"
    default_message = "Step not found"


class InvalidStepRecordError(ServiceError):
    """A step record names no step, no single parent with a key, or lacks a field."""

    error_code = "VALIDATION_ERROR"
    default_message = "Invalid step record"
