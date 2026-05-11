"""Session-scoped Playwright cookie injection (research.md D5).

Implements the SC-007 contract: every existing UI-mode E2E scenario uses
a session-scoped login (one SDK call per session) and the captured
session cookie is injected onto every Playwright ``BrowserContext`` that
the suite opens. Tests that genuinely need a clean unauthenticated
browser opt out with ``@pytest.mark.no_cookie_injection``.

The seeded admin's credentials are sourced from the test fixtures'
``styrmin-values.yaml`` (``styrmin.adminPassword``) and mirrored in
``backend/tests/e2e/conftest.py`` as ``_E2E_ADMIN_USERNAME`` /
``_E2E_ADMIN_PASSWORD``. The conftest exposes them via the
``admin_credentials`` fixture, which this module re-uses through the
``admin_token`` fixture (login as the seeded admin via SDK).

The cookie name matches the backend's session cookie
(``styrmin_session``) so server-side auth resolution treats the
Playwright context identically to a freshly-logged-in browser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable
from urllib.parse import urlparse

import pytest

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext


# Must match ``cookie.name`` set by the backend's login mutation.
# Lifted to a module-level constant so the cookie name is one
# import-line away from any future audit.
SESSION_COOKIE_NAME = "styrmin_session"


# Type alias for the injector that ``conftest.py`` calls on every new
# ``BrowserContext`` that is not opted out of cookie injection.
InjectSessionCookie = Callable[["BrowserContext"], Awaitable[None]]


def _build_cookie(*, token: str, base_url: str) -> dict[str, object]:
    """Construct the Playwright cookie payload for the seeded admin session.

    ``base_url`` is the styrmin base URL (e.g. ``http://localhost:54321``)
    so the cookie's ``domain`` matches the hostname the browser will
    request. ``secure`` is True only when the scheme is HTTPS.
    """
    parsed = urlparse(base_url)
    return {
        "name": SESSION_COOKIE_NAME,
        "value": token,
        "domain": parsed.hostname or "localhost",
        "path": "/",
        "httpOnly": True,
        "secure": parsed.scheme == "https",
        "sameSite": "Lax",
    }


@pytest.fixture(scope="session")
def inject_session_cookie(
    admin_token: str,
    styrmin_deployment: str,
) -> InjectSessionCookie:
    """Return an async callable that injects the seeded-admin session cookie.

    ``conftest.py`` invokes the returned callable on every Playwright
    ``BrowserContext`` it opens that is *not* marked with
    ``@pytest.mark.no_cookie_injection``. The callable is a closure over
    the session-scoped admin token + base URL — building the cookie
    payload once per call (cheap; no allocation pressure) keeps each
    context independent.

    The cookie value is the bearer token returned by
    ``client.auth.login()``. The backend's login mutation sets a
    ``styrmin_session`` cookie carrying that same token, so a request
    that originates from a Playwright page with this cookie is
    indistinguishable from one made by a real logged-in browser.
    """

    async def _inject(context: BrowserContext) -> None:
        await context.add_cookies(
            [_build_cookie(token=admin_token, base_url=styrmin_deployment)]
        )

    return _inject


def should_inject_session_cookie(request: pytest.FixtureRequest) -> bool:
    """Return False if the current test opts out of session cookie injection.

    Tests opt out by declaring ``@pytest.mark.no_cookie_injection``. The
    primary consumer is ``test_auth_lifecycle.py`` (US8), which drives
    the actual login form in ui-mode and therefore needs a clean browser.

    Lifted to a module-level helper so the conftest fixture can re-use
    the same predicate without re-deriving the marker lookup.
    """
    return request.node.get_closest_marker("no_cookie_injection") is None
