"""The GraphQL logs of the server hold no secret of a request (#573).

Strawberry's default error log printed the request document around the error,
so a password written as a literal in a login mutation reached the server log
at ERROR. graphql-core's message for an invalid value repeats the value.
"""

from __future__ import annotations

import io
import logging

import pytest
from loguru import logger

from styrmin_backend.api import init_graphql_router

LITERAL = "FAKE573-literal-4444"


async def _execute(document: str) -> list:
    schema = init_graphql_router().schema
    # No unit of work in the context: the login resolver raises, as a wrong
    # password makes it raise, with the literal still in the document.
    result = await schema.execute(document, context_value={})
    assert result.errors
    return result.errors


@pytest.mark.asyncio
async def test_a_resolver_error_logs_its_path_and_message_not_the_document(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    await _execute(
        f'mutation Login {{ login(username: "nobody", password: "{LITERAL}") '
        "{ __typename } }"
    )

    records = [r for r in caplog.records if r.name == "strawberry.execution"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "operation Login, path login" in records[0].getMessage()
    assert records[0].exc_info is not None
    assert LITERAL not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document",
    [
        # Unknown field: the document is printed around the error.
        f'mutation {{ login(username: "nobody", password: "{LITERAL}") {{ nope }} }}',
        # A value of the wrong type: graphql-core's message repeats it.
        f'mutation {{ login(username: "nobody", password: {LITERAL.replace("-", "_")}) '
        "{ __typename } }",
    ],
    ids=["unknown-field", "invalid-value"],
)
async def test_an_invalid_request_logs_where_the_error_is_not_the_request(
    caplog: pytest.LogCaptureFixture, document: str
) -> None:
    caplog.set_level(logging.DEBUG)

    errors = await _execute(document)

    assert LITERAL not in caplog.text
    assert LITERAL.replace("-", "_") not in caplog.text
    assert "invalid request at line 1 column" in caplog.text
    # The client still receives graphql-core's message.
    assert errors[0].message


@pytest.mark.asyncio
async def test_an_invalid_variable_value_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    schema = init_graphql_router().schema

    result = await schema.execute(
        'mutation Login($p: String!) { login(username: "nobody", password: $p) '
        "{ __typename } }",
        variable_values={"p": 44714471},
        context_value={},
    )

    assert result.errors
    assert "44714471" in result.errors[0].message
    assert "44714471" not in caplog.text


@pytest.mark.asyncio
async def test_the_debug_request_log_masks_a_password_variable() -> None:
    schema = init_graphql_router().schema
    stream = io.StringIO()
    handler_id = logger.add(stream, level="DEBUG", format="{message}")
    try:
        await schema.execute(
            "mutation Login($u: String!, $p: String!) "
            "{ login(username: $u, password: $p) { __typename } }",
            variable_values={"u": "nobody", "p": "FAKE573-var-5555"},
            context_value={},
        )
    finally:
        logger.remove(handler_id)

    text = stream.getvalue()
    assert "'p': '***'" in text
    assert "FAKE573-var-5555" not in text


@pytest.mark.asyncio
async def test_an_operation_name_that_is_not_a_graphql_name_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The client chooses ``operationName``; a line break in it would start a
    # line of its own in the log.
    caplog.set_level(logging.DEBUG)
    schema = init_graphql_router().schema
    forged = "x\n09:00:00.000 | ERROR   | forged line"

    # A document that does not parse, so the error is logged before the
    # operation is looked up by its name.
    await schema.execute("query { nope", operation_name=forged, context_value={})

    assert "forged line" not in caplog.text
    assert "operation <invalid name>" in caplog.text
