"""E2E test for the Pods tab on the deployment detail page (spec 012).

Drives the happy path through the UI:
- Open the deployment detail page for a RUNNING simple-app deployment
- Switch to the Pods tab
- Wait for at least one pod row with phase RUNNING
- Expand that pod row
- Open the (collapsed-by-default) Commands section
- Click Copy on the logs command
- Assert the clipboard contains the expected ``kubectl logs`` invocation
  with the deployment's namespace and the pod's name

UI-only because the underlying ``podStatuses`` query is already covered by
service-layer tests; the api variant of this scenario would only re-exercise
the same SDK call without adding coverage of the tab, copy, or namespace
substitution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.pages.pods_tab import PodsTabPage

if TYPE_CHECKING:
    from playwright.async_api import Page


@pytest.mark.ci
@pytest.mark.ui_only(
    reason="Pods tab UI flow — SDK exposes podStatuses already and is "
    "covered by service-layer tests; api variant would only re-run the SDK call.",
)
async def test_pods_tab_copy_logs_command(
    deployed_simple_app: dict,
    session_ui_page: "Page",
    scenario_environment_id: str,
) -> None:
    deployment_id = deployed_simple_app["deployment_id"]
    namespace = deployed_simple_app["namespace"]

    detail_page = DeploymentDetailPage(session_ui_page)
    pods_tab = PodsTabPage(session_ui_page)

    # 1. Browser clipboard reads require an explicit grant in Chromium. The
    # Copy button still writes without it, but the assertion below cannot
    # read back without permission.
    await pods_tab.grant_clipboard_permissions()

    # 2. Navigate to the deployment detail page and confirm the deployment
    # is RUNNING before switching tabs — saves on flaky waits inside the
    # tab and matches the PRD's preconditions.
    await detail_page.goto(
        environment_id=scenario_environment_id,
        deployment_id=deployment_id,
    )
    await detail_page.wait_for_status(expected="running", timeout=120.0)

    # 3. Open the Pods tab and wait for at least one RUNNING pod row.
    await pods_tab.open()
    pod_name = await pods_tab.wait_for_at_least_one_running_pod(timeout=120.0)

    # 4. Expand the row and open the Commands collapsible.
    await pods_tab.expand_pod(pod_name)
    await pods_tab.open_commands_section()

    # 5. Copy the logs command and verify the exact string lands on the
    # clipboard. The format is owned by buildKubectlCommand; this only
    # checks that the right namespace and pod name are substituted in.
    await pods_tab.click_copy_logs()
    clipboard_text = await pods_tab.read_clipboard()
    expected = f"kubectl logs --namespace {namespace} {pod_name} --all-containers"
    assert clipboard_text == expected, (
        f"clipboard should contain the namespace-and-pod-name-substituted "
        f"logs command. expected={expected!r}, got={clipboard_text!r}"
    )
