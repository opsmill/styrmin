"""Page object for a task template of Semaphore v2.16 and its task log, used by the demos only.

Semaphore's Vuetify UI has few test ids, so the locators use roles, labels and icon classes,
plus the test id of the task status.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e.demos.semaphore_setup import ADMIN_PASSWORD, ADMIN_USERNAME
from tests.e2e.drivers.errors import ScenarioActionError, ScenarioTimeout
from tests.e2e.pages._dom import enter_text

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

TIMEOUT_MS = 30_000
FINISHED_STATUSES = ("Success", "Failed", "Stopped")
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_FINISHED_PATTERN = re.compile(rf"^\s*({'|'.join(FINISHED_STATUSES)})\s*$")
# The message Semaphore shows after a deletion, next to its "Close" button.
_DELETED_PATTERN = re.compile(r'Template ".*" deleted')
# The template list; a template's own page also holds a table, of its tasks.
_LIST_URL_PATTERN = re.compile(r"/project/\d+/templates/?$")


def strip_ansi(text: str) -> str:
    """Remove the ANSI colour and cursor codes that Ansible writes into a task log."""
    return _ANSI_PATTERN.sub("", text)


def check_task_status(status: str, log: str) -> None:
    """Raise unless ``status`` is "Success"; the error ends with the last lines of ``log``."""
    if status.strip() == "Success":
        return
    tail = "\n".join([line for line in log.splitlines() if line.strip()][-10:])
    raise ScenarioActionError(
        f"The Semaphore task ended with status {status.strip()!r}. Last lines of its log:\n{tail}"
    )


class SemaphoreTemplatesPage:
    """Run a task template, read its log, and delete it in the Semaphore web UI."""

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

    async def log_in(
        self,
        base_url: str,
        *,
        username: str = ADMIN_USERNAME,
        password: str = ADMIN_PASSWORD,
    ) -> None:
        """Log in at ``/auth/login``; ends when Semaphore leaves the login page."""
        await self._page.goto(f"{base_url}/auth/login")
        await enter_text(
            self._page.get_by_label("Username"),
            username,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        await enter_text(
            self._page.get_by_label("Password"),
            password,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )
        await self._page.get_by_role("button", name="Sign In", exact=True).click()
        await self._page.wait_for_url(
            lambda url: "/auth/login" not in url, timeout=TIMEOUT_MS
        )

    async def goto_template(
        self, base_url: str, project_id: int, template_id: int
    ) -> None:
        await self._page.goto(
            f"{base_url}/project/{project_id}/templates/{template_id}"
        )
        await self._run_button.wait_for(timeout=TIMEOUT_MS)

    async def run(self) -> None:
        """Start a task of the open template; ends when its log dialog opens."""
        await self._run_button.click()
        new_task = self._page.get_by_role("dialog").filter(has_text="New Task")
        await new_task.get_by_role("button", name="Run", exact=True).click()
        await self._log_dialog.wait_for(timeout=TIMEOUT_MS)

    async def wait_for_output(self, timeout: float) -> str:
        """Wait up to ``timeout`` seconds for the task in the log dialog to finish and return its log.

        Raises when the task does not end with "Success".
        """
        status = self._log_dialog.get_by_test_id("task-status")
        try:
            await expect(status).to_have_text(_FINISHED_PATTERN, timeout=timeout * 1000)
        except AssertionError as exc:
            shown = await status.inner_text() if await status.count() else "no status"
            raise ScenarioTimeout(
                f"The Semaphore task did not finish within {timeout:.0f} s (status: {shown.strip()})"
            ) from exc
        log = await self._raw_log()
        check_task_status(await status.inner_text(), log)
        return log

    async def close_output(self) -> None:
        """Close the task log dialog."""
        dialog = self._log_dialog
        await (
            dialog.get_by_role("button")
            .filter(has=self._page.locator(".mdi-close"))
            .click()
        )
        await dialog.wait_for(state="hidden", timeout=TIMEOUT_MS)

    async def delete_template(self) -> None:
        """Delete the open template; ends when Semaphore reports it deleted."""
        await (
            self._page.get_by_role("button")
            .filter(has=self._page.locator(".mdi-delete"))
            .click()
        )
        confirm = self._page.get_by_role("dialog").filter(has_text="Delete template")
        await confirm.get_by_role("button", name="Yes", exact=True).click()
        try:
            await expect(self._page.get_by_text(_DELETED_PATTERN)).to_be_visible(
                timeout=TIMEOUT_MS
            )
        except AssertionError as exc:
            raise ScenarioActionError(
                "Semaphore did not report the template deleted"
            ) from exc

    async def template_names(self, base_url: str, project_id: int) -> list[str]:
        """Open the project's template list and return the template names."""
        await self._page.goto(f"{base_url}/project/{project_id}/templates")
        return await self.listed_template_names()

    async def listed_template_names(self) -> list[str]:
        """Return the names in the template list on screen, such as the one Semaphore opens after a deletion."""
        await self._page.wait_for_url(_LIST_URL_PATTERN, timeout=TIMEOUT_MS)
        # Semaphore renders the table only once the list has loaded.
        table = self._page.get_by_role("table")
        await table.wait_for(timeout=TIMEOUT_MS)
        names = await table.get_by_role("link").all_inner_texts()
        return [name.strip() for name in names]

    async def open_template(self, name: str) -> None:
        """Click template ``name`` in the template list on screen; ends when its page shows "Run"."""
        await (
            self._page.get_by_role("table")
            .get_by_role("link", name=name, exact=True)
            .click()
        )
        await self._run_button.wait_for(timeout=TIMEOUT_MS)

    @property
    def _run_button(self) -> Locator:
        return self._page.get_by_role("main").get_by_role(
            "button", name="Run", exact=True
        )

    @property
    def _log_dialog(self) -> Locator:
        return self._page.get_by_role("dialog").filter(
            has_text=re.compile(r"Task #\d+")
        )

    async def _raw_log(self) -> str:
        # The "Raw log" link appears when the task stops; the browser context's cookie authenticates the request.
        link = self._log_dialog.get_by_role("link", name="Raw log")
        try:
            href = await link.get_attribute("href", timeout=TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ScenarioTimeout(
                "The task log dialog shows no 'Raw log' link"
            ) from exc
        if not href:
            raise ScenarioActionError(
                "The 'Raw log' link of the task log has no address"
            )
        response = await self._page.request.get(urljoin(self._page.url, href))
        if not response.ok:
            raise ScenarioActionError(
                f"Semaphore answered HTTP {response.status} for the raw task log"
            )
        return strip_ansi(await response.text())
