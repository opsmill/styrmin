"""Page object for the Groups admin pages (``/groups`` and ``/groups/$id``).

Used by the admin group membership E2E test
(``test_admin_group_membership.py``). Selectors mirror the
``data-testid`` / ``id`` attributes declared in
``frontend/src/pages/groups/GroupsListPage.tsx``,
``CreateGroupDialog.tsx``, and ``GroupDetailPage.tsx``.

The page object intentionally combines the list, create-dialog, and
detail surfaces so a single object can be threaded through a scenario
that exercises the full lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.pages._dom import submit_dialog, wait_for_dialog_open

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class GroupsAdminPage:
    """Drive the ``/groups`` admin list, create-group dialog, and detail page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    # ------------------------------------------------------------------
    # List page + create dialog
    # ------------------------------------------------------------------

    async def goto_list(self) -> None:
        """Navigate to ``/groups`` and wait for the page header."""
        await self._page.goto("/groups")
        await expect(
            self._page.get_by_role("heading", name="Groups", exact=True)
        ).to_be_visible(timeout=15_000)

    async def open_create_dialog(self) -> None:
        """Click the "Create group" button and wait for the dialog to mount."""
        await self._page.locator("[data-testid=groups-create-button]").click()
        await wait_for_dialog_open(self._page.get_by_role("dialog"))

    async def fill_create_form(
        self,
        *,
        name: str,
        role: str,
        member_usernames: list[str] | None = None,
    ) -> None:
        """Fill the create-group form. Caller must have opened the dialog.

        ``role`` is one of ``READ_ONLY`` / ``READ_WRITE`` / ``ADMIN``.
        ``member_usernames`` is matched against the active-user list in
        the multi-select; matching is by the visible label which starts
        with the username (see ``CreateGroupDialog.tsx``).
        """
        await self._page.locator("#create-group-name").fill(name)

        await self._page.locator("#create-group-role").click()
        label = {
            "READ_ONLY": "Read-only",
            "READ_WRITE": "Read/write",
            "ADMIN": "Admin",
        }[role]
        option = self._page.get_by_role("option", name=label, exact=True)
        await option.wait_for(state="visible", timeout=5_000)
        await option.click()

        if member_usernames:
            multiselect = self._page.locator(
                "[data-testid=create-group-members-multiselect]"
            )
            for username in member_usernames:
                # Each member row labels the checkbox with the
                # username. ``label`` matches the whole text including
                # the display-name suffix; we use a partial match.
                row_label = multiselect.locator(f"label:has-text('{username}')").first
                await row_label.wait_for(state="visible", timeout=5_000)
                await row_label.click()

    async def submit_create(self) -> None:
        """Submit the create-group dialog and wait for it to close."""
        # Successful close == success.
        await submit_dialog(
            self._page.get_by_role("dialog"), button="Create", timeout=10_000
        )

    def find_row(self, name: str) -> Locator:
        """Return the table row locator for ``name``."""
        return self._page.locator(
            f"[data-testid=groups-row][data-group-name='{name}']"
        ).first

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------

    async def goto_detail(self, group_id: str) -> None:
        """Navigate directly to ``/groups/<id>`` and wait for the edit form."""
        await self._page.goto(f"/groups/{group_id}")
        await expect(self._page.locator("[data-testid=group-edit-form]")).to_be_visible(
            timeout=15_000
        )
        # Members section seeds asynchronously from the ListUsers query
        # — wait for the multiselect to mount before the test reads
        # checkbox state. ``state="attached"`` rather than ``visible``
        # because the empty branch renders a paragraph instead.
        await self._page.locator(
            "[data-testid=group-members-multiselect], "
            "[data-testid=group-inactive-members-list]"
        ).first.wait_for(state="attached", timeout=15_000)

    def active_member_row(self, user_id: str) -> Locator:
        """Locator for an active member row in the editor."""
        return self._page.locator(
            f"[data-testid=group-members-multiselect] [data-user-id='{user_id}']"
        ).first

    def inactive_member_row(self, user_id: str) -> Locator:
        """Locator for an inactive member row in the editor."""
        return self._page.locator(
            f"[data-testid=group-inactive-members-list] [data-user-id='{user_id}']"
        ).first

    async def save_no_changes(self) -> None:
        """Click Save without making any edits and assert the success banner.

        This is the regression check for Phase 2 B1: before the fix, the
        editor would silently drop inactive members on save because
        ``activeUsers`` (not the full membership) seeded the form.
        """
        await self._page.locator("[data-testid=group-edit-save]").click()
        await expect(
            self._page.locator("[data-testid=group-detail-success]")
        ).to_be_visible(timeout=10_000)

    async def uncheck_inactive_member(self, user_id: str) -> None:
        """Uncheck an inactive member's checkbox and save the form."""
        row = self.inactive_member_row(user_id)
        await row.wait_for(state="visible", timeout=10_000)
        # The checkbox is a Radix primitive; click the label for the
        # canonical click target. The label sits inside the row.
        await row.locator("label").click()
        await self._page.locator("[data-testid=group-edit-save]").click()
        await expect(
            self._page.locator("[data-testid=group-detail-success]")
        ).to_be_visible(timeout=10_000)
