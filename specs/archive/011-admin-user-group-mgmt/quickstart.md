# Quickstart: Admin User & Group Management

**Feature**: 011-admin-user-group-mgmt
**Audience**: An operator (or reviewer) who wants to verify the feature end-to-end without reading source.

## Prerequisites

1. Local Styrmin checkout up to date with `develop` (#179 merged).
2. `uv sync` + `cd frontend && pnpm install` done.
3. Dev environment running: `uv run invoke dev` (Postgres, backend, frontend).
4. The backend bootstrap step has logged a generated admin password — copy it from the log line `Bootstrapped admin user 'admin' with a generated password ...`. (If you set `STYRMIN_ADMIN_PASSWORD` in your env, use that.)

## A. Browser walkthrough — full user lifecycle without SDK

1. Open `http://localhost:3000` → you land on `/login`.
2. Sign in as `admin` with the bootstrap password.
3. Header should show "admin" with an ADMIN badge. Click the header avatar to see Profile + Logout.
4. Navigate to `/users`. The table shows the seeded admin.
5. Click "Create user":
   - Username: `alice`
   - Display name: `Alice Example`
   - Password: any string ≥8 chars
   - Role: `READ_WRITE`
   - Groups: leave empty
   - Submit. Alice now appears in the table.
6. Click Alice's row → `/users/<id>`. Change display name to `Alice E.` and submit → the table reflects the change after navigating back.
7. On Alice's detail page, click "Reset password" → confirm a new password. Toast: "Password reset. All of Alice's sessions have been invalidated."
8. Edit Alice → set `active` to `false`. Toast: "User deactivated."
9. Edit Alice → set `active` back to `true`.
10. Try to delete the seeded admin (yourself) → toast: "LAST_ADMIN — cannot leave the system with zero active admins."
11. Delete Alice (no deployments yet → no FK references) → toast: "User deleted."

## B. Groups walkthrough

1. Navigate to `/groups`. Click "Create group":
   - Name: `platform-admins`
   - Role: `ADMIN`
   - Members: add `admin`
   - Submit.
2. Open `/groups/<id>` of the new group, change role to `READ_WRITE`, save → admin's effective role drops only if admin is no longer admin elsewhere. (In practice the admin's direct role is still ADMIN, so this is safe.)
3. Try to delete `platform-admins` after removing admin's direct ADMIN role and demoting → LAST_ADMIN guard kicks in.

## C. Role-gated UI

1. Create a `read_only` user (`viewer` / `Viewer`). Log out → log in as viewer.
2. Confirm:
   - No "Users" or "Groups" nav entries.
   - No "Create deployment", "Edit env vars", etc. mutation buttons on any page.
   - Manually navigating to `/users` redirects to `/`.
3. Navigate to `/profile`. Change own display name. Save. Header updates.
4. Change own password (current password correct). Open a separate browser/private window, log in as the same viewer with the new password — both sessions should be active. Now repeat the password change in window A → window B's next request returns UNAUTHENTICATED and that window redirects to `/login`; window A keeps working.

## D. Admin via group membership only

1. Create a `read_only` user `bob`. Add `bob` to `platform-admins` (where role=ADMIN).
2. Log out → log in as `bob`.
3. Confirm `bob` sees the Users/Groups nav and the admin-only mutation buttons even though `bob.role = READ_ONLY`. This proves `IfRole` reads `effectiveRole`, not `role`.

## E. SDK walkthrough (optional — same lifecycle via Python)

```python
import os, asyncio
from styrmin_sdk import StyrminClient

async def main():
    async with StyrminClient(server_address="http://localhost:8000") as c:
        await c.auth.login("admin", os.environ["STYRMIN_ADMIN_PASSWORD"])
        alice = await c.users.create(
            username="alice", password="hunter22!", display_name="Alice", role="READ_WRITE"
        )
        await c.users.update(alice.id, role="READ_ONLY")
        await c.users.reset_password(alice.id, "new-pass-123")
        await c.users.update(alice.id, active=False)
        await c.users.delete(alice.id)
        print(await c.users.list())

asyncio.run(main())
```

## F. End-to-end lifecycle test (CI surface)

```bash
# Single dual-entrypoint scenario, runs as both [api-chromium] and [ui-chromium]:
sleep infinity | uv run pytest backend/tests/e2e/test_auth_lifecycle.py -v -s --pdb 2>&1 | tee /tmp/auth_lifecycle.log
```

This MUST pass before the feature is considered done. The `[ui-chromium]` variant drives the actual login form (does not use Playwright cookie injection). The `[api-chromium]` variant calls `client.auth.login()` directly.

## G. Generated documentation

`dev/guides/users-and-groups.md` ships in this feature. After Phase 4 it covers everything in this Quickstart plus:

- Role semantics (READ_ONLY / READ_WRITE / ADMIN)
- Default-admin bootstrap (`STYRMIN_ADMIN_PASSWORD` env, generated-password log line)
- "Hide-not-disable" rationale
- Effective role and group-conferred elevation
- How to recover when "I locked myself out": there is no recovery flow in v1 — re-bootstrap via env var.
