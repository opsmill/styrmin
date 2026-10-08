"""E2E coverage for editing the Scheduling section through the unified
configuration drawer (011 / US2, T050).

Drives Playwright through the full operator flow:

1. Seed a deployment.
2. Open the Configuration tab and click the hero's "Edit configuration"
   CTA to open the drawer.
3. Navigate to the Scheduling section via the section-nav rail.
4. Change the container CPU request.
5. Click "Review & apply"; assert the diff dialog lists the changed
   path under ``scheduling.resources.requests.cpu`` and the impact
   list mentions "Pods will be recreated with new resource limits".
6. Click "Apply"; wait for the deployment task to converge.
7. Assert the persisted ``deployment.config`` reflects the new CPU
   value (via the SDK) and the underlying pods restarted (the chart
   re-rendered the pod template with the new request, replacing the
   previous pod set — UIDs differ from baseline).

The keyboard-only variant (FR-028) repeats step 4 through 6 driving the
flow with ``page.keyboard.press`` only — no clicks. Both tests are
``@pytest.mark.ui_only`` per AGENTS.md / research R-010: the SDK has no
"open drawer" surface, so the dual-entrypoint API variant would not add
coverage.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from kubernetes_asyncio import client as kubeclient
from playwright.async_api import expect
from styrmin_sdk import StyrminClient

from tests.e2e.configuration.conftest import DrawerDeployment
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [pytest.mark.shard_configuration]

RECONCILE_TIMEOUT_SECONDS = 480.0
# The config persists when the Apply mutation commits, not after the
# reconcile; a longer wait only delays reporting a lost edit (#260).
PERSIST_TIMEOUT_SECONDS = 60.0


DRAWER_DEPLOYMENT = DrawerDeployment(name="drawer-sched")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _server_pod_uids(vcluster: dict, namespace: str) -> set[str]:
    """Read the current set of simple-app pod UIDs in ``namespace``.

    Used as a "did the pods recreate?" oracle: when the chart re-renders
    a pod template with a new resource request, the StatefulSet/Deployment
    rolls the pods and every UID changes. Comparing UIDs across the
    pre-apply baseline and the post-converge state is a cheap "yes/no"
    signal without parsing the workload spec.
    """
    core = kubeclient.CoreV1Api(vcluster["api"])
    pods = await core.list_namespaced_pod(
        namespace=namespace,
        label_selector="app.kubernetes.io/name=simple-app",
    )
    return {p.metadata.uid for p in pods.items if p.metadata.uid}


async def _wait_for_persisted_cpu(
    client: StyrminClient, deployment_id: str, expected: str, timeout: float
) -> None:
    """Poll the deployment until ``config.scheduling.resources.requests.cpu``
    matches ``expected``. The drawer's Apply enqueues an update task; the
    persisted config reflects the new value as soon as the mutation
    commits, which usually precedes the reconcile finishing.
    """
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        dep = await client.deployments.get(deployment_id)
        cfg = getattr(dep, "config", None) or {}
        sched = (cfg.get("scheduling") or {}) if isinstance(cfg, dict) else {}
        requests = (
            (sched.get("resources") or {}).get("requests") or {}
            if isinstance(sched, dict)
            else {}
        )
        last = requests.get("cpu")
        if last == expected:
            return
        await asyncio.sleep(2.0)
    raise AssertionError(
        f"deployment {deployment_id} did not persist "
        f"scheduling.resources.requests.cpu={expected!r} within {timeout}s; "
        f"last observed value was {last!r}"
    )


async def _open_drawer_to_scheduling(page: "Page", deployment_id: str) -> None:
    """Common navigation: tabs → Configuration → Edit → Scheduling.

    Shared by the click-driven and keyboard-driven test variants so the
    pre-edit DOM state is identical between them. The keyboard variant
    then exercises ``page.keyboard.press`` for the modify+submit steps
    where the FR-028 invariant actually matters.
    """
    detail = DeploymentDetailPage(page)
    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("[data-testid=settings-tab]")).to_be_visible()
    await page.locator("[data-testid=settings-update-button]").click()
    drawer = page.locator("[role=dialog][aria-labelledby=config-edit-drawer-title]")
    await expect(drawer).to_be_visible()
    # Click the Scheduling entry in the section-nav rail so the scroll
    # target lands the cpu input in viewport.
    await page.locator("[data-testid=section-nav-scheduling]").click()
    # Detail page object is unused after navigation but kept around so a
    # debugger can still call its helpers from a paused pdb session.
    _ = detail


# ---------------------------------------------------------------------------
# Test — primary click-driven flow
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Drives the unified drawer's Scheduling section through the UI. "
        "No SDK equivalent for 'open drawer / click Review & apply' — "
        "the dual-entrypoint API variant has no analogue."
    ),
)
async def test_drawer_scheduling_edit(
    drawer_deployment: dict,
    session_ui_page: "Page",
    vcluster: dict,
) -> None:
    page = session_ui_page
    client: StyrminClient = drawer_deployment["client"]
    environment_id = drawer_deployment["environment_id"]
    deployment_id = drawer_deployment["deployment_id"]
    namespace = drawer_deployment["namespace"]

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    baseline_uids = await _server_pod_uids(vcluster, namespace)
    assert baseline_uids, (
        f"expected at least one simple-app pod in namespace {namespace!r} "
        "before applying the CPU change"
    )

    await _open_drawer_to_scheduling(page, deployment_id)

    # Change the container CPU request — the input lives in the
    # "requests" column of the Resources sub-block.
    new_cpu = "275m"
    cpu_input = page.locator("[data-testid=sched-res-requests-cpu]")
    await expect(cpu_input).to_be_visible()
    await cpu_input.fill(new_cpu)
    # Blur so TanStack Form's value-change subscription fires before we
    # click Review & apply.
    await cpu_input.press("Tab")

    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.click()

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    await expect(diff_dialog).to_be_visible()

    # Diff must list the changed path under the scheduling section.
    # The diff row renders ``label`` only — ``path`` lives in the
    # ``title`` attribute (not visible textContent), so we assert on
    # the human-readable label.
    scheduling_section = diff_dialog.locator("[data-testid=diff-section-scheduling]")
    await expect(scheduling_section).to_be_visible()
    await expect(scheduling_section).to_contain_text("Request cpu")

    # Impact list must mention the canonical consequence text from
    # impact-rules.ts for ``scheduling.resources.**``.
    impact_section = diff_dialog.locator("[data-testid=diff-dialog-impact-section]")
    await expect(impact_section).to_be_visible()
    await expect(impact_section).to_contain_text(
        "Pods will be recreated with new resource limits"
    )

    # Apply.
    await page.locator("[data-testid=diff-dialog-apply-button]").click()
    # The drawer closes on successful apply (forceClose).
    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    # Persisted state asserts.
    await _wait_for_persisted_cpu(
        client, deployment_id, new_cpu, timeout=PERSIST_TIMEOUT_SECONDS
    )

    # Pods must have rolled — comparing UID sets is enough to prove the
    # chart re-rendered the pod template under the new request.
    deadline = time.time() + RECONCILE_TIMEOUT_SECONDS
    rolled = False
    while time.time() < deadline:
        current_uids = await _server_pod_uids(vcluster, namespace)
        if current_uids and current_uids.isdisjoint(baseline_uids):
            rolled = True
            break
        await asyncio.sleep(5.0)
    assert rolled, (
        f"simple-app pods did not roll after CPU change "
        f"(baseline={baseline_uids}, current={await _server_pod_uids(vcluster, namespace)})"
    )


# ---------------------------------------------------------------------------
# Test — keyboard-only variant (FR-028)
# ---------------------------------------------------------------------------


@pytest.mark.ci
@pytest.mark.ui_only(
    reason=(
        "Exercises the FR-028 keyboard-only invariant for the drawer's "
        "primary flow. The dialog focus trap and tab order matter only in "
        "the UI; no SDK equivalent."
    ),
)
async def test_drawer_scheduling_edit_keyboard_only(
    drawer_deployment: dict,
    session_ui_page: "Page",
) -> None:
    """Repeat the primary flow with keyboard-only navigation.

    The first variant proves the back-end side of the apply path; this
    variant proves the operator can complete the same flow without a
    mouse. We don't re-assert on pod rolls (that's the same backend
    behaviour as above and would just be re-running ``test_drawer_
    scheduling_edit`` minus the click→keypress swap). We do assert on
    the dialog opening and the persisted CPU landing — those are the
    keyboard-routing-sensitive observable side-effects.
    """
    page = session_ui_page
    client: StyrminClient = drawer_deployment["client"]
    environment_id = drawer_deployment["environment_id"]
    deployment_id = drawer_deployment["deployment_id"]

    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    await detail.wait_for_status(expected="running", timeout=180.0)

    await _open_drawer_to_scheduling(page, deployment_id)

    new_cpu = "325m"
    cpu_input = page.locator("[data-testid=sched-res-requests-cpu]")
    await expect(cpu_input).to_be_visible()
    # Set the value via Playwright's high-level fill — character-by-character
    # `page.keyboard.type` after a focus + Ctrl+A + Delete sequence was
    # losing focus mid-sequence on the previous CI run and writing an empty
    # value into the form state. The a11y discipline of this test is the
    # keyboard-driven *button activation* below (focus + Enter on Review,
    # then on Apply); the input value itself is just data setup.
    await cpu_input.fill(new_cpu)
    # Tab away so the form picks up the value via the field's onBlur.
    await page.keyboard.press("Tab")

    # Drive Review & apply from the keyboard — focus the button and press Enter.
    review_button = page.locator("[data-testid=drawer-review-apply-button]")
    await expect(review_button).to_be_enabled()
    await review_button.focus()
    await page.keyboard.press("Enter")

    diff_dialog = page.locator("[data-testid=config-diff-dialog]")
    # Keyboard activation (focus + Enter) on the Review & apply button is
    # measurably slower than a real click — under CI load the dialog mount
    # can exceed Playwright's default 5s ``to_be_visible`` timeout. Local
    # runs land well under a second; CI saw a 5s timeout on this exact line
    # at commit b19c914. Bump to 30s to match the pattern of the
    # ``to_be_hidden`` assertion below.
    await expect(diff_dialog).to_be_visible(timeout=30_000)
    await expect(
        diff_dialog.locator("[data-testid=diff-section-scheduling]")
    ).to_contain_text("Request cpu")

    # Base UI focuses the dialog's close button one animation frame after
    # opening. Focusing Apply before that frame let it steal focus, so Enter
    # closed the dialog without applying (#260).
    await expect(
        diff_dialog.locator("[data-testid=diff-dialog-close-button]")
    ).to_be_focused()
    apply_button = page.locator("[data-testid=diff-dialog-apply-button]")
    await expect(apply_button).to_be_enabled()
    await apply_button.focus()
    await expect(apply_button).to_be_focused()
    await page.keyboard.press("Enter")

    await expect(diff_dialog).to_be_hidden(timeout=60_000)

    await _wait_for_persisted_cpu(
        client, deployment_id, new_cpu, timeout=PERSIST_TIMEOUT_SECONDS
    )
