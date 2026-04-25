"""UI E2E for the deployment delete dialog.

The cluster-teardown / tombstone-state assertions live in
``test_deployment_deletion.py`` (api_only). This file covers only the
UI surface added in the delete-deployment feature: the header Delete
button, the disposition radios, and the destructive confirm button.
The post-mutation tombstone state is verified through the SDK so the
test does not depend on UI rendering of terminal states.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from playwright.async_api import Page
from styrmin_sdk import StyrminClient

from tests.e2e.conftest import _wait_for_deployment_running
from tests.e2e.pages.deployment_detail import DeploymentDetailPage
from tests.e2e.test_deployment_deletion import _wait_for_deployment_deleted


@pytest.fixture
async def fresh_simple_app_for_ui(
    styrmin_resources: dict, simple_app_image: str, vcluster: dict
) -> dict:
    """Per-test deployment; mirrors ``fresh_simple_app`` but isolated so
    the api_only and ui_only files can evolve independently.
    """
    client: StyrminClient = styrmin_resources["client"]
    environment_id = styrmin_resources["environment_id"]

    unique_suffix = uuid4().hex[:8]
    deployment_name = f"delete-ui-e2e-{unique_suffix}"
    service_override = f"simple-app-delete-ui-e2e-{unique_suffix}"

    task = await client.deployments.create(
        driver="simple-app",
        version="0.1.0",
        environment_id=environment_id,
        name=deployment_name,
        service_name_overrides=[
            {
                "driverServiceName": "simple-app",
                "overrideName": service_override,
            }
        ],
    )
    deployment_id = task.deployment_id
    assert deployment_id is not None
    await _wait_for_deployment_running(client, deployment_id)

    return {
        "deployment_id": str(deployment_id),
        "environment_id": environment_id,
    }


@pytest.mark.ci
@pytest.mark.ui_only(
    reason="exercises the deployment-detail Delete dialog (header button, "
    "RETAIN/REMOVE radios, destructive confirm). Tombstone-state and "
    "cluster-teardown invariants are covered by the api_only suite."
)
async def test_delete_deployment_via_ui_dialog_retain(
    styrmin_resources: dict,
    fresh_simple_app_for_ui: dict,
    session_ui_page: Page,
) -> None:
    """Drive the new delete dialog end-to-end and verify the deployment
    reaches the DELETED terminal state through the SDK.
    """
    assert session_ui_page is not None, (
        "session_ui_page is None — this test must run with driver_mode=ui"
    )
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = fresh_simple_app_for_ui["deployment_id"]
    environment_id = fresh_simple_app_for_ui["environment_id"]

    page_object = DeploymentDetailPage(session_ui_page)
    await page_object.goto(environment_id=environment_id, deployment_id=deployment_id)
    await page_object.wait_for_status(expected="running")

    await page_object.delete_deployment(disposition="RETAIN")

    # The SDK is the ground truth for tombstone state — UI rendering of
    # the terminal state is incidental to this test.
    await _wait_for_deployment_deleted(client, deployment_id)
    tombstone = await client.deployments.get(deployment_id)
    assert tombstone.status == "deleted"
