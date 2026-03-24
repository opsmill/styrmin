from styrmin_backend.exceptions import StyrminError


class RepositoryException(StyrminError):
    """The base repository exception class."""


class EntityClassInconsistencyError(RepositoryException):
    """The entity is not of expected class."""
