"""Read the end of a failed Job's output before the Job can be removed.

See specs/019-task-steps/contracts/flow-step-reporter.md "Job output" and
research D10.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from fast_depends import Depends, inject
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client import V1Pod
from kubernetes_asyncio.client.api_client import ApiClient, ApiException

from styrmin_backend.domain.steps import (
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    truncate_output,
)

from .dependency import get_api_client
from .exceptions import JobOutputUnreadableError

#: One line or one byte more than Styrmin keeps tells that earlier output was cut.
TAIL_LINES = MAX_OUTPUT_LINES + 1
LIMIT_BYTES = MAX_OUTPUT_BYTES + 1
#: The Job controller's pod labels, current first, then the legacy one.
_JOB_NAME_LABELS = ("batch.kubernetes.io/job-name", "job-name")
_NO_TIME = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class JobOutput:
    """The end of a Job's output and whether earlier output was cut."""

    text: str
    truncated: bool


@inject
async def read_job_output_tail(
    namespace: str,
    job_name: str,
    container: str,
    client: ApiClient = Depends(get_api_client),
) -> JobOutput:
    """Read the end of ``container``'s output in the newest pod of the Job ``job_name``.

    Keeps at most the last ``MAX_OUTPUT_LINES`` lines and ``MAX_OUTPUT_BYTES``
    bytes. Raises ``JobOutputUnreadableError`` with the reason when no pod
    exists or a Kubernetes API call fails.
    """
    core_api = kubeclient.CoreV1Api(client)
    try:
        pod_name = await _newest_pod_name(core_api, namespace, job_name)
        tail_lines = TAIL_LINES
        raw = await _read_log(core_api, namespace, pod_name, container, tail_lines)
        byte_cut = len(raw) >= LIMIT_BYTES
        # The byte limit keeps the start of the tail; fewer lines keep its end.
        while len(raw) >= LIMIT_BYTES and tail_lines > 1:
            tail_lines //= 2
            raw = await _read_log(core_api, namespace, pod_name, container, tail_lines)
    except JobOutputUnreadableError:
        raise
    except ApiException as exc:
        raise JobOutputUnreadableError(
            _api_reason(exc.status, exc.reason, exc.body)
        ) from exc
    except Exception as exc:  # noqa: BLE001 - reading the output never hides the Job's failure
        raise JobOutputUnreadableError(f"{type(exc).__name__}: {exc}") from exc
    text, truncated = truncate_output(raw.decode(errors="replace"))
    return JobOutput(text=text, truncated=truncated or byte_cut)


async def _newest_pod_name(
    core_api: kubeclient.CoreV1Api, namespace: str, job_name: str
) -> str:
    for label in _JOB_NAME_LABELS:
        pods = await core_api.list_namespaced_pod(
            namespace=namespace, label_selector=f"{label}={job_name}"
        )
        if pods.items:
            return max(pods.items, key=_newest_failed_first).metadata.name
    raise JobOutputUnreadableError(
        f"no pod of Job {job_name} was found in namespace {namespace}"
    )


def _newest_failed_first(pod: V1Pod) -> tuple[bool, datetime]:
    """Prefer a failed pod to a retry that has not ended, then the newest."""
    failed = pod.status is not None and pod.status.phase == "Failed"
    return failed, pod.metadata.creation_timestamp or _NO_TIME


async def _read_log(
    core_api: kubeclient.CoreV1Api,
    namespace: str,
    pod_name: str,
    container: str,
    tail_lines: int,
) -> bytes:
    # Raw bytes: the client decodes strictly and parses a one-line JSON log as JSON.
    response = await core_api.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container=container,
        tail_lines=tail_lines,
        limit_bytes=LIMIT_BYTES,
        _preload_content=False,
    )
    try:
        body = await response.read()
    finally:
        response.release()
    if not 200 <= response.status < 300:
        raise JobOutputUnreadableError(
            _api_reason(response.status, response.reason, body)
        )
    return body


def _api_reason(
    status: int | None, reason: str | None, body: str | bytes | None
) -> str:
    """The message of the Kubernetes ``Status`` answer, else the HTTP reason."""
    try:
        message = json.loads(body or "")["message"]
    except ValueError, TypeError, KeyError:
        message = reason
    return f"the Kubernetes API answered {status}: {message}"
