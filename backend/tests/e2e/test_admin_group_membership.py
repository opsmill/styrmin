"""End-to-end admin group membership / role-editor lifecycle (Phase 6 C2).

Dual-entrypoint scenario that exercises the Phase 2 B1 fix (group
editor preserves inactive members on save) along with the basic
group-membership CRUD surface and the ``LAST_ADMIN`` guard.

Steps shared across both variants:

1. Admin creates a new group ``lifecycle-group-<suffix>`` with role
   ``READ_WRITE``.
2. Admin creates two users (A and B), both initially active.
3. Both users are added to the new group.
4. User B is deactivated; the group now has one active + one inactive
   member.
5. The group's editor must show BOTH users (A in the active list, B in
   the inactive sub-list).
6. Saving the editor with no changes preserves BOTH memberships
   (Phase 2 B1).
7. Removing B via the inactive-member checkbox leaves only A in the
   group.
8. Last-admin guard: attempting to demote the seeded admin to a
   non-admin role returns ``LAST_ADMIN``.

Steps 5-7 specifically distinguish the ui variant from the api
variant: the ui variant walks the React form (which is what
historically dropped inactive members), while the api variant exercises
the same semantic chain through the SDK so the LAST_ADMIN guard is
asserted in both modes.
"""

from __future__ import annotations

import uuid

import pytest
from playwright.async_api import expect
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import OperationFailedError, StyrminError
from styrmin_sdk.graphql._generated.enums import Role

from tests.e2e.pages import GroupsAdminPage

pytestmark = [pytest.mark.ci]


async def _member_ids(client: StyrminClient, group_id: str) -> set[str]:
    """Return the set of user ids whose ``.groups`` contains ``group_id``.

    The backend ``type Group`` does not expose ``members`` directly;
    callers go through the user list (active + inactive) and filter,
    matching what ``GroupDetailPage`` does client-side. We use
    ``active=None`` so deactivated members are still observable.
    """
    users = await client.users.list(active=None)
    return {str(u.id) for u in users if any(str(g.id) == group_id for g in u.groups)}


async def _delete_user_quietly(client: StyrminClient, user_id: str) -> None:
    """Best-effort delete used by the test's cleanup block."""
    try:
        await client.users.delete(user_id)
    except StyrminError:
        # The test may have already deleted the user, or an FK constraint
        # might have surfaced — we swallow either way so the cleanup
        # doesn't mask the original failure.
        pass


async def _delete_group_quietly(client: StyrminClient, group_id: str) -> None:
    """Best-effort delete used by the test's cleanup block."""
    try:
        await client.groups.delete(group_id)
    except StyrminError:
        pass


async def test_admin_group_membership_lifecycle(
    authenticated_styrmin_client: StyrminClient,
    styrmin_resources: dict,  # noqa: ARG001 — gates platform setup before the test runs
    driver_mode: str,
    session_ui_page,
    admin_credentials: tuple[str, str],
) -> None:
    """Group membership/role-editor lifecycle in both api and ui modes."""
    suffix = uuid.uuid4().hex[:8]
    group_name = f"lifecycle-group-{suffix}"
    username_a = f"member-a-{suffix}"
    username_b = f"member-b-{suffix}"
    password = f"member-pw-{suffix}"

    group_id: str | None = None
    user_a_id: str | None = None
    user_b_id: str | None = None

    try:
        # ------------------------------------------------------------------
        # Step 2 (run first so the create-group form can find the users):
        # create both users as ADMIN-active. Provisioned via the SDK in
        # both modes — these are test fixtures, not part of the user-
        # CRUD acceptance surface (covered by ``test_admin_user_crud``).
        # ------------------------------------------------------------------
        user_a = await authenticated_styrmin_client.users.create(
            username=username_a,
            password=password,
            display_name=f"Member A {suffix}",
            role=Role.READ_ONLY,
        )
        user_a_id = str(user_a.id)
        user_b = await authenticated_styrmin_client.users.create(
            username=username_b,
            password=password,
            display_name=f"Member B {suffix}",
            role=Role.READ_ONLY,
        )
        user_b_id = str(user_b.id)

        # ------------------------------------------------------------------
        # Step 1 + 3: create the group with both members already attached.
        # ------------------------------------------------------------------
        if driver_mode == "api":
            created = await authenticated_styrmin_client.groups.create(
                name=group_name,
                role=Role.READ_WRITE,
                member_ids=[user_a.id, user_b.id],
            )
            group_id = str(created.id)
            assert created.role == Role.READ_WRITE
        else:
            assert session_ui_page is not None
            groups_page = GroupsAdminPage(session_ui_page)
            await groups_page.goto_list()
            await groups_page.open_create_dialog()
            await groups_page.fill_create_form(
                name=group_name,
                role="READ_WRITE",
                member_usernames=[username_a, username_b],
            )
            await groups_page.submit_create()
            # Resolve the id via SDK — the row carries ``data-group-id``
            # but the SDK lookup is the canonical path.
            groups = await authenticated_styrmin_client.groups.list()
            match = next(g for g in groups if g.name == group_name)
            group_id = str(match.id)

        assert await _member_ids(authenticated_styrmin_client, group_id) == {
            user_a_id,
            user_b_id,
        }

        # ------------------------------------------------------------------
        # Step 4: deactivate User B. Done through the SDK in both modes
        # (the deactivate path is covered end-to-end by
        # ``test_admin_user_crud``; here it's just a fixture step).
        # ------------------------------------------------------------------
        await authenticated_styrmin_client.users.update(user_b_id, active=False)

        # ------------------------------------------------------------------
        # Step 5: editor surfaces both members. Inactive A in the active
        # list, inactive B in the inactive sub-list. ui-variant only —
        # the api equivalent is "membership set is unchanged", which we
        # assert below.
        # ------------------------------------------------------------------
        if driver_mode == "ui":
            assert session_ui_page is not None
            groups_page = GroupsAdminPage(session_ui_page)
            await groups_page.goto_detail(group_id)

            active_row = groups_page.active_member_row(user_a_id)
            await expect(active_row).to_be_visible(timeout=10_000)
            active_checkbox = active_row.locator(f"#group-member-{user_a_id}")
            assert await active_checkbox.is_checked()

            inactive_row = groups_page.inactive_member_row(user_b_id)
            await expect(inactive_row).to_be_visible(timeout=10_000)
            inactive_checkbox = inactive_row.locator(
                f"#group-inactive-member-{user_b_id}"
            )
            assert await inactive_checkbox.is_checked()

        # Both variants: a fresh SDK observation still sees both
        # members — the deactivate of B did not implicitly drop them.
        assert await _member_ids(authenticated_styrmin_client, group_id) == {
            user_a_id,
            user_b_id,
        }

        # ------------------------------------------------------------------
        # Step 6: save the editor with no changes; both members must
        # remain. Pre-Phase-2-B1 the ui form would have submitted a
        # memberIds replacement of [activeMembersOnly], silently
        # dropping User B. The api variant exercises the equivalent
        # safety check: ``update(memberIds=[A,B])`` with no real change
        # is a no-op for the persisted set.
        # ------------------------------------------------------------------
        if driver_mode == "ui":
            groups_page = GroupsAdminPage(session_ui_page)
            await groups_page.save_no_changes()
        else:
            # api equivalent: re-send the current membership list and
            # confirm the persisted set is unchanged.
            await authenticated_styrmin_client.groups.update(
                group_id, member_ids=[user_a.id, user_b.id]
            )

        assert await _member_ids(authenticated_styrmin_client, group_id) == {
            user_a_id,
            user_b_id,
        }, (
            "Phase 2 B1 regression: saving the group editor without changes "
            "must preserve inactive members (User B)."
        )

        # ------------------------------------------------------------------
        # Step 7: remove B explicitly — only A remains.
        # ------------------------------------------------------------------
        if driver_mode == "ui":
            groups_page = GroupsAdminPage(session_ui_page)
            # The page is already on /groups/$id from step 6.
            await groups_page.uncheck_inactive_member(user_b_id)
        else:
            await authenticated_styrmin_client.groups.update(
                group_id, member_ids=[user_a.id]
            )

        assert await _member_ids(authenticated_styrmin_client, group_id) == {
            user_a_id,
        }

        # ------------------------------------------------------------------
        # Step 8: LAST_ADMIN guard. The seeded admin is the only active
        # admin on this fixture — demoting them or deactivating them
        # must return LAST_ADMIN. We probe via SDK in both modes
        # (server-side guard is mode-independent and asserting it
        # through the UI doubles the test runtime without adding signal:
        # the ui editor surfaces the same error inline, but the guard
        # fires in the resolver).
        # ------------------------------------------------------------------
        admin_username, _ = admin_credentials
        admin_listing = await authenticated_styrmin_client.users.list(active=True)
        admin_user = next(u for u in admin_listing if u.username == admin_username)

        with pytest.raises(OperationFailedError) as excinfo:
            await authenticated_styrmin_client.users.update(
                str(admin_user.id), role=Role.READ_ONLY
            )
        assert excinfo.value.typename == "LAST_ADMIN", (
            f"expected LAST_ADMIN guard, got {excinfo.value.typename!r}"
        )

        # ------------------------------------------------------------------
        # Cleanup setup: explicitly delete the group while we still hold
        # its id; the surrounding ``finally`` will then clean the users.
        # We delete the group here (not in finally) so the test's
        # "clean state on success" reads as part of the scenario rather
        # than as best-effort teardown.
        # ------------------------------------------------------------------
        await authenticated_styrmin_client.groups.delete(group_id)
        group_id = None

    finally:
        # Order: groups before users (group delete is allowed even when
        # members exist; user delete fails on referencing groups).
        if group_id is not None:
            await _delete_group_quietly(authenticated_styrmin_client, group_id)
        if user_a_id is not None:
            await _delete_user_quietly(authenticated_styrmin_client, user_a_id)
        if user_b_id is not None:
            await _delete_user_quietly(authenticated_styrmin_client, user_b_id)
