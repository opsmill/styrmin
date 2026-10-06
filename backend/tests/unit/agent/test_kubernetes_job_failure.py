"""A failed Kubernetes Job raises ``JobFailedError`` with the end of its output (spec 019, research D10)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from styrmin_backend.agent.service.kubernetes.exceptions import JobFailedError
from styrmin_backend.agent.service.kubernetes.primitives import (
    run_job,
    run_kubernetes_job,
)
from tests.helpers.fake_kubernetes import (
    GENERATED_SUFFIX,
    FakeKubernetes,
    FakePod,
    serve,
)

NAMESPACE = "styrmin-app"


def _manifest(container: str, **metadata: str) -> dict[str, Any]:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"namespace": NAMESPACE, **metadata},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"name": container, "image": "busybox:1.36"}],
                    "restartPolicy": "Never",
                }
            }
        },
    }


def _pod(job: str, logs: dict[str, bytes]) -> FakePod:
    return FakePod(
        name=f"{job}-pod",
        labels={"batch.kubernetes.io/job-name": job},
        created=datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
        logs=logs,
    )


async def test_run_job_failure_carries_the_user_job_output() -> None:
    job = "app-release-job"
    fake = FakeKubernetes(
        pods=[_pod(job, {"user-job": b"exit 3\n", "istio-proxy": b"proxy\n"})]
    )

    async with serve(fake) as client:
        with pytest.raises(JobFailedError) as raised:
            await run_job(
                namespace=NAMESPACE,
                body=_manifest("user-job", name=job),
                client=client,
            )

    assert str(raised.value) == f"Job {job} failed in namespace {NAMESPACE}"
    assert (raised.value.output, raised.value.truncated) == ("exit 3\n", False)
    assert [read["container"] for read in fake.log_reads] == ["user-job"]


async def test_run_kubernetes_job_failure_names_the_generated_job() -> None:
    # The manifest has only ``generateName``; the error names the created Job.
    job = f"job-run-42-{GENERATED_SUFFIX}"
    fake = FakeKubernetes(pods=[_pod(job, {"prefect-job": b"Traceback: boom\n"})])

    async with serve(fake) as client:
        with pytest.raises(JobFailedError) as raised:
            await run_kubernetes_job(
                namespace=NAMESPACE,
                manifest=_manifest("prefect-job", generateName="job-run-42-"),
                client=client,
            )

    assert str(raised.value) == f"Job {job} failed in namespace {NAMESPACE}"
    assert (raised.value.output, raised.value.truncated) == ("Traceback: boom\n", False)
    assert [read["container"] for read in fake.log_reads] == ["prefect-job"]


async def test_run_kubernetes_job_returns_the_completed_job() -> None:
    fake = FakeKubernetes(job_succeeds=True)

    async with serve(fake) as client:
        job = await run_kubernetes_job(
            namespace=NAMESPACE,
            manifest=_manifest("prefect-job", generateName="job-run-42-"),
            client=client,
        )

    assert job.metadata.name == f"job-run-42-{GENERATED_SUFFIX}"
    assert fake.log_reads == []


@pytest.mark.parametrize(
    ("fake", "reason"),
    [
        (FakeKubernetes(), "no pod of Job {job} was found in namespace styrmin-app"),
        (
            FakeKubernetes(list_error=(403, "pods is forbidden")),
            "the Kubernetes API answered 403: pods is forbidden",
        ),
    ],
    ids=["no-pod", "api-error"],
)
async def test_unreadable_output_keeps_the_job_failure(
    fake: FakeKubernetes, reason: str
) -> None:
    job = "app-release-job"

    async with serve(fake) as client:
        with pytest.raises(JobFailedError) as raised:
            await run_job(
                namespace=NAMESPACE,
                body=_manifest("user-job", name=job),
                client=client,
            )

    assert str(raised.value) == (
        f"Job {job} failed in namespace {NAMESPACE}. "
        f"The output could not be read: {reason.format(job=job)}"
    )
    assert (raised.value.output, raised.value.truncated) == (None, False)
