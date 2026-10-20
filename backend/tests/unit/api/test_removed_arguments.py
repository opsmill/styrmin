"""Unit tests for ``ExplainRemovedArguments``.

A request that sends a removed argument gets the message listed in
``REMOVED_ARGUMENTS``; any other unknown argument keeps graphql-core's
"Unknown argument" message. Both are refused before the resolver runs.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import strawberry

from styrmin_backend.api.removed_arguments import ExplainRemovedArguments


def _build_schema(calls: list[UUID]) -> strawberry.Schema:
    @strawberry.type
    class Query:
        @strawberry.field
        def ping(self) -> str:
            return "pong"

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create_restore(self, backup_id: UUID) -> str:
            calls.append(backup_id)
            return "created"

    return strawberry.Schema(
        query=Query, mutation=Mutation, extensions=[ExplainRemovedArguments]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", ["targetNamespace", "targetInstanceId"])
async def test_a_removed_argument_is_explained(argument: str) -> None:
    calls: list[UUID] = []
    schema = _build_schema(calls)

    result = await schema.execute(
        f'mutation {{ createRestore(backupId: "{uuid4()}", {argument}: "x") }}'
    )

    assert result.errors is not None
    [error] = result.errors
    assert error.message.startswith(
        f"createRestore no longer takes the argument {argument}: "
    )
    assert "Upgrade styrminctl and the Python SDK" in error.message
    assert calls == []


@pytest.mark.asyncio
async def test_another_unknown_argument_keeps_the_graphql_core_message() -> None:
    calls: list[UUID] = []
    schema = _build_schema(calls)

    result = await schema.execute(
        f'mutation {{ createRestore(backupId: "{uuid4()}", force: true) }}'
    )

    assert result.errors is not None
    [error] = result.errors
    assert error.message == (
        "Unknown argument 'force' on field 'Mutation.createRestore'."
    )
    assert calls == []


@pytest.mark.asyncio
async def test_a_request_without_removed_arguments_runs() -> None:
    calls: list[UUID] = []
    schema = _build_schema(calls)
    backup_id = uuid4()

    result = await schema.execute(
        f'mutation {{ createRestore(backupId: "{backup_id}") }}'
    )

    assert result.errors is None
    assert calls == [backup_id]
