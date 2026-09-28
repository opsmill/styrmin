"""Unit tests for ``run_job`` (#374).

``execute_commands`` used to create a Job with one deterministic name per
deployment and ``run_job`` never removed it, so the second call in the same
namespace -- including the next upgrade of the same deployment -- failed with a
409 that was surfaced as ``CustomResourceNotFound``. These tests pin the new
contract: the Job name is read back from the create response (so
``generateName`` works), a 409 is a typed ``JobAlreadyExistsError``, and a
failed Job is a typed ``JobFailedError``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.exceptions import (
    JobAlreadyExistsError,
    JobFailedError,
)
from styrmin_backend.agent.service.kubernetes.primitives import run_job

# Call the undecorated function so we can inject a mock client directly without
# fast_depends' ``ApiClient`` type validation.
_run_job = run_job.__wrapped__

_BATCH_API = "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.BatchV1Api"


def _job(
    name: str, *, succeeded: int | None = None, failed: int | None = None
) -> MagicMock:
    job = MagicMock()
    job.metadata.name = name
    job.status.succeeded = succeeded
    job.status.failed = failed
    return job


def _mock_batch_api(created: MagicMock, *polls: MagicMock) -> MagicMock:
    api = MagicMock()
    api.create_namespaced_job = AsyncMock(return_value=created)
    api.read_namespaced_job_status = AsyncMock(side_effect=list(polls))
    return api


_GENERATED_BODY = {
    "apiVersion": "batch/v1",
    "kind": "Job",
    "metadata": {"generateName": "styrmin-abc-job-", "namespace": "ns"},
    "spec": {"template": {"spec": {"containers": [], "restartPolicy": "Never"}}},
}


@pytest.mark.asyncio
async def test_polls_the_name_assigned_by_the_api_server() -> None:
    """With ``generateName`` the body has no ``name``; the create response does."""
    api = _mock_batch_api(
        _job("styrmin-abc-job-x7k2q"), _job("styrmin-abc-job-x7k2q", succeeded=1)
    )
    with patch(_BATCH_API, return_value=api):
        await _run_job(namespace="ns", body=_GENERATED_BODY, client=MagicMock())

    api.create_namespaced_job.assert_awaited_once()
    assert api.create_namespaced_job.call_args.kwargs["body"] is _GENERATED_BODY
    api.read_namespaced_job_status.assert_awaited_once_with(
        name="styrmin-abc-job-x7k2q", namespace="ns"
    )


@pytest.mark.asyncio
async def test_keeps_polling_until_the_job_succeeds() -> None:
    api = _mock_batch_api(
        _job("rel-job-1"),
        _job("rel-job-1"),
        _job("rel-job-1"),
        _job("rel-job-1", succeeded=1),
    )
    with (
        patch(_BATCH_API, return_value=api),
        patch(
            "styrmin_backend.agent.service.kubernetes.primitives.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep,
    ):
        await _run_job(namespace="ns", body=_GENERATED_BODY, client=MagicMock())

    assert api.read_namespaced_job_status.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_conflict_raises_typed_job_already_exists_error() -> None:
    api = _mock_batch_api(_job("unused"))
    api.create_namespaced_job.side_effect = ApiException(status=409)
    body = {"metadata": {"name": "styrmin-abc-job", "namespace": "ns"}, "spec": {}}
    with patch(_BATCH_API, return_value=api):
        with pytest.raises(
            JobAlreadyExistsError,
            match="styrmin-abc-job already exists in namespace ns",
        ):
            await _run_job(namespace="ns", body=body, client=MagicMock())

    api.read_namespaced_job_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_api_errors_propagate_unchanged() -> None:
    api = _mock_batch_api(_job("unused"))
    api.create_namespaced_job.side_effect = ApiException(status=403)
    with patch(_BATCH_API, return_value=api):
        with pytest.raises(ApiException):
            await _run_job(namespace="ns", body=_GENERATED_BODY, client=MagicMock())


@pytest.mark.asyncio
async def test_failed_job_raises_typed_job_failed_error() -> None:
    api = _mock_batch_api(_job("rel-job-9"), _job("rel-job-9", failed=1))
    with patch(_BATCH_API, return_value=api):
        with pytest.raises(JobFailedError, match="rel-job-9 failed in namespace ns"):
            await _run_job(namespace="ns", body=_GENERATED_BODY, client=MagicMock())
