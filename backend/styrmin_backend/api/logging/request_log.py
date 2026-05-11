"""Strawberry schema extension that logs every GraphQL operation.

This is intentionally minimal: the line lands at ``DEBUG`` level, only
once per operation, and the variables payload is run through
:func:`mask_variables` so password fields never reach the log sink. The
existing :class:`StructuredErrorExtension` continues to handle error
logging; this extension only records the *request* (operation name +
masked variables) so audit trails have something to point at.

The masking is the FR-029 requirement; the per-operation emit gives
operators a low-volume audit hook without flooding the log with every
nested field resolution.

See ``specs/011-admin-user-group-mgmt/research.md`` §D13.
"""

from __future__ import annotations

from typing import Iterator

from loguru import logger
from strawberry.extensions import SchemaExtension

from styrmin_backend.api.logging.mask import mask_variables


class RequestLoggingExtension(SchemaExtension):
    """Log every GraphQL operation with masked variables.

    Order in the schema's ``extensions`` list does not matter — this
    extension is read-only from the executor's perspective and the
    masking pulls a deep copy, so it cannot interfere with any other
    extension or resolver.
    """

    def on_operation(self) -> Iterator[None]:
        # Strawberry populates ``operation_name`` and ``variables`` on
        # the execution context for both queries and mutations. Either
        # can be ``None`` for anonymous / variable-less operations; the
        # mask helper tolerates both.
        ctx = self.execution_context
        operation_name = ctx.operation_name or "<anonymous>"
        masked = mask_variables(ctx.variables)
        logger.debug(
            "GraphQL request operation={} variables={}",
            operation_name,
            masked,
        )
        yield
