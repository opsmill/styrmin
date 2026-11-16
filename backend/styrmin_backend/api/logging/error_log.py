"""Log GraphQL errors without the request document (#573).

Strawberry's default ``Schema.process_errors`` logs ``str(error)``, which
prints the lines of the request document around the error. A request that
writes a password as a literal, such as
``mutation { login(username: "u", password: "...") }``, then puts the
password in the server log at ``ERROR``. graphql-core's messages for an
invalid request can also repeat a value of the request, such as
``String cannot represent a non string value: hunter2``.

:class:`StyrminSchema` logs one line per error on the same logger,
``strawberry.execution``, at the same level, with the traceback of the
exception that a resolver raised. The line holds the operation name, the
path and the message, except for the message of an invalid request, which
only the client receives.
"""

from __future__ import annotations

import logging
import re

import strawberry
from graphql import GraphQLError
from strawberry.types import ExecutionContext

#: Strawberry's logger for these errors, kept so that existing log filters still match.
logger = logging.getLogger("strawberry.execution")


def _from_styrmin(error: GraphQLError) -> bool:
    return bool(error.path or (error.extensions or {}).get("code"))


def describe_error(error: GraphQLError) -> str:
    """The message of ``error`` when no part of the request can be in it, else where the error is.

    A resolver error (it has a path) and an error that Styrmin built with a
    code, such as ``UNAUTHENTICATED``, have a message that Styrmin wrote. An
    error of parsing, validation or variable coercion comes from graphql-core
    and can repeat a value of the request.
    """
    if _from_styrmin(error):
        return error.message
    where = ", ".join(
        f"line {location.line} column {location.column}"
        for location in error.locations or ()
    )
    return (
        f"invalid request at {where or 'an unknown place'}; "
        "only the client receives the message"
    )


# A GraphQL name, cut to a length that fits a log line.
_OPERATION_NAME = re.compile(r"[_A-Za-z][_0-9A-Za-z]{0,99}")


def _operation_name(execution_context: ExecutionContext | None) -> str:
    """The operation name, or a placeholder when it is missing or not a GraphQL name.

    The client sends the ``operationName`` of a request as any string, so a
    value that is not a GraphQL name, such as one with a line break, is not
    written to the log.
    """
    if execution_context is None:
        return "<anonymous>"
    try:
        name = execution_context.operation_name
    except Exception:  # noqa: BLE001 - a log line must not fail the request
        return "<anonymous>"
    if not name:
        return "<anonymous>"
    return name if _OPERATION_NAME.fullmatch(name) else "<invalid name>"


class StyrminSchema(strawberry.Schema):
    """Strawberry schema whose error log holds no part of the request."""

    def process_errors(
        self,
        errors: list[GraphQLError],
        execution_context: ExecutionContext | None = None,
    ) -> None:
        operation = _operation_name(execution_context)
        for error in errors:
            path = ".".join(str(key) for key in error.path) if error.path else "-"
            logger.error(
                "GraphQL error in operation %s, path %s: %s",
                operation,
                path,
                describe_error(error),
                # The traceback of a graphql-core error repeats its message.
                exc_info=error.original_error if error.path else None,
            )
