"""A fake Kubernetes API for tests that read a failed Job's output (spec 019, research D10).

It answers pod lists, pod log reads (with the kubelet's ``tailLines`` and
``limitBytes`` rules), Job reads, creation, deletion and status, so the real
``kubernetes_asyncio`` client runs against it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestServer
from kubernetes_asyncio.client import Configuration
from kubernetes_asyncio.client.api_client import ApiClient

#: The suffix the fake adds to a Job's ``generateName``.
GENERATED_SUFFIX = "x7k2p"


@dataclass
class FakePod:
    name: str
    labels: dict[str, str]
    created: datetime
    #: Each container's log, as the kubelet stores it.
    logs: dict[str, bytes] = field(default_factory=dict)
    phase: str = "Failed"


@dataclass
class FakeKubernetes:
    """Pods with logs, and Jobs that fail unless ``job_succeeds`` is set."""

    pods: list[FakePod] = field(default_factory=list)
    #: ``(HTTP status, message)`` answered to every pod list when set.
    list_error: tuple[int, str] | None = None
    #: ``(HTTP status, message)`` answered to every log read when set.
    log_error: tuple[int, str] | None = None
    job_succeeds: bool = False
    #: Each Job by name, with ``metadata.uid``; a Job added by a test may set its ``status``.
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: How many reads still find a deleted Job, as while Kubernetes removes its
    #: pods first; ``None`` keeps it for ever.
    reads_until_deleted: int | None = 0
    #: When set, another writer creates a new Job of the same name as soon as
    #: a deleted Job is removed.
    recreated_after_delete: bool = False
    #: When set, another writer deletes the Job before its first status read.
    removed_before_status: bool = False
    #: The pods that the Job controller starts: each one joins ``pods`` when
    #: the Job named by its ``batch.kubernetes.io/job-name`` label is created.
    pods_on_create: list[FakePod] = field(default_factory=list)
    #: ``(request, Job name)`` of each Job request, in order: ``read``,
    #: ``delete``, ``create`` or ``status``.
    job_requests: list[tuple[str, str]] = field(default_factory=list)
    #: The body of each Job delete, in order.
    job_deletes: list[dict[str, Any]] = field(default_factory=list)
    #: The reads left before each deleted Job is removed.
    _deleting: dict[str, int | None] = field(
        default_factory=dict, init=False, repr=False
    )
    #: The label selector of each pod list, in order.
    pod_lists: list[str] = field(default_factory=list)
    #: The query of each log read, in order.
    log_reads: list[dict[str, str]] = field(default_factory=list)

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/v1/namespaces/{namespace}/pods", self._list_pods)
        app.router.add_get(
            "/api/v1/namespaces/{namespace}/pods/{pod}/log", self._read_log
        )
        app.router.add_post(
            "/apis/batch/v1/namespaces/{namespace}/jobs", self._create_job
        )
        app.router.add_get(
            "/apis/batch/v1/namespaces/{namespace}/jobs/{job}", self._read_job
        )
        app.router.add_delete(
            "/apis/batch/v1/namespaces/{namespace}/jobs/{job}", self._delete_job
        )
        app.router.add_get(
            "/apis/batch/v1/namespaces/{namespace}/jobs/{job}/status",
            self._read_job_status,
        )
        return app

    async def _list_pods(self, request: web.Request) -> web.Response:
        selector = request.query.get("labelSelector", "")
        self.pod_lists.append(selector)
        if self.list_error is not None:
            return _status(*self.list_error)
        key, _, value = selector.partition("=")
        items = [_pod_json(pod) for pod in self.pods if pod.labels.get(key) == value]
        return web.json_response(
            {"apiVersion": "v1", "kind": "PodList", "metadata": {}, "items": items}
        )

    async def _read_log(self, request: web.Request) -> web.Response:
        self.log_reads.append(dict(request.query))
        if self.log_error is not None:
            return _status(*self.log_error)
        name = request.match_info["pod"]
        pod = next((pod for pod in self.pods if pod.name == name), None)
        if pod is None:
            return _status(404, f'pods "{name}" not found')
        lines = pod.logs.get(request.query.get("container", ""), b"").splitlines(
            keepends=True
        )
        if "tailLines" in request.query:
            lines = lines[-int(request.query["tailLines"]) :]
        body = b"".join(lines)
        # The kubelet stops after limitBytes, so it keeps the start of the tail.
        if "limitBytes" in request.query:
            body = body[: int(request.query["limitBytes"])]
        return web.Response(body=body, content_type="text/plain")

    async def _create_job(self, request: web.Request) -> web.Response:
        job = await request.json()
        metadata = job.setdefault("metadata", {})
        name = metadata.get("name") or metadata["generateName"] + GENERATED_SUFFIX
        self.job_requests.append(("create", name))
        if name in self.jobs:
            return _status(409, f'jobs.batch "{name}" already exists')
        metadata["name"] = name
        metadata["uid"] = str(uuid4())
        self.jobs[name] = job
        started = [pod for pod in self.pods_on_create if _job_of(pod) == name]
        self.pods_on_create = [pod for pod in self.pods_on_create if pod not in started]
        self.pods.extend(started)
        return web.json_response(job, status=201)

    async def _read_job(self, request: web.Request) -> web.Response:
        name = request.match_info["job"]
        self.job_requests.append(("read", name))
        if name in self._deleting:
            reads_left = self._deleting[name]
            if reads_left is not None and reads_left <= 0:
                self._remove_deleted(name)
            elif reads_left is not None:
                self._deleting[name] = reads_left - 1
        job = self.jobs.get(name)
        if job is None:
            return _status(404, f'jobs.batch "{name}" not found')
        return web.json_response(job)

    async def _delete_job(self, request: web.Request) -> web.Response:
        name = request.match_info["job"]
        self.job_requests.append(("delete", name))
        options = await request.json() if request.can_read_body else {}
        self.job_deletes.append(options)
        job = self.jobs.get(name)
        if job is None:
            return _status(404, f'jobs.batch "{name}" not found')
        uid = (options.get("preconditions") or {}).get("uid")
        if uid is not None and uid != job["metadata"]["uid"]:
            return _status(409, f"Precondition failed: UID in precondition: {uid}")
        self._deleting[name] = self.reads_until_deleted
        if self.reads_until_deleted == 0:
            self._remove_deleted(name)
        return web.json_response(
            {"apiVersion": "v1", "kind": "Status", "status": "Success"}
        )

    def _remove_deleted(self, name: str) -> None:
        """Remove a deleted Job after its pods, as the ``Foreground`` propagation policy does."""
        del self._deleting[name]
        self.pods = [pod for pod in self.pods if _job_of(pod) != name]
        del self.jobs[name]
        if self.recreated_after_delete:
            self.jobs[name] = {"metadata": {"name": name, "uid": str(uuid4())}}

    async def _read_job_status(self, request: web.Request) -> web.Response:
        name = request.match_info["job"]
        self.job_requests.append(("status", name))
        if self.removed_before_status:
            self.jobs.pop(name, None)
        job = self.jobs.get(name)
        if job is None:
            return _status(404, f'jobs.batch "{name}" not found')
        if self.job_succeeds:
            status = {
                "succeeded": 1,
                "conditions": [{"type": "Complete", "status": "True"}],
            }
        else:
            status = {"failed": 1, "conditions": [{"type": "Failed", "status": "True"}]}
        return web.json_response({**job, "status": status})


@asynccontextmanager
async def serve(fake: FakeKubernetes) -> AsyncIterator[ApiClient]:
    """Serve ``fake`` and yield a Kubernetes API client that calls it."""
    async with TestServer(fake.app()) as server:
        configuration = Configuration(host=str(server.make_url("")).rstrip("/"))
        async with ApiClient(configuration) as client:
            yield client


def _job_of(pod: FakePod) -> str | None:
    return pod.labels.get("batch.kubernetes.io/job-name")


def _pod_json(pod: FakePod) -> dict[str, Any]:
    return {
        "metadata": {
            "name": pod.name,
            "labels": pod.labels,
            "creationTimestamp": pod.created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "status": {"phase": pod.phase},
    }


def _status(code: int, message: str) -> web.Response:
    return web.json_response(
        {
            "apiVersion": "v1",
            "kind": "Status",
            "metadata": {},
            "status": "Failure",
            "message": message,
            "code": code,
        },
        status=code,
    )
