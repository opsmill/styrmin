"""``run_job`` deletes the Job that an earlier run left before it creates its own (#372).

``execute_commands`` names its Job after the deployment's release, so every
run of an action on one deployment creates a Job with the same name. The
Job of the earlier run, completed or failed, is deleted with its pods, and
``run_job`` waits until it is gone before it creates the new one.
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.agent.service.kubernetes import primitives
from styrmin_backend.agent.service.kubernetes.exceptions import (
    JobAlreadyExistsError,
    JobNotDeletedError,
)
from styrmin_backend.agent.service.kubernetes.primitives import run_job
from tests.helpers.fake_kubernetes import FakeKubernetes, serve

NAMESPACE = "styrmin-app"
JOB = "app-release-job"
EARLIER_UID = "0b7c1d2e-earlier-run"


def _manifest() -> dict[str, Any]:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": JOB, "namespace": NAMESPACE},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"name": "user-job", "image": "busybox:1.36"}],
                    "restartPolicy": "Never",
                }
            }
        },
    }


def _earlier_job(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {JOB: {"metadata": {"name": JOB, "uid": EARLIER_UID}, "status": status}}


@pytest.fixture(autouse=True)
def fast_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(primitives, "JOB_DELETION_POLL_SECONDS", 0.0)


@pytest.mark.parametrize(
    "status",
    [
        pytest.param({"succeeded": 1}, id="completed"),
        pytest.param({"failed": 1}, id="failed"),
    ],
)
async def test_earlier_job_is_deleted_with_its_pods_then_the_new_job_is_created(
    status: dict[str, Any],
) -> None:
    fake = FakeKubernetes(job_succeeds=True, jobs=_earlier_job(status))

    async with serve(fake) as client:
        await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert fake.job_requests == [
        ("read", JOB),
        ("delete", JOB),
        ("read", JOB),
        ("create", JOB),
        ("status", JOB),
    ]
    (options,) = fake.job_deletes
    assert options["propagationPolicy"] == "Foreground"
    assert options["preconditions"] == {"uid": EARLIER_UID}
    assert fake.jobs[JOB]["metadata"]["uid"] != EARLIER_UID


async def test_without_an_earlier_job_the_job_is_created_without_a_delete() -> None:
    fake = FakeKubernetes(job_succeeds=True)

    async with serve(fake) as client:
        await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert fake.job_requests == [("read", JOB), ("create", JOB), ("status", JOB)]
    assert fake.job_deletes == []


async def test_the_new_job_is_created_only_once_the_earlier_job_is_gone() -> None:
    # Kubernetes removes a Job deleted in the foreground only after its pods.
    fake = FakeKubernetes(
        job_succeeds=True, jobs=_earlier_job({"failed": 1}), reads_until_deleted=2
    )

    async with serve(fake) as client:
        await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert fake.job_requests == [
        ("read", JOB),
        ("delete", JOB),
        ("read", JOB),
        ("read", JOB),
        ("read", JOB),
        ("create", JOB),
        ("status", JOB),
    ]


async def test_an_earlier_job_that_is_not_deleted_in_time_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(primitives, "JOB_DELETION_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(primitives, "JOB_DELETION_POLL_SECONDS", 0.01)
    fake = FakeKubernetes(jobs=_earlier_job({"failed": 1}), reads_until_deleted=None)

    async with serve(fake) as client:
        with pytest.raises(JobNotDeletedError) as raised:
            await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert str(raised.value) == (
        f"Job {JOB} of an earlier run still exists in namespace {NAMESPACE} 0 seconds "
        "after Styrmin deleted it, so the new Job cannot be created. Check why its pods "
        f"are not removed: kubectl get pods -n {NAMESPACE} "
        f"-l batch.kubernetes.io/job-name={JOB}"
    )
    assert ("create", JOB) not in fake.job_requests


async def test_a_job_created_by_another_writer_after_the_delete_raises_a_typed_error() -> (
    None
):
    fake = FakeKubernetes(
        jobs=_earlier_job({"succeeded": 1}), recreated_after_delete=True
    )

    async with serve(fake) as client:
        with pytest.raises(JobAlreadyExistsError) as raised:
            await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert str(raised.value) == (
        f"Job {JOB} already exists in namespace {NAMESPACE}: it was created after "
        "Styrmin deleted the Job of an earlier run. Another action may be running for "
        "this deployment."
    )
    # The other writer's Job is left alone: one delete, of the earlier Job only.
    assert len(fake.job_deletes) == 1
    assert fake.job_requests[-1] == ("create", JOB)
