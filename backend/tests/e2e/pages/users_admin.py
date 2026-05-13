"""Page object for the Users admin pages (``/users`` and ``/users/$id``).

Used by the US8 auth-lifecycle E2E test (``test_auth_lifecycle.py``).
Selectors mirror the ``data-testid`` / ``id`` attributes declared in
``frontend/src/pages/users/UsersListPage.tsx``, ``CreateUserDialog.tsx``,
and ``UserDetailPage.tsx``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import expect

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class UsersAdminPage:
    """Drive the ``/users`` admin list, the create-user dialog, and a user's detail page.

    The page object intentionally combines the list and detail surfaces:
    every operation a test would chain together (create → find row →
    open detail → mutate / delete) flows through the same wrapper.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    # ------------------------------------------------------------------
    # List page
    # ------------------------------------------------------------------

    async def goto_list(self) -> None:
        """Navigate to ``/users`` and wait for the page header to render."""
        await self._page.goto("/users")
        await expect(
            self._page.get_by_role("heading", name="Users", exact=True)
        ).to_be_visible(timeout=15_000)

    async def open_create_dialog(self) -> None:
        """Click the "Create user" button and wait for the dialog to mount."""
        await self._page.locator("[data-testid=users-create-button]").click()
        dialog = self._page.get_by_role("dialog")
        await dialog.wait_for(state="visible")

    async def fill_create_form(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
    ) -> None:
        """Fill the create-user form. Caller must have opened the dialog.

        ``role`` is one of ``READ_ONLY`` / ``READ_WRITE`` / ``ADMIN``.
        The role select uses Radix's combobox primitive; the option's
        ``value`` attribute is the role string itself.
        """
        await self._page.locator("#create-user-username").fill(username)
        await self._page.locator("#create-user-display-name").fill(display_name)
        await self._page.locator("#create-user-password").fill(password)

        # Open the role select trigger and click the matching option.
        # SelectItem renders the human label (``roleLabel``) as visible
        # text — ``get_by_role("option", name=...)`` matches on
        # accessible name, so we translate the canonical role enum to
        # its rendered label here.
        await self._page.locator("#create-user-role").click()
        role_label = {
            "READ_ONLY": "Read-only",
            "READ_WRITE": "Read/write",
            "ADMIN": "Admin",
        }[role]
        option = self._page.get_by_role("option", name=role_label, exact=True)
        await option.wait_for(state="visible", timeout=5_000)
        await option.click()

    async def submit(self) -> None:
        """Submit the create-user dialog and wait for it to close."""
        dialog = self._page.get_by_role("dialog")
        await dialog.get_by_role("button", name="Create", exact=True).click()
        # The dialog only closes on success; on error the alert renders
        # inline. ``wait_for(state="hidden")`` therefore doubles as the
        # success assertion — if the form failed, the test sees a
        # timeout pointing straight at the dialog.
        await dialog.wait_for(state="hidden", timeout=10_000)

    def find_row(self, username: str) -> Locator:
        """Return the table row locator for ``username``.

        Returns a Locator (lazy) — callers chain ``await expect(...)``
        or ``await ....click()`` on it to evaluate.
        """
        return self._page.locator(
            f"[data-testid=users-row][data-username='{username}']"
        ).first

    async def open_user(self, username: str) -> None:
        """Click the username link in the row to land on ``/users/$id``."""
        row = self.find_row(username)
        await row.wait_for(state="visible", timeout=10_000)
        # The username cell renders as a <Link> — click on the cell text
        # rather than the row to land on the detail page.
        await row.get_by_role("link", name=username).click()
        await expect(
            self._page.get_by_role("heading", name=username, exact=True)
        ).to_be_visible(timeout=10_000)

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------

    async def set_active(self, value: bool) -> None:
        """Toggle the Active checkbox and save the form.

        Reads the current state of the checkbox first; only clicks when
        the current value differs from the target so a no-op call is
        actually a no-op (Playwright would otherwise flip the value).
        """
        checkbox = self._page.locator("#user-active")
        current = await checkbox.is_checked()
        if current != value:
            # The checkbox is a Radix primitive; the label is the
            # canonical click target.
            await self._page.locator("label[for='user-active']").click()
        await self._page.locator("[data-testid=user-edit-save]").click()
        await expect(
            self._page.locator("[data-testid=user-detail-success]")
        ).to_be_visible(timeout=10_000)

    async def reset_password(self, new_password: str) -> None:
        """Open the reset-password dialog, set ``new_password``, submit."""
        await self._page.locator("[data-testid=user-reset-password-trigger]").click()
        dialog = self._page.get_by_role("dialog", name="Reset password")
        await dialog.wait_for(state="visible")
        await self._page.locator("#reset-password-new").fill(new_password)
        await dialog.get_by_role("button", name="Reset", exact=True).click()
        await dialog.wait_for(state="hidden", timeout=10_000)

    async def delete_user(self) -> None:
        """Click the Delete button, confirm via the in-app ConfirmDialog,
        and wait for the redirect back to ``/users``.

        Phase 4 G2 replaced ``window.confirm`` with an in-app
        ``ConfirmDialog`` (testid ``user-delete-confirm``); we drive that
        modal instead of registering a JS dialog handler. The successful
        navigation away from the detail page is the assertion.
        """
        await self._page.locator("[data-testid=user-delete-button]").click()
        confirm = self._page.locator("[data-testid=user-delete-confirm-confirm]")
        await confirm.wait_for(state="visible", timeout=5_000)
        await confirm.click()
        # On success the page navigates back to ``/users``; the
        # successful navigation away is the assertion.
        await self._page.wait_for_url("**/users", timeout=10_000)

    async def set_display_name(self, value: str) -> None:
        """Replace the display-name input and save the form.

        Saving is asserted by the inline success banner.
        """
        field = self._page.locator("#user-display-name")
        await field.fill(value)
        await self._page.locator("[data-testid=user-edit-save]").click()
        await expect(
            self._page.locator("[data-testid=user-detail-success]")
        ).to_be_visible(timeout=10_000)

    async def set_role(self, role: str) -> None:
        """Pick ``role`` (``READ_ONLY`` / ``READ_WRITE`` / ``ADMIN``) and save.

        Uses the Radix Select on ``#user-role``; the option's display
        text is the human label, so we look up the option by the long-
        form text rendered by ``roleLabel``.
        """
        await self._page.locator("[data-testid=user-role-trigger]").click()
        # The SelectItem renders the human label as visible text. Use
        # the role's value attribute to disambiguate: Radix sets it on
        # the option element, but the visible text is the label. We
        # match on the role-string title fallback, which the badge sets
        # but the option does not — so match by the label values
        # directly.
        label = {
            "READ_ONLY": "Read-only",
            "READ_WRITE": "Read/write",
            "ADMIN": "Admin",
        }[role]
        option = self._page.get_by_role("option", name=label, exact=True)
        await option.wait_for(state="visible", timeout=5_000)
        await option.click()
        await self._page.locator("[data-testid=user-edit-save]").click()
        await expect(
            self._page.locator("[data-testid=user-detail-success]")
        ).to_be_visible(timeout=10_000)
