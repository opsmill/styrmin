"""Page object for the login page (``/login``).

Used by the US8 auth-lifecycle E2E test (``test_auth_lifecycle.py``) and
any future test that needs to drive the real login form. Selectors
mirror the IDs declared in ``frontend/src/pages/login/LoginPage.tsx``
(``login-username``, ``login-password``, ``login-error``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import expect

from tests.e2e.pages._dom import enter_text

if TYPE_CHECKING:
    from playwright.async_api import Page


class LoginPage:
    """Drive the login form on the ``/login`` route."""

    def __init__(self, page: Page, *, keystroke_delay_ms: int | None = None) -> None:
        self._page = page
        self._keystroke_delay_ms = keystroke_delay_ms

    async def goto(self) -> None:
        """Navigate to ``/login`` and wait for the form to render.

        The login form is a single Card; the "Sign in to Styrmin"
        heading is the most stable anchor on the page. Plain ``goto`` is
        not enough on its own because the frontend mounts client-side —
        we need to wait for the React tree to attach before the test can
        type into the inputs.
        """
        await self._page.goto("/login")
        await expect(
            self._page.get_by_role("heading", name="Sign in to Styrmin")
        ).to_be_visible(timeout=15_000)

    async def fill_username(self, value: str) -> None:
        await enter_text(
            self._page.locator("#login-username"),
            value,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

    async def fill_password(self, value: str) -> None:
        await enter_text(
            self._page.locator("#login-password"),
            value,
            keystroke_delay_ms=self._keystroke_delay_ms,
        )

    async def submit(self) -> None:
        """Click the Sign-in button and wait for the navigation away.

        On success the auth context refetches ``currentUser`` and the
        router redirects to ``/`` — wait for the URL to change rather
        than for the button text, because the "Signing in…" pending
        state flips back to "Sign in" iff the mutation errored.
        """
        await self._page.get_by_role("button", name="Sign in").click()

    async def wait_for_redirect(self) -> None:
        """Block until the post-login redirect away from ``/login`` lands.

        On a successful login the AuthProvider refetches ``currentUser``
        which causes the route guard to send the user to ``/``. The
        redirect is best detected by waiting for a URL pattern that does
        NOT include ``/login`` — Playwright's ``wait_for_url`` accepts
        a predicate for exactly this.
        """
        await self._page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)

    async def expect_error_message(self, text: str) -> None:
        """Assert the generic error message ``text`` renders inline.

        The login page surfaces the same generic message ("Invalid
        username or password.") for every failure mode by contract —
        spec.md FR-024 — so callers pass that exact string.
        """
        error = self._page.locator("[data-testid=login-error]")
        await expect(error).to_be_visible(timeout=10_000)
        await expect(error).to_have_text(text)
