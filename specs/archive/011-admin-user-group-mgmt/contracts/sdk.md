# Contract: Python SDK — Admin User & Group Management

**Feature**: 011-admin-user-group-mgmt
**Date**: 2026-05-11

## Resource namespaces

### `client.users`

```python
class UserResource(BaseResource):
    async def create(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: Role,                          # READ_ONLY | READ_WRITE | ADMIN
        group_ids: list[UUID] | None = None,
    ) -> User:
        """Create a new user. Admin only.

        Raises StyrminGraphQLError with .code in {DUPLICATE_USERNAME, GROUP_NOT_FOUND,
        VALIDATION, FORBIDDEN}.
        """

    async def update(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        role: Role | None = None,
        active: bool | None = None,
        group_ids: list[UUID] | None = None,   # None = leave; [] = clear; [...] = replace
    ) -> User:
        """Partial update. group_ids uses set semantics.

        Raises StyrminGraphQLError with .code in {USER_NOT_FOUND, GROUP_NOT_FOUND,
        LAST_ADMIN, VALIDATION, FORBIDDEN}.
        """

    async def reset_password(
        self, user_id: UUID, new_password: str
    ) -> bool:
        """Reset another user's password. Invalidates all of that user's sessions.

        Raises StyrminGraphQLError with .code in {USER_NOT_FOUND, VALIDATION, FORBIDDEN}.
        """

    async def delete(self, user_id: UUID) -> bool:
        """Hard-delete. Rejected when FK references exist or zero-admins would result.

        Raises StyrminGraphQLError with .code in {USER_NOT_FOUND, USER_HAS_REFERENCES,
        LAST_ADMIN, FORBIDDEN}.
        """

    async def list(
        self,
        *,
        active: bool | None = None,
        role: Role | None = None,
        search: str | None = None,
    ) -> list[User]:
        """List users with optional filters. Bare list, no pagination."""

    async def get(self, user_id: UUID) -> User:
        """Fetch a single user. Raises USER_NOT_FOUND if missing."""
```

### `client.groups`

```python
class GroupResource(BaseResource):
    async def create(
        self,
        *,
        name: str,
        role: Role,
        member_ids: list[UUID] | None = None,
    ) -> Group: ...

    async def update(
        self,
        group_id: UUID,
        *,
        name: str | None = None,
        role: Role | None = None,
        member_ids: list[UUID] | None = None,   # set semantics
    ) -> Group: ...

    async def delete(self, group_id: UUID) -> bool: ...

    async def list(self, *, search: str | None = None) -> list[Group]: ...

    async def get(self, group_id: UUID) -> Group: ...
```

## `.graphql` operation files (under `python_sdk/src/styrmin_sdk/graphql/`)

One operation per file. File name is snake_case of the GraphQL operation name. Every operation MUST be named (`mutation CreateUser { ... }`, not anonymous).

| File | Operation | Type |
|---|---|---|
| `create_user.graphql` | `CreateUser` | mutation |
| `update_user.graphql` | `UpdateUser` | mutation |
| `reset_user_password.graphql` | `ResetUserPassword` | mutation |
| `delete_user.graphql` | `DeleteUser` | mutation |
| `list_users.graphql` | `ListUsers` | query |
| `get_user.graphql` | `GetUser` | query |
| `create_group.graphql` | `CreateGroup` | mutation |
| `update_group.graphql` | `UpdateGroup` | mutation |
| `delete_group.graphql` | `DeleteGroup` | mutation |
| `list_groups.graphql` | `ListGroups` | query |
| `get_group.graphql` | `GetGroup` | query |

### Example: `list_users.graphql`

```graphql
query ListUsers($active: Boolean, $role: Role, $search: String) {
  users(active: $active, role: $role, search: $search) {
    id
    username
    displayName
    role
    effectiveRole
    active
    groups {
      id
      name
      role
    }
    createdOn
    updatedOn
  }
}
```

### Example: `update_user.graphql`

```graphql
mutation UpdateUser($id: UUID!, $input: UpdateUserInput!) {
  updateUser(id: $id, input: $input) {
    id
    username
    displayName
    role
    effectiveRole
    active
    groups {
      id
      name
      role
    }
  }
}
```

## Registration on `StyrminClient`

In `python_sdk/src/styrmin_sdk/client.py`:

```python
from styrmin_sdk.resources.users import UserResource
from styrmin_sdk.resources.groups import GroupResource

class StyrminClient:
    def __init__(self, ...):
        # ... existing ...
        self.users = UserResource(self._transport)
        self.groups = GroupResource(self._transport)
```

## Code-generation step

After adding the `.graphql` files:

```bash
uv run invoke generate
```

regenerates the Pydantic models in `python_sdk/src/styrmin_sdk/graphql/_generated/` from the schema + queries. The resource classes import the generated types.

## Test surface

| Test | Asserts |
|---|---|
| `test_resources_users.py::test_create_round_trip` | `client.users.create(...)` returns a `User` with the expected fields. |
| `test_resources_users.py::test_update_clears_groups` | `group_ids=[]` clears memberships. |
| `test_resources_users.py::test_reset_password_returns_true` | `reset_password` returns `True`. |
| `test_resources_users.py::test_delete_raises_user_has_references` | `delete` raises `StyrminGraphQLError(code='USER_HAS_REFERENCES')`. |
| `test_resources_users.py::test_list_with_filters` | filters apply. |
| `test_resources_users.py::test_forbidden_for_non_admin_token` | with a `read_write` token, every method raises `FORBIDDEN`. |
| Same matrix for `test_resources_groups.py`. | |
