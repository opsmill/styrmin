"""Unit tests for the Job manifest built by ``execute_commands`` (#374).

The primitive must be callable any number of times in the same deployment
namespace -- across hooks and across upgrades of the same deployment -- so the
Job it creates has to be unique per call and must not stay behind forever.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.actions.primitives import (
    JOB_TTL_SECONDS_AFTER_FINISHED,
    execute_commands,
)

_RUN_JOB = "styrmin_backend.actions.primitives.run_job"


def _context() -> MagicMock:
    context = MagicMock()
    context.instance.release_reference = "styrmin-abc"
    context.instance.namespace = "styrmin-abc"
    context.components = None
    return context


@pytest.mark.asyncio
async def test_job_name_is_generated_per_call() -> None:
    run_job = AsyncMock()
    with patch(_RUN_JOB, run_job):
        await execute_commands.fn(
            ["sh", "-c", "true"], image="busybox", context=_context()
        )

    run_job.assert_awaited_once()
    body = run_job.call_args.kwargs["body"]
    assert run_job.call_args.kwargs["namespace"] == "styrmin-abc"
    assert body["metadata"]["generateName"] == "styrmin-abc-job-"
    assert "name" not in body["metadata"], (
        "a fixed name collides with the previous call's Job"
    )
    assert body["metadata"]["namespace"] == "styrmin-abc"


@pytest.mark.asyncio
async def test_finished_jobs_are_garbage_collected() -> None:
    run_job = AsyncMock()
    with patch(_RUN_JOB, run_job):
        await execute_commands.fn(
            ["sh", "-c", "true"], image="busybox", context=_context()
        )

    body = run_job.call_args.kwargs["body"]
    assert body["spec"]["ttlSecondsAfterFinished"] == JOB_TTL_SECONDS_AFTER_FINISHED
    assert JOB_TTL_SECONDS_AFTER_FINISHED > 0


@pytest.mark.asyncio
async def test_two_calls_in_the_same_namespace_both_reach_kubernetes() -> None:
    """The scenario from #374: the same action runs the primitive twice."""
    run_job = AsyncMock()
    context = _context()
    with patch(_RUN_JOB, run_job):
        await execute_commands.fn(["echo", "first"], image="busybox", context=context)
        await execute_commands.fn(["echo", "second"], image="busybox", context=context)

    assert run_job.await_count == 2
    first, second = (call.kwargs["body"] for call in run_job.await_args_list)
    assert first["metadata"] == second["metadata"], (
        "both calls share the same generateName prefix"
    )
    assert first["spec"]["template"]["spec"]["containers"][0]["command"] == [
        "echo",
        "first",
    ]
    assert second["spec"]["template"]["spec"]["containers"][0]["command"] == [
        "echo",
        "second",
    ]
