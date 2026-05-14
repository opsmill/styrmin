"""Parameter validation and resolution for deployments.

Validates user-provided parameter values against driver parameter definitions
and applies default values for omitted optional parameters.

Modules:

* :mod:`validator` — :func:`parse_parameter_definitions` and
  :func:`validate_parameter_values`, the validation entry points.
* :mod:`exceptions` — :class:`~styrmin_backend.services.exceptions.ServiceError`
  subclasses surfaced through ``StructuredErrorExtension`` as precise
  GraphQL ``extensions.code`` values.
"""

from styrmin_backend.services.parameters.exceptions import (
    DuplicateParameterNameError,
)
from styrmin_backend.services.parameters.validator import (
    parse_parameter_definitions,
    validate_parameter_values,
)

__all__ = [
    "DuplicateParameterNameError",
    "parse_parameter_definitions",
    "validate_parameter_values",
]
