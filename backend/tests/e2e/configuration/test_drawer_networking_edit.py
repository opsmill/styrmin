"""E2E coverage for editing the Networking section through the unified
configuration drawer (011 / US2, T053).

Adds a CIDR to the IP allowlist via the drawer, applies the change, and
asserts the application Ingress's whitelist-source-range annotation (or
the equivalent Traefik Middleware in this cluster) reflects the new
CIDR.

The styrmin_resources cluster runs Traefik with the
``acl@kubernetescrd`` Middleware pattern rather than the
nginx ``whitelist-source-range`` annotation. We assert on whichever
representation is observable in the deployment namespace — the test
passes if either form carries the new CIDR.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import new_class
from playwright.async_api import expect
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [pytest.mark.shard_mutation_small]

RECONCILE_TIMEOUT_SECONDS = 480.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def networking_edit_environment(
    styrmin_resources: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
) -> AsyncGenerator[dict, None]:
    driver, client = session_scenario_driver
    cluster_id = styrmin_resources["cluster_id"]
    env = await driver.create_environment(
        name=f"drawer-net-{uuid.uuid4().hex[:8]}",
        cluster_id=cluster_id,
        config={},
    )
    yield {"environment_id": str(env.id), "client": client}


@pytest.fixture(scope="module")
async def networking_edit_deployment(
    networking_edit_environment: dict,
    session_scenario_driver: tuple[ScenarioDriver, StyrminClient],
    simple_app_image: str,  # noqa: ARG001 — builds the image
    vcluster: dict,
) -> dict:
    driver, _ = session_scenario_driver
    deployment = await driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=networking_edit_environment["environment_id"],
        name="drawer-net",
    )
    deployment = await driver.wait_for_deployment_running(
        deployment_id=deployment.id, timeout=RECONCILE_TIMEOUT_SECONDS
    )
    return {
        "deployment_id": str(deployment.id),
        "namespace": f"styrmin-{deployment.id}",
        "kubeconfig_path": vcluster["kubeconfig_path"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_allowlist_resource(
    *, namespace: str, expected_cidr: str, kubeconfig_path: str, timeout: float
) -> None:
    """Poll the deployment namespace until ``expected_cidr`` shows up in
    one of the supported allowlist representations:

    * a Traefik ``Middleware/acl`` object's ``spec.ipAllowList.sourceRange``
      (the form rendered by the in-cluster styrmin chart), or
    * an Ingress annotation
      ``nginx.ingress.kubernetes.io/whitelist-source-range`` containing
      ``expected_cidr`` as a substring (nginx-controller form, kept as a
      fallback so the test stays portable across clusters).

    The two forms are equivalent end-to-end: both gate ingress traffic at
    the L7 layer on the operator-set CIDR list.
    """
    kr8s_api = await kr8s.asyncio.api(kubeconfig=kubeconfig_path)
    middleware_cls = new_class(  # noqa: N806 — kr8s factory mirrors K8s kind casing
        kind="Middleware",
        version="traefik.io/v1alpha1",
        namespaced=True,
        asyncio=True,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 1) Traefik Middleware.
        try:
            mw = await middleware_cls.get(name="acl", namespace=namespace, api=kr8s_api)
            sources = (
                mw.raw.get("spec", {}).get("ipAllowList", {}).get("sourceRange", [])
                or []
            )
            if expected_cidr in sources:
                return
        except Exception:
            pass

        # 2) Nginx-style annotation on the application Ingress.
        ingresses: list[AsyncIngress] = [
            ing
            async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
            if isinstance(ing, AsyncIngress)
        ]
        for ing in ingresses:
            annotations = ing.metadata.get("annotations", {}) or {}
            value = annotations.get(
                "nginx.ingress.kubernetes.io/whitelist-source-range"
            )
            if value and expected_cidr in value:
                return

        await asyncio.sleep(3.0)

    raise AssertionError(
        f"IP allowlist update did not propagate to a Middleware or Ingress "
        f"annotation in namespace {namespace} within {timeout}s "
        f"(expected CIDR={expected_cidr!r})"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Networking section is not currently rendered in the edit drawer "
        "(see frontend/src/lib/configuration-types.ts::DRAWER_SECTION_GROUPS). "
        "The Settings tab read view still shows networking; re-enable this "
        "test when the Networking section is re-introduced in the drawer."
    ),
)
@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Networking section. No SDK "
        "equivalent for 'open drawer / Add CIDR / Apply' — the wire-level "
        "mutation is already covered by the standalone ingress test."
    ),
)
async def test_drawer_networking_edit(
    networking_edit_environment: dict,
    networking_edit_deployment: dict,
    session_ui_page: "Page",
) -> None:
    page = session_ui_page
    environment_id = networking_edit_environment["environment_id"]
    deployment_id = networking_edit_deployment["deployment_id"]
    namespace = networking_edit_deployment["namespace"]
    kubeconfig_path = networking_edit_deployment["kubeconfig_path"]

    new_cidr = "10.99.0.0/16"

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()

    await page.locator("[data-testid=section-nav-networking]").click()

    await page.locator("[data-testid=add-cidr]").click()
    cidr_input = page.locator("[data-testid=cidr-0]")
    await expect(cidr_input).to_be_visible()
    await cidr_input.fill(new_cidr)
    await cidr_input.press("Tab")

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # Diff rows render the human-readable ``label`` (not ``path``).
    net_section = diff_dialog.locator("[data-testid=diff-section-networking]")
    await expect(net_section).to_be_visible()
    await expect(net_section).to_contain_text("IP whitelist")

    impact_section = diff_dialog.locator("[data-testid=diff-dialog-impact-section]")
    await expect(impact_section).to_be_visible()
    await expect(impact_section).to_contain_text(
        "Ingress controller allowlist will be reconfigured"
    )

    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    await _wait_for_allowlist_resource(
        namespace=namespace,
        expected_cidr=new_cidr,
        kubeconfig_path=kubeconfig_path,
        timeout=RECONCILE_TIMEOUT_SECONDS,
    )
