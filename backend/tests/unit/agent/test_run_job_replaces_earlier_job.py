"""``run_job`` deletes the ended Job of an earlier action before it creates its own (#372).

``execute_commands`` names its Job after the deployment's release, so every
run of an action on one deployment creates a Job with the same name. The
Job of the earlier run, completed or failed, is deleted with its pods, and
``run_job`` waits until it is gone before it creates the new one. A Job of
that name that is still running, or that no driver action created, is never
deleted.
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.agent.service.kubernetes import primitives
from styrmin_backend.agent.service.kubernetes.exceptions import (
    JobAlreadyExistsError,
    JobDeletedError,
    JobNotDeletedError,
    JobNotFromActionError,
    JobStillRunningError,
)
from styrmin_backend.agent.service.kubernetes.primitives import (
    ACTION_JOB_LABEL,
    run_job,
)
from tests.helpers.fake_kubernetes import FakeKubernetes, serve

NAMESPACE = "styrmin-app"
JOB = "app-release-job"
EARLIER_UID = "0b7c1d2e-earlier-run"

COMPLETED = {"succeeded": 1, "conditions": [{"type": "Complete", "status": "True"}]}
FAILED = {"failed": 1, "conditions": [{"type": "Failed", "status": "True"}]}


def _manifest() -> dict[str, Any]:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": JOB,
            "namespace": NAMESPACE,
            "labels": {ACTION_JOB_LABEL: "true"},
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"name": "user-job", "image": "busybox:1.36"}],
                    "restartPolicy": "Never",
                }
            }
        },
    }


def _earlier_job(
    status: dict[str, Any],
    *,
    labels: dict[str, str] | None = None,
    container: str = "user-job",
) -> dict[str, dict[str, Any]]:
    return {
        JOB: {
            "metadata": {
                "name": JOB,
                "uid": EARLIER_UID,
                "labels": {ACTION_JOB_LABEL: "true"} if labels is None else labels,
            },
            "spec": {
                "template": {
                    "spec": {"containers": [{"name": container, "image": "busybox"}]}
                }
            },
            "status": status,
        }
    }


@pytest.fixture(autouse=True)
def fast_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(primitives, "JOB_DELETION_POLL_SECONDS", 0.0)


@pytest.mark.parametrize(
    ("status", "end"),
    [
        pytest.param(COMPLETED, "completed", id="completed"),
        pytest.param(FAILED, "failed", id="failed"),
    ],
)
async def test_earlier_job_is_deleted_with_its_pods_then_the_new_job_is_created(
    status: dict[str, Any], end: str
) -> None:
    fake = FakeKubernetes(job_succeeds=True, jobs=_earlier_job(status))
    lines: list[str] = []

    async def on_delete(line: str) -> None:
        lines.append(line)

    async with serve(fake) as client:
        await run_job(
            namespace=NAMESPACE, body=_manifest(), client=client, on_delete=on_delete
        )

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
    assert lines == [
        f"Deleting Job {JOB}, which an earlier action left ({end}), and its pods "
        "before the new Job is created. This waits up to 120 seconds."
    ]


async def test_without_an_earlier_job_the_job_is_created_without_a_delete() -> None:
    fake = FakeKubernetes(job_succeeds=True)

    async with serve(fake) as client:
        await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert fake.job_requests == [("read", JOB), ("create", JOB), ("status", JOB)]
    assert fake.job_deletes == []


async def test_the_new_job_is_created_only_once_the_earlier_job_is_gone() -> None:
    # Kubernetes removes a Job deleted in the foreground only after its pods.
    fake = FakeKubernetes(
        job_succeeds=True, jobs=_earlier_job(FAILED), reads_until_deleted=2
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


@pytest.mark.parametrize(
    "status",
    [
        pytest.param({"active": 1}, id="running"),
        # A failed pod without the Failed condition: the Job can start another pod.
        pytest.param({"failed": 1}, id="failed-pod-before-the-backoff-limit"),
    ],
)
async def test_an_earlier_job_that_is_still_running_is_not_deleted(
    status: dict[str, Any],
) -> None:
    fake = FakeKubernetes(job_succeeds=True, jobs=_earlier_job(status))

    async with serve(fake) as client:
        with pytest.raises(JobStillRunningError) as raised:
            await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert str(raised.value) == (
        f"Job {JOB} of an earlier action is still running in namespace {NAMESPACE}, "
        "so Styrmin does not delete it: another change of this deployment may still "
        "be running its action. Wait until the Job ends, then request the change "
        f"again. To read its state: kubectl get job -n {NAMESPACE} {JOB}"
    )
    assert fake.job_requests == [("read", JOB)]
    assert fake.job_deletes == []
    assert fake.jobs[JOB]["metadata"]["uid"] == EARLIER_UID


async def test_a_job_that_no_action_created_is_not_deleted() -> None:
    fake = FakeKubernetes(
        job_succeeds=True,
        jobs=_earlier_job(
            COMPLETED, labels={"app.kubernetes.io/managed-by": "Helm"}, container="init"
        ),
    )

    async with serve(fake) as client:
        with pytest.raises(JobNotFromActionError) as raised:
            await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert str(raised.value) == (
        f"Job {JOB} in namespace {NAMESPACE} was not created by a driver action: it "
        f"has no label {ACTION_JOB_LABEL}=true. Styrmin does not delete it, so the "
        "action cannot create its own Job of that name. If nothing needs that Job, "
        f"delete it, then request the change again: kubectl delete job -n {NAMESPACE} "
        f"{JOB}"
    )
    assert fake.job_requests == [("read", JOB)]
    assert fake.job_deletes == []


async def test_an_ended_job_of_an_earlier_styrmin_version_without_the_label_is_deleted() -> (
    None
):
    # Before the label, execute_commands' Jobs had only their user-job container.
    fake = FakeKubernetes(job_succeeds=True, jobs=_earlier_job(FAILED, labels={}))

    async with serve(fake) as client:
        await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert len(fake.job_deletes) == 1
    assert fake.jobs[JOB]["metadata"]["uid"] != EARLIER_UID


async def test_an_earlier_job_that_is_not_deleted_in_time_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(primitives, "JOB_DELETION_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(primitives, "JOB_DELETION_POLL_SECONDS", 0.01)
    fake = FakeKubernetes(jobs=_earlier_job(FAILED), reads_until_deleted=None)

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
    fake = FakeKubernetes(jobs=_earlier_job(COMPLETED), recreated_after_delete=True)

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


async def test_a_job_deleted_while_styrmin_waits_for_it_raises_a_typed_error() -> None:
    fake = FakeKubernetes(job_succeeds=True, removed_before_status=True)

    async with serve(fake) as client:
        with pytest.raises(JobDeletedError) as raised:
            await run_job(namespace=NAMESPACE, body=_manifest(), client=client)

    assert str(raised.value) == (
        f"Job {JOB} in namespace {NAMESPACE} was deleted before it ended, so the "
        "result of its commands is not known. Something other than this action "
        "deleted it, such as another change of this deployment or a kubectl command. "
        "Request the change again."
    )
