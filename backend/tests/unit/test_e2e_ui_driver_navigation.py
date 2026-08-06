"""``UiScenarioDriver`` deployment-page binding for the backup/restore flow.

Unit-scoped for a reason the E2E cannot cover: the interesting branch is the one
where the shared Playwright ``Page`` has *drifted* to a different deployment than
the driver is bound to. Every E2E path reaches ``create_backup`` immediately
after a call that navigated the page itself, so the drift branch is unreachable
from a passing scenario — and the bug it guards against (backing up whichever
deployment a sibling test happened to leave on screen) shows up as a scenario
that passes for the wrong reason rather than as a failure.

Driving it here with a fake page makes all three branches deterministic and puts
them in the unit job, which costs no cluster.
"""

from __future__ import annotations

import pytest

from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.ui_driver import UiScenarioDriver, _deployment_id_from_url

ENV_ID = "11111111-1111-1111-1111-111111111111"
BOUND_DEPLOYMENT = "22222222-2222-2222-2222-222222222222"
OTHER_DEPLOYMENT = "33333333-3333-3333-3333-333333333333"


class _FakePage:
    """Minimal stand-in exposing the one attribute the driver reads."""

    def __init__(self, url: str) -> None:
        self.url = url


class _RecordingDetailPage:
    """Records ``goto`` calls instead of driving a browser."""

    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.gotos: list[tuple[str, str]] = []

    async def goto(self, *, environment_id: str, deployment_id: str) -> None:
        self.gotos.append((environment_id, deployment_id))
        # Mirror the real page object's side effect so a caller that navigates
        # then re-checks the URL sees the new location.
        self._page.url = (
            f"http://styrmin/environments/{environment_id}/deployments/{deployment_id}"
        )


def _driver(
    *,
    url: str,
    bound_deployment: str | None,
    environment_id: str | None = ENV_ID,
) -> tuple[UiScenarioDriver, _RecordingDetailPage]:
    page = _FakePage(url)
    driver = UiScenarioDriver(page=page, base_url="http://styrmin")  # type: ignore[arg-type]
    detail = _RecordingDetailPage(page)
    driver._deployment_detail = detail  # type: ignore[assignment]
    driver._deployment_id = bound_deployment
    driver._environment_id = environment_id
    return driver, detail


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"http://s/environments/{ENV_ID}/deployments/{BOUND_DEPLOYMENT}",
            BOUND_DEPLOYMENT,
        ),
        # Query strings and trailing sub-paths must not defeat the parse — the
        # deployment detail page appends a tab param, and pods/config live under
        # further path segments.
        (
            f"http://s/environments/{ENV_ID}/deployments/{BOUND_DEPLOYMENT}?tab=backups",
            BOUND_DEPLOYMENT,
        ),
        (f"http://s/deployments/{BOUND_DEPLOYMENT}", BOUND_DEPLOYMENT),
        (f"http://s/environments/{ENV_ID}", None),
        ("http://s/", None),
        # "deployments" as the final segment is the *list* page, not a detail page.
        (f"http://s/environments/{ENV_ID}/deployments", None),
    ],
)
def test_deployment_id_from_url(url: str, expected: str | None) -> None:
    assert _deployment_id_from_url(url) == expected


async def test_no_navigation_when_the_page_already_shows_the_bound_deployment() -> None:
    """The common path must stay a no-op — re-navigating would reset the tab."""
    driver, detail = _driver(
        url=f"http://s/environments/{ENV_ID}/deployments/{BOUND_DEPLOYMENT}",
        bound_deployment=BOUND_DEPLOYMENT,
    )

    await driver._ensure_deployment_detail()

    assert detail.gotos == []


async def test_renavigates_when_the_shared_page_drifted_to_another_deployment() -> None:
    """The bug this guards: acting on a sibling test's deployment.

    The Playwright ``Page`` is session-scoped, so a scenario that never navigated
    itself would previously pass the old ``"/deployments/" in url`` check while
    pointing at someone else's deployment — backing up the wrong one, and
    changing target silently if collection order changed.
    """
    driver, detail = _driver(
        url=f"http://s/environments/{ENV_ID}/deployments/{OTHER_DEPLOYMENT}",
        bound_deployment=BOUND_DEPLOYMENT,
    )

    await driver._ensure_deployment_detail()

    assert detail.gotos == [(ENV_ID, BOUND_DEPLOYMENT)]


async def test_renavigates_from_a_page_that_is_not_a_deployment_at_all() -> None:
    """The old code raised here; the comment promised a re-navigation fallback."""
    driver, detail = _driver(
        url=f"http://s/environments/{ENV_ID}",
        bound_deployment=BOUND_DEPLOYMENT,
    )

    await driver._ensure_deployment_detail()

    assert detail.gotos == [(ENV_ID, BOUND_DEPLOYMENT)]


async def test_falls_back_to_the_url_when_no_deployment_is_bound() -> None:
    """Preserves the old behaviour for a scenario that navigated by hand."""
    driver, detail = _driver(
        url=f"http://s/environments/{ENV_ID}/deployments/{OTHER_DEPLOYMENT}",
        bound_deployment=None,
    )

    await driver._ensure_deployment_detail()

    assert detail.gotos == []


async def test_fails_loudly_when_nothing_identifies_a_deployment() -> None:
    """No binding and no deployment in the URL is unrecoverable — say so."""
    driver, _ = _driver(url="http://s/", bound_deployment=None)

    with pytest.raises(ScenarioActionError, match="no deployment"):
        await driver._ensure_deployment_detail()


async def test_fails_loudly_when_the_environment_context_is_missing() -> None:
    """Re-navigation needs the owning environment to build the URL."""
    driver, _ = _driver(
        url="http://s/settings",
        bound_deployment=BOUND_DEPLOYMENT,
        environment_id=None,
    )

    with pytest.raises(ScenarioActionError, match="no environment context"):
        await driver._ensure_deployment_detail()
