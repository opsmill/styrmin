"""Reading the end of a failed Job's output (spec 019, contracts/flow-step-reporter.md "Job output")."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kubernetes_asyncio.client import Configuration
from kubernetes_asyncio.client.api_client import ApiClient

from styrmin_backend.agent.service.kubernetes.exceptions import (
    JobOutputUnreadableError,
)
from styrmin_backend.agent.service.kubernetes.job_logs import (
    JobOutput,
    read_job_output_tail,
)
from styrmin_backend.domain.steps import MAX_OUTPUT_BYTES
from tests.helpers.fake_kubernetes import FakeKubernetes, FakePod, serve

NAMESPACE = "styrmin-app"
JOB = "app-job"
CONTAINER = "user-job"
JOB_LABEL = "batch.kubernetes.io/job-name"
LEGACY_JOB_LABEL = "job-name"


def _pod(
    name: str,
    *,
    minute: int = 0,
    log: bytes = b"",
    label: str = JOB_LABEL,
    job: str = JOB,
    phase: str = "Failed",
) -> FakePod:
    return FakePod(
        name=name,
        labels={label: job},
        created=datetime(2026, 10, 6, 10, minute, tzinfo=UTC),
        logs={CONTAINER: log, "sidecar": b"sidecar output\n"},
        phase=phase,
    )


async def _read(fake: FakeKubernetes) -> JobOutput:
    async with serve(fake) as client:
        return await read_job_output_tail(
            namespace=NAMESPACE, job_name=JOB, container=CONTAINER, client=client
        )


def _lines(count: int, width: int = 0) -> bytes:
    return b"".join(f"line {n}".ljust(width).encode() + b"\n" for n in range(count))


async def test_reads_the_newest_pod_of_the_job() -> None:
    fake = FakeKubernetes(
        pods=[
            _pod("first-try", minute=1, log=b"first try\n"),
            _pod("last-try", minute=5, log=b"step-output-1\nstep-output-2\n"),
            _pod("other-job", minute=9, log=b"other\n", job="other-job"),
        ]
    )

    output = await _read(fake)

    assert output == JobOutput(text="step-output-1\nstep-output-2\n", truncated=False)
    assert fake.pod_lists == [f"{JOB_LABEL}={JOB}"]
    assert fake.log_reads == [
        {"container": CONTAINER, "tailLines": "201", "limitBytes": "65537"}
    ]


async def test_falls_back_to_the_legacy_job_name_label() -> None:
    fake = FakeKubernetes(
        pods=[
            _pod("old", minute=1, log=b"old\n", label=LEGACY_JOB_LABEL),
            _pod("new", minute=2, log=b"new\n", label=LEGACY_JOB_LABEL),
        ]
    )

    output = await _read(fake)

    assert output == JobOutput(text="new\n", truncated=False)
    assert fake.pod_lists == [f"{JOB_LABEL}={JOB}", f"{LEGACY_JOB_LABEL}={JOB}"]


async def test_prefers_the_newest_failed_pod_over_a_retry_still_starting() -> None:
    fake = FakeKubernetes(
        pods=[
            _pod("failed", minute=1, log=b"Traceback: boom\n"),
            _pod("retry", minute=2, log=b"", phase="Pending"),
        ]
    )

    assert (await _read(fake)).text == "Traceback: boom\n"


async def test_200_lines_are_kept_whole() -> None:
    fake = FakeKubernetes(pods=[_pod("pod", log=_lines(200))])

    assert await _read(fake) == JobOutput(text=_lines(200).decode(), truncated=False)


async def test_201_lines_drop_the_first_line_and_set_truncated() -> None:
    fake = FakeKubernetes(pods=[_pod("pod", log=_lines(300))])

    output = await _read(fake)

    assert output.truncated is True
    assert (
        output.text == b"".join(_lines(300).splitlines(keepends=True)[-200:]).decode()
    )


async def test_65537_bytes_keep_the_end_of_the_output_and_set_truncated() -> None:
    # Three lines of 65,537 bytes in all. Every read of 3 or more lines reaches
    # the byte limit, and halving goes from 3 lines to 1, so only the last line
    # is kept, although the last two lines would fit.
    log = b"a" * 40_000 + b"\n" + b"b" * 15_536 + b"\n" + b"c" * 9_998 + b"\n"
    assert len(log) == MAX_OUTPUT_BYTES + 1
    fake = FakeKubernetes(pods=[_pod("pod", log=log)])

    output = await _read(fake)

    assert output == JobOutput(text="c" * 9_998 + "\n", truncated=True)


async def test_long_lines_keep_the_last_lines_within_64_kib() -> None:
    log = _lines(250, width=999)
    fake = FakeKubernetes(pods=[_pod("pod", log=log)])

    output = await _read(fake)

    assert output.truncated is True
    assert output.text.endswith("line 249".ljust(999) + "\n")
    assert len(output.text.encode()) <= MAX_OUTPUT_BYTES
    assert [read["tailLines"] for read in fake.log_reads] == ["201", "100", "50"]
    assert output.text == b"".join(log.splitlines(keepends=True)[-50:]).decode()


async def test_one_line_longer_than_64_kib_keeps_at_most_64_kib() -> None:
    fake = FakeKubernetes(pods=[_pod("pod", log=b"z" * 100_000 + b"\n")])

    output = await _read(fake)

    assert output.truncated is True
    assert output.text == "z" * MAX_OUTPUT_BYTES


async def test_output_is_returned_as_written() -> None:
    # A JSON line and bytes that are not UTF-8 come back as text, unchanged.
    fake = FakeKubernetes(
        pods=[_pod("pod", log=b'{"level": "error", "msg": "boom"}\ncaf\xc3\n')]
    )

    output = await _read(fake)

    assert output == JobOutput(
        text='{"level": "error", "msg": "boom"}\ncaf�\n', truncated=False
    )


async def test_no_pod_raises_an_unreadable_error() -> None:
    fake = FakeKubernetes(pods=[_pod("other", job="other-job")])

    with pytest.raises(
        JobOutputUnreadableError,
        match=f"no pod of Job {JOB} was found in namespace {NAMESPACE}",
    ):
        await _read(fake)


@pytest.mark.parametrize(
    ("fake", "reason"),
    [
        (
            FakeKubernetes(list_error=(403, 'pods is forbidden: cannot list "pods"')),
            'the Kubernetes API answered 403: pods is forbidden: cannot list "pods"',
        ),
        (
            FakeKubernetes(
                pods=[_pod("pod", log=b"x\n")],
                log_error=(
                    400,
                    'container "user-job" in pod "pod" is waiting to start: '
                    "ContainerCreating",
                ),
            ),
            'the Kubernetes API answered 400: container "user-job" in pod "pod" '
            "is waiting to start: ContainerCreating",
        ),
    ],
    ids=["pod-list", "log-read"],
)
async def test_api_errors_raise_an_unreadable_error(
    fake: FakeKubernetes, reason: str
) -> None:
    with pytest.raises(JobOutputUnreadableError) as raised:
        await _read(fake)

    assert str(raised.value) == reason


async def test_an_unreachable_api_raises_an_unreadable_error() -> None:
    async with ApiClient(Configuration(host="http://127.0.0.1:1")) as client:
        with pytest.raises(JobOutputUnreadableError, match="ClientConnectorError"):
            await read_job_output_tail(
                namespace=NAMESPACE, job_name=JOB, container=CONTAINER, client=client
            )
