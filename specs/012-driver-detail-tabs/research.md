# Research: Driver Detail Page Redesign (Tabbed Layout)

**Feature**: `012-driver-detail-tabs`
**Date**: 2026-05-21

Most decisions were resolved in the `/grill-idea` session captured at `.specify/idea-brief.md`. This file records the **technical-context** research that the spec deliberately deferred to planning: existing patterns to reuse, exact shapes to handle, and conventions to match.

## 1. Tab component API

**Decision**: reuse the existing `frontend/src/components/ui/tabs.tsx` primitives.

**API**:

```ts
<Tabs
  tabs={[{ id: "overview", label: "Overview" }, ...]}
  activeTab={activeTab}
  onTabChange={setActiveTab}
/>
<TabPanel active={activeTab === "overview"}>...</TabPanel>
```

**Rationale**: matches the established `DeploymentDetailPage` pattern; no new dependency; integrates with the surrounding `cn` + Tailwind utility classes already used across the app.

**Alternatives considered**:

- Radix `<Tabs>` primitive — already available transitively (used by other UI primitives) but using it directly would deviate from the established two-component pattern (`Tabs` + `TabPanel`) without a strong reason. Rejected.
- New custom tabs component — unnecessary; the existing one is fit for purpose.

## 2. Tab + version selection state

**Decision**: local `useState` for both `activeTab` and `selectedVersionId` in the rewritten `DriverDetailPage`. No URL search-params, no persistence beyond the lifetime of the page.

**Rationale**: matches `DeploymentDetailPage` (which uses local `useState<string>("overview")`). Consistent with the rest of the app. URL persistence is explicitly out of scope per spec assumptions.

**Alternatives considered**:

- TanStack Router `validateSearch` + `useSearch` for URL-persisted tab + version state — more powerful (shareable links) but inconsistent with sibling pages. Rejected; can be added uniformly across detail pages in a future spec.

## 3. Newest-first ordering for driver versions

**Decision**: order **driver versions** by `createdOn` descending **client-side** in the React component, after the GraphQL field is exposed.

**Rationale**: requires only a `Array.toSorted()` on the existing query response. Keeps server-side queries unchanged. Sort key is now a deterministic, comparable timestamp, eliminating the fragility of semver-parsing free-form version strings.

**Alternatives considered**:

- Add `order_by` to the SQLAlchemy `ApplicationDriver.versions` relationship — also acceptable, slightly less explicit. Choosing client-side keeps ordering behaviour visible at the consumer.

## 4. GraphQL `createdOn` field addition

**Decision**: expose a `created_on` resolver on both `ApplicationDriver` and `ApplicationDriverVersion` Strawberry types, surfaced as GraphQL `createdOn: DateTime!`.

**Rationale**:

- Both DB rows already carry `created_on` via `StyrminModel` (server-default `func.now()`, non-null).
- Naming follows Strawberry's automatic snake-case → camelCase mapping (`created_on` Python attribute → `createdOn` GraphQL field).
- The field is non-null because the DB column is non-null and `server_default` is `func.now()`.

**Files to touch**:

- `backend/styrmin_backend/api/definitions/application_driver/model.py` — add `created_on: datetime` to both `ApplicationDriver` and `ApplicationDriverVersion` Strawberry types, populated in their respective `from_instance` classmethods.
- `schema.graphql` — regenerated via `uv run styrmin export graphql-schema schema.graphql`.
- `frontend/src/graphql/get_driver.graphql` — add `createdOn` to both type selections.
- `python_sdk/src/styrmin_sdk/graphql/_generated/` + `frontend/src/generated/graphql.ts` — regenerated via `uv run invoke generate`.

**Alternatives considered**:

- Exposing only on `ApplicationDriverVersion` (sufficient for v1 UI) — rejected because driver-level `createdOn` is symmetric, costs nothing to add, and unblocks future Drivers-list improvements without another schema bump.

## 5. GraphQL propagation test

**Decision**: add `backend/tests/functional/graphql/test_application_driver_created_on_propagation.py` covering both fields.

**Pattern**: follow `test_env_vars_propagation.py` (existing) — seed real rows via the repository layer, run the GraphQL query through `gql(...)` against the real service stack, assert the field value round-trips.

**Test outline**:

1. Seed an `ApplicationDriver` with a known `created_on` (overriding the server default for determinism) and two `ApplicationDriverVersion` rows with distinct `created_on` values.
2. Query `applicationDriver(applicationDriverId: ...) { createdOn versions { id createdOn } }`.
3. Assert `applicationDriver.createdOn` equals the seeded driver timestamp.
4. Assert each version's `createdOn` equals the seeded version timestamp.

**Rationale**: complies with Constitution §V (NON-NEGOTIABLE GraphQL propagation requirement); pattern is well-established in the existing test directory.

## 6. Components JSON shape

**Decision**: render structured rows by extracting the component name (the dict key) and any **declared** scalar/dict fields. Do **not** attempt to extract runtime concepts (containers, ports, resources) — those are mocked in the design but rejected as out of scope.

**Source of truth**: `driver/DRIVERS.md` documents the shape under `spec.components`:

```yaml
components:
  <component-name>:
    identifier:
      label:
        <key>: <value>     # Kubernetes label selector
    # Additional fields allowed (cpu, memory, etc.)
```

Persisted as `ApplicationDriverVersion.components: dict | None` (JSON column on the DB row). In the GraphQL response this comes through as a `JSON` scalar.

**Renderable fields per component** (v1):

- Component name (dict key) — primary identifier.
- `identifier.label` — render as a key/value list ("`service: infrahub-server`").
- Any other declared scalar fields (`cpu`, `memory`, etc.) — render as a key/value list. This is forward-compatible: any field a driver chooses to declare will show up.

**Empty / unexpectedly-shaped declarations**: render the empty-state message per `FR-018`. The renderer must defensively check `typeof components === "object"` and `!Array.isArray(components)` before iterating keys; anything else degrades to the empty state.

**Rationale**: gives users a structured view of the **declared** shape (per the spec) without inventing data, and adapts automatically as drivers add new fields under a component.

**Alternatives considered**:

- Treat `components` as opaque and skip the tab entirely — rejected; the spec explicitly mandates structured rendering (`FR-009`).
- Validate the JSON against a strict Pydantic-derived TypeScript shape — overkill for read-only display; bare runtime checks suffice and absorb future driver-spec additions without code change.

## 7. Relative-time formatting

**Decision**: a small in-component helper that returns a coarse-grained "N units ago" string from a `Date`. No new dependency.

**Rationale**: the relative-time labels are advisory ("2 days ago"); we don't need `date-fns` / `dayjs`-precision formatting. A ~20-line helper at `frontend/src/pages/drivers/driver-detail/relative-time.ts` covers seconds / minutes / hours / days / weeks / months / years. If precision later matters, swap in a library uniformly across the app via a separate spec.

**Alternatives considered**:

- Pull in `date-fns` `formatDistanceToNow()` — adds a dependency for one feature. Rejected (Governance Gate would activate; reuse hand-rolled helper instead).

## 8. E2E test pattern (`ui_only`)

**Decision**: add `backend/tests/e2e/test_driver_detail.py` containing `test_driver_detail_inspects_versions_via_tabs`, marked `@pytest.mark.ci` and `@pytest.mark.ui_only(reason=...)`.

**Pattern**: model after `backend/tests/e2e/test_deployment_detail_header.py` (existing `ui_only` example).

**Test outline**:

1. **Seed** via SDK: create an **application driver** named e.g. `tabs-fixture` with three local-source **driver versions** at distinct `created_on` timestamps; each version has a small distinct set of parameters and at least one component declaration.
2. **Navigate** Playwright to the driver detail page for `tabs-fixture`.
3. **Assert** left rail shows three rows in newest-first order; row 1 has the active-state class.
4. **Assert** the right pane shows the latest version's header and the Overview tab content.
5. **Click** the oldest version row; assert the right pane updates to that version.
6. **Click** the Components tab; assert at least one structured component row is rendered and the page contains no `<pre>` element with JSON-shaped content.
7. **Click** the Source tab; assert the source-type-appropriate text matches the seeded source.

**Why no API variant**: every assertion is about **rendered DOM** (which row has active state, which tab panel is shown, presence/absence of `<pre>`). The SDK has no equivalent of "click a tab". This matches the `@pytest.mark.ui_only` rubric in `AGENTS.md`.

**Local-PASS evidence requirement (Constitution §V NON-NEGOTIABLE)**: the implementer must capture and record, in the spec directory or PR body, (a) pytest node ID, (b) exact pytest command, (c) ISO 8601 timestamp of the passing run, (d) vcluster id from `/tmp/pytest-of-*/pytest-*/`, (e) verbatim `PASSED ...` line. Captured as part of task closure, not as a separate artefact file.

## 9. Frontend unit-test layout

**Decision**: tests live at `frontend/src/__tests__/driver-detail/` mirroring the existing `__tests__/` layout used by `AppShell.test.tsx` and `role_gating.test.tsx`.

**Coverage targets**:

- `DriverDetailPage.test.tsx`:
  - Tab switching preserves the selected version.
  - Version switching preserves the active tab.
  - Empty-versions branch renders the role-gated empty state (Add Version hidden for READ users).
  - Auto-refresh silent-fallback (EC-002): after a refresh removes the previously-selected version, the page silently falls back to the newest version in the refreshed list — explicitly enumerated as a named test case.
- `VersionList.test.tsx`: newest-first ordering by `createdOn`; active-state class on the selected row; source-type indicator for git vs local; long-version-string truncates with full value exposed via `title`.

Both files mock `useGetDriverQuery` with a fixed driver fixture (3 versions, distinct timestamps, mixed source types).

**Alternatives considered**:

- Per-tab unit tests for each `*Tab.tsx` panel — overkill for the empty-state coverage; the page-level test combined with the E2E gives sufficient assurance. Per-tab tests can be added later if a tab grows in complexity.

## 10. Auto-refresh + selected-version drift

**Decision**: on every refresh, the page reconciles the in-memory `selectedVersionId` against the freshly fetched `driver.versions`:

- If the previously-selected version still exists → keep selection unchanged.
- If it has been removed → silently fall back to the newest version in the refreshed list.

**Implementation**: a `useEffect` keyed on `data?.applicationDriver?.versions` that runs the reconciliation. Avoids stale-closure UI showing version content that no longer exists in the data.

**Rationale**: matches `EC-002` from the spec. Silent fallback because the auto-refresh is a background poll and a toast would erode trust.

## 11. Auto-refresh error behaviour (known limitation, preserved)

**Decision**: keep the current behaviour — any `error` returned by `useGetDriverQuery` (including a transient failure during the 10 s auto-refresh poll) replaces the page with `<ErrorState>`.

**Rationale**: this matches the existing `DriverDetailPage` behaviour exactly and matches sibling pages. Changing it (e.g. retaining the last-good snapshot and showing a non-blocking banner) is a project-wide UX improvement, not feature-specific work. Documented as a known limitation here so reviewers do not flag it as a regression.

**Follow-up flag**: a future spec could change `useGetDriverQuery` callers to swallow refresh failures and surface them inline; out of scope for this feature.

## 12. SDK additivity of `createdOn`

**Decision**: the GraphQL schema change is purely additive on existing types and is therefore non-breaking for existing SDK consumers.

**Rationale**: ariadne-codegen generates per-operation TypedDict / Pydantic types from the `.graphql` query files. Callers that do **not** add `createdOn` to their selection set will not see the field in their generated types and are unaffected by the schema change. The only consumers that will see the new field are the two GraphQL operations updated in this feature (`get_driver.graphql` in the frontend; any SDK operation we also update). No callers need to be migrated in lock-step.

## 13. Deploy / rollback strategy

**Decision**: no feature flag.

**Rationale**: this is a UI-only redesign of a single page. Rollback in the unlikely event of a regression is `git revert` of the merge commit plus a redeploy. A feature flag would add code surface for one release and then be removed; the cost outweighs the benefit. The backend GraphQL change (`createdOn` field) is additive and safe to leave in place even if the frontend is rolled back.

## Open Questions

None. All NEEDS CLARIFICATION items from the spec have been resolved here or earlier in the brief.
