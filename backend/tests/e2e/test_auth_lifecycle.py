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


# ``no_cookie_injection`` is the SC-007 opt-out: the session-scoped
# Playwright BrowserContext that this test opens does NOT receive the
# seeded admin's session cookie, so the ui-mode variant of "log in as
# the new user" exercises the real login form rather than impersonating
# the admin.
pytestmark = [
    pytest.mark.ci,
    pytest.mark.no_cookie_injection,
]


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
    session_ui_page,  # noqa: ARG001 — ensures the UI session is up so the LoginPage flow has a Page
) -> AsyncGenerator[StyrminClient, None]:
    """Return a ``StyrminClient`` authenticated as the test user.

    - api-mode: SDK ``client.auth.login(...)``.
    - ui-mode: drive the real ``/login`` form via ``LoginPage`` (the
      cookie injection is opted-out at the module level), then build a
      sibling SDK client carrying the same returned token so the
      "permitted mutation" / "forbidden mutation" assertions are
      mode-independent. The ui-mode variant therefore exercises BOTH
      the form (visible side-effect on the page) and the API call
      surface — matching the spec's wording that ui-mode "drives the
      actual login form, NOT cookie injection" while still letting the
      test assert on GraphQL behaviour.
    """
    _, username, _, password = auth_lifecycle_test_user

    if driver_mode == "ui":
        # Drive the real form. The session-scoped Playwright Page has
        # no admin cookie (this test opted out), so it lands on
        # ``/login`` with a clean state.
        page = session_ui_page
        assert page is not None, "ui driver_mode must provide a session_ui_page"
        login_page = LoginPage(page)
        await login_page.goto()
        await login_page.fill_username(username)
        await login_page.fill_password(password)
        await login_page.submit()
        await login_page.wait_for_redirect()

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
