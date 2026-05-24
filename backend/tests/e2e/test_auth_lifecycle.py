"""End-to-end auth lifecycle (issue #180, spec 011-admin-user-group-mgmt § US8).

Single dual-entrypoint scenario that exercises the full auth path:

1. Log in as the seeded admin (already handled by the session fixtures).
2. Admin creates a ``READ_WRITE`` user via SDK.
3. That user logs in:
   - ``[api-chromium]``: SDK ``client.auth.login(...)``.
   - ``[ui-chromium]``: drive the actual ``/login`` form via ``LoginPage``.
   (Cookie injection is opted-out via ``@pytest.mark.no_cookie_injection``
   so the ui-mode variant genuinely goes through the form.)
4. The new user performs a ``READ_WRITE``-permitted mutation
   (``createEnvironment``) and asserts success.
5. The new user attempts an ADMIN-only mutation (``createUser``) and
   asserts ``FORBIDDEN``.

This is the explicit "shipped to a pass" requirement for the feature
(FR-026, SC-004).
"""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminAuthorizationError, StyrminError
from styrmin_sdk.graphql._generated.enums import Role

from tests.e2e.pages.login import LoginPage


# In ui-mode this test spins up its OWN short-lived BrowserContext (no
# admin cookie) for the LoginPage flow — see ``test_user_client`` below.
# We cannot gate the shared session-scoped page on a marker because the
# session fixture is lazy: a marker on the first test to request it would
# poison every subsequent test's UI session.
pytestmark = [pytest.mark.ci, pytest.mark.shard_general]


@pytest.fixture
async def auth_lifecycle_test_user(
    authenticated_styrmin_client: StyrminClient,
) -> AsyncGenerator[tuple[str, str, str, str], None]:
    """Provision a ``READ_WRITE`` user via the admin SDK; clean up on teardown.

    Yields ``(user_id, username, display_name, password)``. Cleanup goes
    through the admin client (which holds the bootstrap admin session)
    and tolerates ``USER_NOT_FOUND`` — the auth-lifecycle test may have
    already deleted the user as part of the scenario, or its
    ``createEnvironment`` may have created an FK reference that has its
    own cleanup path.

    Side-effect cleanup ordering: any environment the new user created
    inside the test body MUST be deleted before this teardown runs,
    otherwise the user's ``created_by`` FK on the environment blocks
    ``deleteUser`` with ``USER_HAS_REFERENCES``.
    """
    suffix = uuid.uuid4().hex[:8]
    username = f"lifecycle-{suffix}"
    password = f"lifecycle-pw-{suffix}"
    display_name = f"Lifecycle Test {suffix}"

    created = await authenticated_styrmin_client.users.create(
        username=username,
        password=password,
        display_name=display_name,
        role=Role.READ_WRITE,
    )

    try:
        yield str(created.id), username, display_name, password
    finally:
        try:
            await authenticated_styrmin_client.users.delete(str(created.id))
        except StyrminError:
            # Best-effort cleanup. A USER_HAS_REFERENCES error here means
            # the scenario left behind an environment / deployment owned
            # by the test user — the per-test environment cleanup below
            # should have prevented that, but we don't want to mask the
            # original test failure if it did happen.
            pass


@pytest.fixture
async def test_user_client(
    auth_lifecycle_test_user: tuple[str, str, str, str],
    styrmin_deployment: str,
    driver_mode: str,
    session_ui_page,
) -> AsyncGenerator[StyrminClient, None]:
    """Return a ``StyrminClient`` authenticated as the test user.

    - api-mode: SDK ``client.auth.login(...)``.
    - ui-mode: drive the real ``/login`` form via ``LoginPage`` in a
      short-lived fresh ``BrowserContext`` (no admin cookie) launched off
      the same Playwright browser as ``session_ui_page``. The session
      page itself stays admin-logged-in for the rest of the suite. After
      the form drives, build a sibling SDK client carrying the new user's
      credentials so the "permitted mutation" / "forbidden mutation"
      assertions are mode-independent. The ui-mode variant therefore
      exercises BOTH the form (visible side-effect) and the API call
      surface — matching the spec's wording that ui-mode "drives the
      actual login form, NOT cookie injection" while still letting the
      test assert on GraphQL behaviour.
    """
    _, username, _, password = auth_lifecycle_test_user

    if driver_mode == "ui":
        assert session_ui_page is not None, (
            "ui driver_mode must provide a session_ui_page"
        )
        # Spin up a clean (no admin cookie) context on the same browser
        # so the login form is exercised against an unauthenticated
        # browser, without disturbing the session page that the rest of
        # the suite shares.
        browser = session_ui_page.context.browser
        assert browser is not None, "session_ui_page must be attached to a live browser"
        clean_context = await browser.new_context(base_url=styrmin_deployment)
        try:
            clean_page = await clean_context.new_page()
            login_page = LoginPage(clean_page)
            await login_page.goto()
            await login_page.fill_username(username)
            await login_page.fill_password(password)
            await login_page.submit()
            await login_page.wait_for_redirect()
        finally:
            await clean_context.close()

    # SDK login. In api-mode this is the only login; in ui-mode it
    # provides the token the assertions need. Both flows go through the
    # production ``Mutation.login`` resolver — no test-only bypass.
    client = StyrminClient(server_address=styrmin_deployment)
    try:
        await client.auth.login(username=username, password=password)
        yield client
    finally:
        await client.close()


@pytest.fixture
async def auth_lifecycle_cleanup(
    authenticated_styrmin_client: StyrminClient,
) -> AsyncGenerator[list[str], None]:
    """Collect environment ids the test creates; delete them on teardown.

    The auth-lifecycle test exercises ``createEnvironment`` as the new
    ``READ_WRITE`` user. That row carries ``created_by = new_user``,
    which is an FK reference that would block ``deleteUser`` in the
    user fixture's teardown. We delete the environment first, via the
    admin client (which can always delete), so the user teardown is
    unblocked.
    """
    env_ids: list[str] = []
    try:
        yield env_ids
    finally:
        for env_id in env_ids:
            try:
                await authenticated_styrmin_client.environments.delete(
                    environment_id=env_id
                )
            except StyrminError:
                # Best-effort. If the test itself already deleted the
                # env or the platform tore it down, suppress so the
                # downstream user-delete still runs.
                pass


async def test_auth_lifecycle(
    test_user_client: StyrminClient,
    styrmin_resources: dict,
    auth_lifecycle_cleanup: list[str],
) -> None:
    """End-to-end auth lifecycle in both ``[api-chromium]`` and ``[ui-chromium]``.

    Per spec § US8 acceptance scenarios 1 and 2, the assertion shape is
    identical across modes — the difference between the two is HOW the
    user logged in (SDK vs. real form), captured in ``test_user_client``.
    """
    cluster_id = styrmin_resources["cluster_id"]
    suffix = uuid.uuid4().hex[:8]

    # Step 4: a ``READ_WRITE``-permitted mutation. ``createEnvironment``
    # is gated on ``RequiresRole(READ_WRITE)`` — a ``READ_WRITE`` user
    # must be able to call it successfully.
    env_name = f"lifecycle-env-{suffix}"
    env = await test_user_client.environments.create(
        name=env_name,
        cluster_id=cluster_id,
        config={},
    )
    auth_lifecycle_cleanup.append(str(env.id))
    assert env.name == env_name
    assert env.id is not None

    # Step 5: an ADMIN-only mutation. ``createUser`` is gated on
    # ``RequiresRole(ADMIN)`` — a ``READ_WRITE`` user must receive
    # ``FORBIDDEN``. The SDK surfaces this as
    # ``StyrminAuthorizationError`` (see ``exceptions.py``).
    forbidden_username = f"forbidden-{suffix}"
    with pytest.raises(StyrminAuthorizationError):
        await test_user_client.users.create(
            username=forbidden_username,
            password="should-never-be-created",
            display_name=forbidden_username,
            role=Role.READ_ONLY,
        )
