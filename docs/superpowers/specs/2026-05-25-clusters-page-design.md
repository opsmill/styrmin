# Clusters Page (Frontend)

**Date:** 2026-05-25
**Status:** Approved (brainstorming) — ready for implementation plan

## Goal

Give clusters a dedicated, top-level home in the frontend so the UI is shaped
for multiple clusters from the start, even while exactly one cluster is
supported today.

## Motivation

The Cluster card currently lives at the top of `SettingsPage` and links to
`/settings/clusters/$clusterId`. Conceptually a cluster is a first-class
infrastructure object, not a setting. Moving it out also lets the sidebar
separate operational navigation (Environments, Drivers, Backup Storage) from
infrastructure/admin (Clusters, Settings) — making space for additional
clusters as that feature matures.

## Scope

In scope:

- New `/clusters` list page (card grid, built for N clusters).
- Move cluster detail from `/settings/clusters/$clusterId` to
  `/clusters/$clusterId` (hard URL cut, no redirect).
- Sidebar entry "Clusters" in the bottom group, immediately above Settings.
- Remove the Cluster section from `SettingsPage` entirely (helper, query,
  imports, dialog trigger).
- Hide the Settings sidebar entry for non-admin users.
- Tests and documentation updates that the project's standards require.

Out of scope:

- Backend / GraphQL changes. The existing `clusters` query and
  `CreateClusterDialog` flow are reused as-is.
- Multi-cluster behaviour beyond layout (single-cluster guard rails stay
  where they are — e.g., dialog only shown when zero clusters exist).
- Renaming or changing cluster fields, configuration UI, or environment
  lists inside the detail page.

## Design

### Sidebar (`src/components/AppShell.tsx`)

`bottomNavItems` becomes:

```ts
const bottomNavItems = [
  { label: "Clusters", icon: Server, href: "/clusters", exact: false },
  { label: "Settings", icon: Settings, href: "/settings", exact: false },
];
```

The Settings entry is rendered conditionally via `IfRole minimum="ADMIN"`
(the Settings page only contains the Access/Users/Groups section after this
change, which is already admin-only). The Clusters entry is visible to all
authenticated roles.

Visual separation from the top group is unchanged — the bottom group already
sits behind a `border-t` divider in the sidebar.

### Routes

- New `src/routes/clusterList.tsx` → path `/clusters` → lazy-loads
  `@/pages/clusters/ClusterListPage`.
- Existing `src/routes/clusterDetail.tsx` path changes:
  `/settings/clusters/$clusterId` → `/clusters/$clusterId`. Component file
  also moves: `pages/settings/ClusterDetailPage.tsx` →
  `pages/clusters/ClusterDetailPage.tsx`.
- `clusterListRoute` registered in `src/routeTree.ts`.

No redirect is added — bookmarks pointing at the old URL will 404, which is
acceptable because the page has not been around long enough to be widely
bookmarked.

### `ClusterListPage` (new)

`src/pages/clusters/ClusterListPage.tsx`:

- Uses `useListClustersQuery` (already generated, same hook the Settings
  page used).
- `PageLayout` with title "Clusters" and breadcrumb `[{ label: "Clusters" }]`.
- Actions slot: `CreateClusterDialog` trigger, wrapped in
  `IfRole minimum="READ_WRITE"`, only rendered when `clusters.length === 0`
  (preserves today's single-cluster invariant — same condition the Settings
  page uses).
- Empty state: `EmptyState` with the existing copy ("No cluster has been
  configured yet. Create one to get started.").
- Populated state: `grid gap-4 sm:grid-cols-2 lg:grid-cols-3` of cards. Each
  card mirrors today's Settings card (Database icon, name, monospace id,
  `ConfigSummary` of `cluster.config`) and links to `/clusters/$clusterId`.
  `data-testid="cluster-card"` and the `data-cluster-*` attributes that
  existing tests rely on are preserved.
- Error / loading: `ErrorState` and `LoadingState`, same as today.

The `ConfigSummary` helper that lives inside `SettingsPage.tsx` moves with
the section — extracted to
`src/pages/clusters/ConfigSummary.tsx` so both list and detail page can
import it. (Detail page still uses `ConfigSection` for the full table; the
small list summary is its own helper.)

### `ClusterDetailPage` tweaks

- File moves to `src/pages/clusters/ClusterDetailPage.tsx`.
- `useParams({ from: "/settings/clusters/$clusterId" })` →
  `useParams({ from: "/clusters/$clusterId" })`.
- Breadcrumbs:
  `[{ label: "Clusters", href: "/clusters" }, { label: cluster.name }]`.

### `SettingsPage`

- Drop the Cluster section entirely (heading, `CreateClusterDialog`,
  `EmptyState`, the cluster card, the loading/error branches, the
  `ConfigSummary` helper, and the `useListClustersQuery` /
  `CreateClusterDialog` imports).
- Remaining content: the `IfRole minimum="ADMIN"` Access section
  (Users / Groups cards). Page is now admin-only in practice — matching the
  sidebar hiding decision above.

## Tests

- New `ClusterListPage.test.tsx` covering: loading, error+retry, empty
  state with the create dialog trigger, and populated state with one card
  rendered.
- `AppShell.test.tsx`: assert "Clusters" is rendered in the bottom nav,
  Settings is rendered only when the auth context provides an ADMIN user,
  and "Clusters" appears above "Settings".
- Update any `SettingsPage` test that asserts on the cluster section — drop
  those assertions or move them to the new file.
- Search and update any references to `/settings/clusters/` in tests
  (Vitest + any Playwright/E2E specs).

## E2E and propagation tests

No GraphQL schema changes ⇒ no propagation tests needed.

E2E impact: any UI-variant E2E that navigates to `/settings` to find the
cluster card (e.g., create-cluster scenarios) must be updated to navigate to
`/clusters`. Specifically check fixtures and page objects in
`backend/tests/e2e/` for hardcoded `/settings/clusters` paths or
`data-testid="cluster-card"` lookups under the Settings page.

## Documentation

- Update any `docs/` pages that describe how to find or create the cluster
  in the UI (likely the install / quickstart pages reachable from
  `docs/installation/` and `docs/how-it-works/`).
- Add a one-line entry in CONTEXT.md only if a new term is introduced —
  none here, so likely no CONTEXT.md change.
- No ADR required: this is a routine UI relocation, not an architecture
  decision.

## Risks / Open Questions

- Empty `/settings` for ADMIN with no Users/Groups configured is unchanged
  by this work but worth noting if a follow-up wants to rename Settings to
  "Access" outright. Out of scope here.
- If a future cluster creation flow needs to live somewhere reachable when
  one cluster already exists, that lives on the new Clusters page rather
  than Settings.
