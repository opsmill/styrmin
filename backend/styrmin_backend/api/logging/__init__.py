"""GraphQL request-logging helpers.

Re-exports the masking primitive so call sites import from one place::

    from styrmin_backend.api.logging import mask_variables
"""

from styrmin_backend.api.logging.mask import mask_variables

__all__ = ["mask_variables"]
