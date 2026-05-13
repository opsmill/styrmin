"""End-to-end admin user CRUD lifecycle (spec 011-admin-user-group-mgmt, Phase 6 C1).

Dual-entrypoint scenario that walks a user through the full admin
lifecycle and asserts the Phase 1-5 fixes that landed on this branch:

- Inactive users can't authenticate (Phase 1 A1, surfaced as
  ``INVALID_CREDENTIALS`` so username enumeration is closed).
- Updates roundtrip through both the SDK (api-mode) and the
  ``/users/$id`` admin form (ui-mode), including role change,
  display-name change, password reset, deactivate/reactivate, and
  hard-delete with the in-app ConfirmDialog (Phase 4 G2).

The api/ui variants share the same step sequence; the only difference
is the driver — SDK calls vs. Playwright on the admin's session page.
"""

from __future__ import annotations

import uuid

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import (
    ResourceNotFoundError,
    StyrminError,
)
from styrmin_sdk.graphql._generated.enums import Role

from tests.e2e.pages import UsersAdminPage

pytestmark = [pytest.mark.ci]


async def _user_can_login(server: str, username: str, password: str) -> bool:
    """Best-effort login probe; returns True iff ``Mutation.login`` succeeds.

    Builds a throwaway SDK client so the probe doesn't share state with
    the admin client. Any ``StyrminError`` (including the
    ``INVALID_CREDENTIALS`` surfaced for deactivated accounts) reads as
    "cannot log in".
    """
    probe = StyrminClient(server_address=server)
    try:
        await probe.auth.login(username=username, password=password)
        return True
    except StyrminError:
        return False
    finally:
        await probe.close()


async def test_admin_user_crud_lifecycle(
    authenticated_styrmin_client: StyrminClient,
    styrmin_deployment: str,
    styrmin_resources: dict,  # noqa: ARG001 — gates platform setup before the test runs
    driver_mode: str,
    session_ui_page,
) -> None:
    """Full admin user CRUD lifecycle, dual-entrypoint.

    Steps (see Phase 6 C1):

    1. Admin creates a ``READ_ONLY`` user.
    2. Admin updates display name and role to ``READ_WRITE``.
    3. Admin resets the user's password.
    4. Admin deactivates the user.
    5. The user can no longer authenticate (verifies Phase 1 A1).
    6. Admin reactivates the user.
    7. Admin hard-deletes the user (no FK references → succeeds).
    8. The user no longer appears in ``users(active: null)`` listing.

    The api variant drives each step through the SDK; the ui variant
    drives the create dialog and the detail-page form. Assertion shape
    is identical across both modes so the variants stay parallel.
    """
    suffix = uuid.uuid4().hex[:8]
    username = f"crud-{suffix}"
    initial_password = f"crud-pw-init-{suffix}"
    reset_password = f"crud-pw-reset-{suffix}"
    initial_display = f"CRUD Test {suffix}"
    new_display = f"CRUD Test {suffix} (updated)"

    created_user_id: str | None = None

    try:
        # ------------------------------------------------------------------
        # Step 1: create as READ_ONLY
        # ------------------------------------------------------------------
        if driver_mode == "api":
            created = await authenticated_styrmin_client.users.create(
                username=username,
                password=initial_password,
                display_name=initial_display,
                role=Role.READ_ONLY,
            )
            created_user_id = str(created.id)
            assert created.role == Role.READ_ONLY
            assert created.active is True
        else:
            assert session_ui_page is not None
            users_page = UsersAdminPage(session_ui_page)
            await users_page.goto_list()
            await users_page.open_create_dialog()
            await users_page.fill_create_form(
                username=username,
                display_name=initial_display,
                password=initial_password,
                role="READ_ONLY",
            )
            await users_page.submit()
            # Resolve the new user's id by querying the SDK — the row
            # carries ``data-user-id`` but the rest of the scenario only
            # needs the canonical id for the post-delete listing check.
            users_after_create = await authenticated_styrmin_client.users.list(
                active=None
            )
            match = next(u for u in users_after_create if u.username == username)
            created_user_id = str(match.id)

        # Probe: the new READ_ONLY user can log in.
        assert await _user_can_login(styrmin_deployment, username, initial_password), (
            "newly-created READ_ONLY user must be able to authenticate"
        )

        # ------------------------------------------------------------------
        # Step 2: update display name + role -> READ_WRITE
        # ------------------------------------------------------------------
        if driver_mode == "api":
            updated = await authenticated_styrmin_client.users.update(
                created_user_id,
                display_name=new_display,
                role=Role.READ_WRITE,
            )
            assert updated.display_name == new_display
            assert updated.role == Role.READ_WRITE
        else:
            await session_ui_page.goto(f"/users/{created_user_id}")
            await expect(
                session_ui_page.get_by_role("heading", name=username, exact=True)
            ).to_be_visible(timeout=10_000)
            users_page = UsersAdminPage(session_ui_page)
            await users_page.set_display_name(new_display)
            await users_page.set_role("READ_WRITE")
            via_sdk = await authenticated_styrmin_client.users.get(created_user_id)
            assert via_sdk.display_name == new_display
            assert via_sdk.role == Role.READ_WRITE

        # ------------------------------------------------------------------
        # Step 3: reset password — old password rejected, new accepted
        # ------------------------------------------------------------------
        if driver_mode == "api":
            ok = await authenticated_styrmin_client.users.reset_password(
                created_user_id, reset_password
            )
            assert ok is True
        else:
            users_page = UsersAdminPage(session_ui_page)
            await users_page.reset_password(reset_password)

        assert not await _user_can_login(
            styrmin_deployment, username, initial_password
        ), "stale password must not authenticate after reset"
        assert await _user_can_login(styrmin_deployment, username, reset_password), (
            "newly-set password must authenticate"
        )

        # ------------------------------------------------------------------
        # Step 4: deactivate (active=false) — verifies Phase 1 A1
        # ------------------------------------------------------------------
        if driver_mode == "api":
            deactivated = await authenticated_styrmin_client.users.update(
                created_user_id, active=False
            )
            assert deactivated.active is False
        else:
            # In ui-mode we still drive the UI checkbox via the detail
            # page so this codepath exercises the React form. Re-navigate
            # because the previous step (reset_password) may have left a
            # stale dialog state on the same page.
            await session_ui_page.goto(f"/users/{created_user_id}")
            await expect(
                session_ui_page.get_by_role("heading", name=username, exact=True)
            ).to_be_visible(timeout=10_000)
            users_page = UsersAdminPage(session_ui_page)
            await users_page.set_active(False)

        # Step 5: inactive user cannot authenticate (Phase 1 A1).
        assert not await _user_can_login(
            styrmin_deployment, username, reset_password
        ), (
            "deactivated user must not authenticate — surfaced as "
            "INVALID_CREDENTIALS to close the enumeration channel"
        )

        # ------------------------------------------------------------------
        # Step 6: reactivate — confirms the toggle works in both directions
        # ------------------------------------------------------------------
        if driver_mode == "api":
            reactivated = await authenticated_styrmin_client.users.update(
                created_user_id, active=True
            )
            assert reactivated.active is True
        else:
            await session_ui_page.goto(f"/users/{created_user_id}")
            await expect(
                session_ui_page.get_by_role("heading", name=username, exact=True)
            ).to_be_visible(timeout=10_000)
            users_page = UsersAdminPage(session_ui_page)
            await users_page.set_active(True)

        assert await _user_can_login(styrmin_deployment, username, reset_password), (
            "reactivated user must authenticate again"
        )

        # ------------------------------------------------------------------
        # Step 7: hard-delete. The user has no FK references (no
        # environments / deployments owned), so deletion succeeds.
        # ------------------------------------------------------------------
        if driver_mode == "api":
            deleted = await authenticated_styrmin_client.users.delete(created_user_id)
            assert deleted is True
        else:
            # ``set_active(True)`` already navigated to the detail
            # page; ``delete_user`` clicks Delete, confirms via the
            # in-app ConfirmDialog (Phase 4 G2), and waits for the
            # redirect.
            users_page = UsersAdminPage(session_ui_page)
            await users_page.delete_user()

        # Mark cleanup as already-done so the finally block doesn't
        # re-attempt a delete that will USER_NOT_FOUND.
        deleted_id = created_user_id
        created_user_id = None

        # ------------------------------------------------------------------
        # Step 8: deleted user no longer appears in ``users(active: null)``
        # ------------------------------------------------------------------
        listing = await authenticated_styrmin_client.users.list(active=None)
        assert all(str(u.id) != deleted_id for u in listing), (
            f"user {deleted_id!r} must not appear in users(active: null) after "
            "hard-delete"
        )
        # And ``users.get`` raises USER_NOT_FOUND.
        with pytest.raises(ResourceNotFoundError):
            await authenticated_styrmin_client.users.get(deleted_id)

    finally:
        # Defensive cleanup: if any step before Step 7 failed, the test
        # user is still in the DB. Best-effort delete; tolerate
        # USER_NOT_FOUND in case the deactivate step left state we can't
        # observe.
        if created_user_id is not None:
            try:
                await authenticated_styrmin_client.users.delete(created_user_id)
            except StyrminError:
                pass
