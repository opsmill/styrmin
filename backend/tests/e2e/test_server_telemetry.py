"""E2E coverage for the server's daily telemetry report (spec 020, issue #274).

The chart points ``STYRMIN_TELEMETRY_ENDPOINT`` at the in-cluster sink of the
``telemetry_sink`` fixture. The test runs ``styrmin telemetry show`` in the server
pod, starts the catalogued daily flow through the Prefect API, as the scheduler
would, and inspects the report the sink received.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any
from uuid import UUID

import httpx
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Service as AsyncService
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.filters import LogFilter, LogFilterFlowRunId
from prefect.client.schemas.objects import FlowRun

from tests.e2e.conftest import _portforward, _wait_for_http

pytestmark = [pytest.mark.shard_general]

_TELEMETRY_DEPLOYMENT = "send_telemetry_report/send_telemetry_report"
_SERVER_POD_SELECTOR = (
    "app.kubernetes.io/component=server,app.kubernetes.io/name=styrmin"
)
_FLOW_RUN_TIMEOUT_SECONDS = 180.0

# FR-006 keys in contract order (contracts/telemetry-report-wire-format.md).
_REPORT_DATA_KEYS = [
    "install_id",
    "styrmin_version",
    "python_version",
    "os_family",
    "arch",
    "cluster_count",
    "environment_count",
    "deployment_count",
    "drivers",
]
_DRIVER_ENTRY_KEYS = ["name", "version", "source_type", "deployment_count"]
_ENVELOPE_KEYS = ["data", "checksum", "kind", "payload_format"]


async def _sink_reports(sink_url: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{sink_url}/reports", timeout=10)
    response.raise_for_status()
    return response.json()


async def _kubectl(kubeconfig_path: str, *args: str) -> str:
    """Run kubectl in the ``styrmin`` namespace without blocking the port-forwards; return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "kubectl",
        "--kubeconfig",
        kubeconfig_path,
        "-n",
        "styrmin",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, (
        f"kubectl {' '.join(args)} exited {proc.returncode}: "
        f"{stderr.decode(errors='replace')}"
    )
    return stdout.decode()


async def _telemetry_show(kubeconfig_path: str) -> dict[str, Any]:
    """Run ``styrmin telemetry show`` in the server pod and parse its output."""
    pod = (
        await _kubectl(
            kubeconfig_path,
            "get",
            "pods",
            "-l",
            _SERVER_POD_SELECTOR,
            "-o",
            "jsonpath={.items[0].metadata.name}",
        )
    ).strip()
    assert pod, "styrmin-server pod not found in vcluster"
    output = await _kubectl(
        kubeconfig_path,
        "exec",
        pod,
        "-c",
        "styrmin-server",
        "--",
        "styrmin",
        "telemetry",
        "show",
    )
    return json.loads(output)


async def _flow_run_logs(client: PrefectClient, flow_run_id: UUID) -> str:
    logs = await client.read_logs(
        log_filter=LogFilter(flow_run_id=LogFilterFlowRunId(any_=[flow_run_id]))
    )
    return "\n".join(f"{log.level} {log.message}" for log in logs)


async def _run_telemetry_flow(kubeconfig_path: str) -> tuple[FlowRun, str]:
    """Start the daily telemetry deployment once; return the final run and its logs."""
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    prefect_service = await AsyncService.get(
        "prefect-server", namespace="styrmin", api=kr8s_api
    )
    async with _portforward(prefect_service, remote_port=4200) as prefect_port:
        prefect_url = f"http://localhost:{prefect_port}/api"
        await _wait_for_http(f"{prefect_url}/health", timeout=60.0)

        async with PrefectClient(api=prefect_url) as client:
            deployment = await client.read_deployment_by_name(_TELEMETRY_DEPLOYMENT)
            flow_run = await client.create_flow_run_from_deployment(
                deployment_id=deployment.id
            )

            deadline = time.monotonic() + _FLOW_RUN_TIMEOUT_SECONDS
            run = await client.read_flow_run(flow_run.id)
            while not (run.state and run.state.is_final()):
                if time.monotonic() > deadline:
                    state = run.state_type.value if run.state_type else None
                    raise AssertionError(
                        f"Telemetry flow run {flow_run.id} did not finish within "
                        f"{_FLOW_RUN_TIMEOUT_SECONDS}s (last state: {state})"
                    )
                await asyncio.sleep(2)
                run = await client.read_flow_run(flow_run.id)

            return run, await _flow_run_logs(client, flow_run.id)


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Starts the daily flow through the Prefect API and reads the report "
    "from the in-cluster sink; Styrmin has no UI for telemetry."
)
async def test_server_sends_daily_report(
    deployed_simple_app: dict,
    telemetry_sink: str,
) -> None:
    """One run of the daily flow sends one report with the FR-006 data to the endpoint.

    ``styrmin telemetry show`` sends nothing and prints the same data (FR-013).
    """
    kubeconfig_path = deployed_simple_app["kubeconfig_path"]
    reports_before = await _sink_reports(telemetry_sink)

    shown_data = await _telemetry_show(kubeconfig_path)
    reports_after_show = await _sink_reports(telemetry_sink)
    assert len(reports_after_show) == len(reports_before), (
        f"styrmin telemetry show sent a report: "
        f"{reports_after_show[len(reports_before) :]}"
    )

    run, run_logs = await _run_telemetry_flow(kubeconfig_path)

    state = run.state_type.value if run.state_type else None
    assert state == "COMPLETED", (
        f"Telemetry flow run ended {state}: {run.state.message if run.state else ''}\n"
        f"Flow run logs:\n{run_logs}"
    )

    reports_after = await _sink_reports(telemetry_sink)
    new_reports = reports_after[len(reports_before) :]
    assert len(new_reports) == 1, (
        f"Expected exactly one new report at the sink, got {len(new_reports)}: "
        f"{new_reports}\nFlow run logs:\n{run_logs}"
    )
    report = new_reports[0]

    assert list(report) == _ENVELOPE_KEYS
    assert report["kind"] == "styrmin"
    assert report["payload_format"] == "1.0"
    data = report["data"]
    expected_checksum = hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()
    assert report["checksum"] == expected_checksum

    assert list(data) == _REPORT_DATA_KEYS
    assert data["styrmin_version"] != "unknown"
    assert data["cluster_count"] == 1

    drivers = data["drivers"]
    for entry in drivers:
        assert list(entry) == _DRIVER_ENTRY_KEYS, entry
    assert any(
        entry["name"] == "simple-app" and entry["deployment_count"] >= 1
        for entry in drivers
    ), f"No simple-app driver entry with a live deployment: {drivers}"

    assert data == shown_data, (
        "The sent data differs from the output of styrmin telemetry show"
    )
