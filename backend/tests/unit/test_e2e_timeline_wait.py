"""``DeploymentDetailPage.wait_for_new_task``: which timeline task ends the wait,
and the errors of ``DeploymentDetailPage.show_timeline_entry``.

The demos call both; the E2E suite does not, so they are checked here with a
fake timeline.
"""

from __future__ import annotations

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.pages import deployment_detail
from tests.e2e.pages.deployment_detail import (
    DeploymentDetailPage,
    _succeeded_new_task,
    _timeline_task_from_row,
    _TimelineTask,
)

OLD = "11111111-1111-1111-1111-111111111111"
NEW = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"


def _task(task_id: str, task_type: str, result: str) -> _TimelineTask:
    return _TimelineTask(id=task_id, type=task_type, result=result)


def test_returns_none_while_the_new_task_runs() -> None:
    tasks = [_task(NEW, "upgrade_instance", "RUNNING")]

    assert (
        _succeeded_new_task(tasks, task_type="upgrade_instance", known_task_ids={OLD})
        is None
    )


def test_returns_the_new_task_that_succeeded() -> None:
    tasks = [
        _task(NEW, "upgrade_instance", "SUCCEEDED"),
        _task(OLD, "upgrade_instance", "SUCCEEDED"),
    ]

    assert (
        _succeeded_new_task(tasks, task_type="upgrade_instance", known_task_ids={OLD})
        == NEW
    )


def test_ignores_known_tasks_and_tasks_of_another_type() -> None:
    tasks = [
        _task(OLD, "upgrade_instance", "FAILED"),
        _task(OTHER, "update_instance", "FAILED"),
        _task(NEW, "upgrade_instance", "RUNNING"),
    ]

    assert (
        _succeeded_new_task(tasks, task_type="upgrade_instance", known_task_ids={OLD})
        is None
    )


@pytest.mark.parametrize("result", ["FAILED", "SUPERSEDED"])
def test_raises_naming_a_new_task_that_did_not_succeed(result: str) -> None:
    tasks = [_task(NEW, "update_instance", result)]

    with pytest.raises(ScenarioActionError, match=f"update_instance task {NEW}"):
        _succeeded_new_task(tasks, task_type="update_instance", known_task_ids=set())


def test_a_row_without_its_test_hooks_raises() -> None:
    with pytest.raises(ScenarioActionError, match="test-hook"):
        _timeline_task_from_row({"id": NEW, "type": "upgrade_instance", "result": ""})


class _FakeTimeline(DeploymentDetailPage):
    """Serves one list of tasks per read instead of reading a browser page."""

    def __init__(self, reads: list[list[_TimelineTask]]) -> None:
        super().__init__(None)  # type: ignore[arg-type]
        self._reads = reads
        self.opened = 0

    async def open_timeline(self) -> None:
        self.opened += 1

    async def _read_timeline_tasks(self) -> list[_TimelineTask]:
        return self._reads.pop(0) if len(self._reads) > 1 else self._reads[0]


async def test_polls_until_the_new_task_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deployment_detail, "_TIMELINE_POLL_SECONDS", 0.0)
    page = _FakeTimeline(
        [
            [_task(OLD, "upgrade_instance", "SUCCEEDED")],
            [_task(NEW, "upgrade_instance", "RUNNING")],
            [_task(NEW, "upgrade_instance", "SUCCEEDED")],
        ]
    )

    task_id = await page.wait_for_new_task(
        "upgrade_instance", known_task_ids={OLD}, timeout=10.0
    )

    assert task_id == NEW
    assert page.opened == 1


async def test_times_out_naming_the_new_tasks_it_saw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deployment_detail, "_TIMELINE_POLL_SECONDS", 0.01)
    page = _FakeTimeline([[_task(NEW, "upgrade_instance", "RUNNING")]])

    with pytest.raises(ScenarioTimeout, match=f"{NEW} \\(RUNNING\\)"):
        await page.wait_for_new_task(
            "upgrade_instance", known_task_ids=set(), timeout=0.05
        )


class _FakeEntry:
    """A timeline entry that is never listed, or that stays collapsed after a click."""

    def __init__(self, *, listed: bool) -> None:
        self._listed = listed
        self.first = self
        self.clicks = 0

    async def wait_for(self, *, state: str, timeout: float) -> None:
        if not self._listed:
            raise PlaywrightTimeoutError("Timeout 10000ms exceeded.")

    async def get_attribute(self, name: str) -> str:
        return "false"

    def locator(self, selector: str) -> _FakeEntry:
        return self

    async def click(self) -> None:
        self.clicks += 1


class _FakePage:
    def __init__(self, entry: _FakeEntry) -> None:
        self._entry = entry

    def locator(self, selector: str) -> _FakeEntry:
        return self._entry


class _StaysCollapsed:
    def __init__(self, entry: _FakeEntry) -> None:
        pass

    async def to_have_attribute(self, name: str, value: str) -> None:
        raise AssertionError("Locator expected to have attribute 'data-expanded'")


async def test_show_timeline_entry_names_a_task_the_open_tab_does_not_list() -> None:
    page = DeploymentDetailPage(_FakePage(_FakeEntry(listed=False)))  # type: ignore[arg-type]

    with pytest.raises(ScenarioActionError) as raised:
        await page.show_timeline_entry(NEW)

    assert str(raised.value) == (
        f"no entry for task {NEW} on the open Timeline tab within 10 s"
    )
    assert isinstance(raised.value.__cause__, PlaywrightTimeoutError)


async def test_show_timeline_entry_names_an_entry_that_does_not_expand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deployment_detail, "expect", _StaysCollapsed)
    entry = _FakeEntry(listed=True)
    page = DeploymentDetailPage(_FakePage(entry))  # type: ignore[arg-type]

    with pytest.raises(ScenarioActionError) as raised:
        await page.show_timeline_entry(NEW)

    assert str(raised.value) == (
        f"the entry for task {NEW} on the open Timeline tab did not expand after a click"
    )
    assert isinstance(raised.value.__cause__, AssertionError)
    assert entry.clicks == 1
