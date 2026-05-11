"""GraphQL request-logging helpers.

Re-exports the masking primitives so call sites import from one place::

    from styrmin_backend.api.logging import mask_variables, MASKED_VARIABLE_NAMES
"""

from styrmin_backend.api.logging.mask import (
    MASKED_VARIABLE_NAMES,
    mask_variables,
)

__all__ = ["MASKED_VARIABLE_NAMES", "mask_variables"]
