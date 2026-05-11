# Contract: Frontend — Admin User & Group Management

**Feature**: 011-admin-user-group-mgmt
**Date**: 2026-05-11

## AuthProvider API

```typescript
// frontend/src/auth/AuthProvider.tsx
type Role = "READ_ONLY" | "READ_WRITE" | "ADMIN";

interface CurrentUser {
  id: string;
  username: string;
  displayName: string;
  role: Role;
  effectiveRole: Role;
  active: boolean;
}

interface AuthContextValue {
  currentUser: CurrentUser | null;   // null = unauthenticated
  loading: boolean;                  // true on initial boot until first currentUser response
  refresh: () => Promise<void>;      // re-issue the currentUser query
  logout: () => Promise<void>;       // call logout mutation + clear context + navigate to /login
}

export const AuthProvider: React.FC<{ children: React.ReactNode }>;
export const useAuth: () => AuthContextValue;
```

Boot behavior:

1. On mount, issue the `currentUser` query via TanStack Query.
2. While the first response is in flight, render a small loading indicator (centered spinner) — block all child rendering until the response.
3. Wire `lib/graphql-fetcher.setUnauthenticatedHandler(...)` to a callback that calls `queryClient.clear()` and `router.navigate({ to: '/login' })`.
4. Push the current `AuthContextValue` into `router.update({ context: { auth: { ... } } })` whenever it changes so route `beforeLoad` guards see fresh state.

## `useEffectiveRole` / `IfRole` API

```typescript
// frontend/src/auth/useEffectiveRole.ts
export function useEffectiveRole(): Role | null;

// frontend/src/auth/IfRole.tsx
interface IfRoleProps {
  minimum: Role;        // shows children when effective role >= minimum
  children: React.ReactNode;
  fallback?: React.ReactNode;   // rendered when role is insufficient; default: render nothing
}
export const IfRole: React.FC<IfRoleProps>;
```

Comparison order: `READ_ONLY < READ_WRITE < ADMIN`.

Usage:

```tsx
<IfRole minimum="READ_WRITE">
  <Button onClick={onCreateDeployment}>Create deployment</Button>
</IfRole>

<IfRole minimum="ADMIN">
  <NavLink to="/users">Users</NavLink>
</IfRole>
```

## graphqlFetcher extension

```typescript
// frontend/src/lib/graphql-fetcher.ts
export class GraphQLTransportError extends Error { /* existing */ }
export class GraphQLOperationError extends Error {
  readonly code: string;
  readonly graphqlMessage: string;
  constructor(code: string, message: string);
}
export class UnauthenticatedError extends GraphQLOperationError { /* code = "UNAUTHENTICATED" */ }
export class ForbiddenError extends GraphQLOperationError { /* code = "FORBIDDEN" */ }

export function setUnauthenticatedHandler(cb: (() => void) | null): void;

export function graphqlFetcher<TData, TVariables>(
  query: string,
  variables?: TVariables,
): () => Promise<TData>;
```

Changes to `graphqlFetcher`:

1. Add `credentials: 'include'` to the `fetch` options.
2. After parsing the body, inspect `json.errors?.[0]?.extensions?.code`:
   - `UNAUTHENTICATED` → call the registered handler (if any), then throw `UnauthenticatedError`.
   - `FORBIDDEN` → throw `ForbiddenError`.
   - Any other defined code → throw `GraphQLOperationError(code, message)`.
   - No `extensions.code` but `errors` present → throw `GraphQLOperationError("UNKNOWN", message)` (preserves current behavior).

Test surface (extend `graphql-fetcher.test.ts`):

| Test | Asserts |
|---|---|
| `sends credentials include` | the `fetch` mock receives `credentials: 'include'`. |
| `UNAUTHENTICATED calls handler` | the registered handler is invoked exactly once. |
| `UNAUTHENTICATED throws UnauthenticatedError` | the thrown error is `instanceof UnauthenticatedError`. |
| `FORBIDDEN throws ForbiddenError without calling handler` | the handler is not invoked; error is `ForbiddenError`. |
| `unknown code throws GraphQLOperationError with code preserved` | round-trip the code. |

## Route map

```text
/                 (existing) — index
/login            NEW — beforeLoad: redirect to '/' when authenticated
/profile          NEW — beforeLoad: require authenticated
/users            NEW — beforeLoad: require admin
/users/$id        NEW — beforeLoad: require admin
/groups           NEW — beforeLoad: require admin
/groups/$id       NEW — beforeLoad: require admin
```

Every existing route gets a global `beforeLoad: require authenticated` at the root level (via `__root.tsx`), with `/login` as the only exempt route. Implementation: a tiny `requireAuth` helper that throws `redirect({ to: '/login', search: { from: location.href } })` when `context.auth.currentUser == null`.

## Header user menu

`frontend/src/components/HeaderUserMenu.tsx`:

```tsx
interface HeaderUserMenuProps {
  user: CurrentUser;
  onLogout: () => Promise<void>;
}
```

Renders:

- display name (truncated if > 20 chars)
- role badge (`READ_ONLY` / `READ_WRITE` / `ADMIN`) derived from `user.effectiveRole`
- menu items: "Profile" (navigates to `/profile`), "Logout" (calls `onLogout`)

`AppShell.tsx` consumes this via `useAuth()` and renders it in the header next to the existing theme toggle.

## LoginPage

`frontend/src/pages/login/LoginPage.tsx`:

- Single form with `username` (text) and `password` (password) inputs.
- Submit → call the `login` mutation via `graphqlFetcher`.
- On success: refetch `currentUser` (triggers AuthProvider transition → router navigates to `/`).
- On failure: render "Invalid username or password." (single generic message; do not distinguish wrong-username from wrong-password).
- No "remember me", no "forgot password" link (out of scope).

## ProfilePage

`frontend/src/pages/profile/ProfilePage.tsx`:

Two independent forms:

1. **Display name** — single text field, calls `updateUser(id=self.id, input={displayName: ...})`. On success: refetch `currentUser`.
2. **Change password** — `currentPassword`, `newPassword`, `newPasswordConfirm` fields, calls `changePassword(currentPassword, newPassword)` mutation (existing from #179). On success: success toast + clear the form. The currently-active session continues to work; other sessions are invalidated server-side.

`newPasswordConfirm` is a client-side check only — the server takes only `newPassword`. Mismatch shows an inline error and does not submit.

## UsersListPage

`frontend/src/pages/users/UsersListPage.tsx`:

- Query `users(active, role, search)` via TanStack Query.
- Filters row: `active` (Yes/No/Any select), `role` (any/READ_ONLY/READ_WRITE/ADMIN select), `search` (text). Filter changes update query variables; new request fires.
- Table columns: `Username`, `Display name`, `Role` (badge), `Groups` (compact list of group names), `Active` (checkmark/x), `Actions` (Edit, Delete).
- Client-side pagination (25 rows per page) over the returned list (the server filter has already narrowed the list).
- "Create user" button (top right) opens a dialog form. Submit calls `createUser`.

Mirrors `pages/backup-storage-locations/` structurally.

## UserDetailPage

`frontend/src/pages/users/UserDetailPage.tsx` (route `/users/$id`):

- Displays user info.
- Inline-edit form for `displayName`, `role`, `active`, `groupIds` (multi-select of `groups()`).
- "Reset password" button opens a confirmation dialog and calls `resetUserPassword`.
- "Delete user" button (only enabled when no FK references — surfaced via a `userCanBeDeleted` flag on the query? **Decision:** do **not** add a server field for "can delete"; rely on the server's `USER_HAS_REFERENCES` error and surface it as a toast. The button is always shown; the error message tells the admin why it failed). On a hard-delete attempt, server returns success or one of `USER_HAS_REFERENCES`, `LAST_ADMIN`.

## GroupsListPage / GroupDetailPage

Mirror UsersListPage / UserDetailPage. `GroupDetailPage` lets the admin set `name`, `role`, and `memberIds` (multi-select of `users(active=true)`). Member list uses set semantics on submission (the full new set replaces the current set).

## Existing pages — apply IfRole

Every existing page that renders a write-mutation button:

```diff
- <Button onClick={onCreateCluster}>Create cluster</Button>
+ <IfRole minimum="READ_WRITE">
+   <Button onClick={onCreateCluster}>Create cluster</Button>
+ </IfRole>
```

Apply to (non-exhaustive — Phase 4 tasks enumerate every site):

- `pages/backup-storage-locations/` — Create / Edit / Delete
- `pages/deployments/` — Create / Delete / Upgrade
- `pages/drivers/` — Add / Delete
- `pages/environments/` — Update env vars / Create / Delete
- `pages/settings/` — any write action

Nav entries in `AppShell.tsx`:

- "Users" → wrap in `<IfRole minimum="ADMIN">`
- "Groups" → wrap in `<IfRole minimum="ADMIN">`

## Test surface (Vitest + RTL)

| Test file | Cases |
|---|---|
| `AuthProvider.test.tsx` | (a) loading spinner before first response; (b) null currentUser → child not rendered; (c) currentUser → child rendered; (d) UNAUTHENTICATED later → handler invoked, queryClient cleared, navigation called. |
| `IfRole.test.tsx` | hide/show by minimum; `effectiveRole` (not `role`) drives the decision. |
| `LoginPage.test.tsx` | happy path triggers mutation + currentUser refetch; error path renders generic message. |
| `ProfilePage.test.tsx` | (a) display-name save calls updateUser; (b) password change happy path; (c) wrong-current-password renders inline error. |
| `UsersListPage.test.tsx` | renders rows from query; role filter updates query variables; client-side pagination. |
| `graphql-fetcher.test.ts` | extended with the four new cases above. |
| `HeaderUserMenu.test.tsx` | displays display name + role badge; logout button calls handler. |
