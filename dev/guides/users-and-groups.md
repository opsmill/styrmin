# Users and Groups

Operator guide to user, group, and role management in Styrmin. Covers
roles, the bootstrap admin, the admin UI, lockout recovery, the SDK
equivalent, and the "hide-not-disable" UI principle.

## Roles

Styrmin has three flat roles:

| Role | Permitted operations |
|------|----------------------|
| `READ_ONLY` | Read every non-admin resource (deployments, environments, drivers, clusters, services, status). |
| `READ_WRITE` | Everything `READ_ONLY` can do, plus create / edit / delete deployments, environments, env vars, backups, schedules. |
| `ADMIN` | Everything `READ_WRITE` can do, plus manage users, groups, the bootstrap admin, and every admin-only field on the `User` type. |

### Direct role vs. effective role

Every user has a **direct role** (`user.role`, set on the row). Membership
in a group also confers a role — when a user is a member of one or more
groups, the **effective role** is the maximum of the direct role and the
roles of every group the user belongs to. The GraphQL `User` type
exposes both as `role` and `effectiveRole`; the frontend authorization
predicate (`<IfRole minimum=...>`) and the backend `_requires(Role.X)`
extension both read `effectiveRole`, never `role`.

This is what lets an admin grant elevated access by adding a user to a
group (e.g., `platform-admins` with `role=ADMIN`) without changing the
user's direct role.

## Bootstrap admin

The backend bootstrap step (`backend/styrmin_backend/services/auth/bootstrap.py`)
ensures at least one active admin exists at startup.

| Env var | Effect |
|---------|--------|
| `STYRMIN_ADMIN_USERNAME` | Username of the bootstrap admin. Defaults to `admin`. |
| `STYRMIN_ADMIN_PASSWORD` | Password for the bootstrap admin. If unset, a strong random password is generated and logged once. |

When `STYRMIN_ADMIN_PASSWORD` is unset, the server logs a single line on
startup:

```
Bootstrapped admin user 'admin' with a generated password <password>
```

Copy that password from the log — it is not persisted anywhere else and
will not be re-emitted on subsequent restarts (the bootstrap is
idempotent and only sets a password the first time the row is created).
If you lose it, see [Lockout recovery](#lockout-recovery).

## Admin UI walkthrough

The admin UI lives at `/users` and `/groups`. These nav entries only
render for users whose `effectiveRole` is `ADMIN`.

### Users

1. Navigate to `/users`. The table lists every user with their direct
   role, active flag, and group memberships.
2. Click **Create user** to open the create dialog. Required: username,
   display name, password (≥ 8 chars), role. Optional: group memberships.
3. Click any row to open `/users/$id` (the detail page). Inline-edit
   display name, role, active flag, and group memberships from there.
4. **Reset password** opens a confirm dialog and then issues a new
   password. *Every existing session for that user is invalidated* —
   they will be logged out everywhere.
5. **Delete user** hard-deletes the user row. Two guards apply:
   - `USER_HAS_REFERENCES` — the user owns deployments (or any FK
     reference). Reassign or remove those references first.
   - `LAST_ADMIN` — deleting (or deactivating, or demoting) this user
     would leave zero active admins. Promote another user first.

### Groups

1. Navigate to `/groups`. The table lists every group with its
   role and member count.
2. Create a group with **Create group**: name, role, optional initial
   member set.
3. Click any row to open `/groups/$id`. The member multi-select uses
   replace semantics — submitting overwrites the full member set.
4. The `LAST_ADMIN` guard applies to group changes too: removing the
   only admin-conferring membership of the last active admin is
   rejected with `LAST_ADMIN`.

### Profile

Every authenticated user (regardless of role) has a `/profile` page,
reachable from the header avatar menu. Users can edit their own display
name and change their own password from there. Username is read-only —
only an admin can change it (via `/users/$id`).

Changing your own password from `/profile` invalidates **every other**
session you have. Your current session is preserved.

## Lockout recovery

There is no recovery flow in v1. If every admin loses access:

1. Stop the backend.
2. Set `STYRMIN_ADMIN_USERNAME` and `STYRMIN_ADMIN_PASSWORD` in the
   backend environment to credentials you control.
3. Manually mark the bootstrap admin row as needing re-creation by
   deleting it from the database (or directly setting its
   `password_hash` to a new bcrypt hash and `active=true`).
4. Restart the backend. The bootstrap will create (or repair) the
   admin row using the env vars.

This is intentionally crude — a self-service "forgot password" flow is
a future feature, not an v1 requirement.

## SDK equivalent

Every operation in the admin UI is also exposed on `StyrminClient.users`
and `StyrminClient.groups`. Both namespaces require an authenticated
admin session.

```python
import asyncio
import os

from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.enums import Role


async def main() -> None:
    async with StyrminClient(server_address="http://localhost:8000") as client:
        await client.auth.login("admin", os.environ["STYRMIN_ADMIN_PASSWORD"])

        alice = await client.users.create(
            username="alice",
            password="hunter22!",
            display_name="Alice",
            role=Role.READ_WRITE,
        )
        await client.users.update(alice.id, role=Role.READ_ONLY)
        await client.users.reset_password(alice.id, "new-pass-123")
        await client.users.update(alice.id, active=False)
        await client.users.delete(alice.id)


asyncio.run(main())
```

See `python_sdk/examples/users_groups.py` for a ready-to-run version.

## Hide-not-disable

The frontend hides write controls from users who do not have permission
to use them; it does not show greyed-out buttons. This is deliberate:

- A grey "Create deployment" button that does nothing on click is
  noisier than the absence of a button. The UI should reflect the
  effective capability set of the current session.
- The authorisation gate is enforced on the server (the
  `_requires(Role.X)` extension on every mutation); the frontend hide
  is a UX optimisation, not a security boundary.
- The role gating uses `effectiveRole`, so a user with direct role
  `READ_ONLY` but membership in an `ADMIN` group sees the admin UI.

To inspect what a user can see, fetch `currentUser.effectiveRole`:

```graphql
query { currentUser { id username role effectiveRole } }
```

If `effectiveRole` is not what you expect, check the user's group
memberships at `/users/$id` (admin view) — `effectiveRole` is the max
of `role` and the role of every group the user belongs to.
