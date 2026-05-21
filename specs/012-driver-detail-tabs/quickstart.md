# Quickstart: Driver Detail Page Redesign (Tabbed Layout)

**Feature**: `012-driver-detail-tabs`
**Branch**: `012-driver-detail-tabs`

A short guide for implementing and verifying this feature end-to-end. Follow the steps in order — they correspond roughly to the dependency order in `tasks.md`.

## Prerequisites

- On branch `012-driver-detail-tabs`.
- `uv sync` has run (Python deps installed).
- `cd frontend && pnpm install` has run (frontend deps installed; required for `uv run invoke generate` to succeed).
- Pre-commit hooks installed: `uv run invoke pre-commit-install`.

## 1. Backend: expose `createdOn`

1. Edit `backend/styrmin_backend/api/definitions/application_driver/model.py`:
   - Add `created_on: datetime` to the `ApplicationDriver` Strawberry type and populate it in `from_instance`.
   - Add `created_on: datetime` to the `ApplicationDriverVersion` Strawberry type and populate it in `from_instance`.
2. Regenerate the root schema:

   ```bash
   uv run styrmin export graphql-schema schema.graphql
   ```

3. Verify `schema.graphql` now declares `createdOn: DateTime!` on both types.

## 2. Backend: propagation test

Add `backend/tests/functional/graphql/test_application_driver_created_on_propagation.py` (pattern: existing `test_env_vars_propagation.py`).

Run it:

```bash
uv run pytest backend/tests/functional/graphql/test_application_driver_created_on_propagation.py -v
```

This must pass before moving on (Constitution §V NON-NEGOTIABLE).

## 3. Regenerate clients

```bash
uv run invoke generate
```

This regenerates:

- `python_sdk/src/styrmin_sdk/graphql/_generated/` Pydantic types,
- `frontend/src/generated/graphql.ts` TypeScript types.

## 4. Frontend: update the GraphQL operation

Edit `frontend/src/graphql/get_driver.graphql` to add `createdOn` on `applicationDriver` and each `versions[]` entry. Validate:

```bash
uv run invoke validate-graphql
```

Re-run `uv run invoke generate` after the edit so the typed hook now exposes `createdOn`.

## 5. Frontend: scaffold the new component tree

Create the directory `frontend/src/pages/drivers/driver-detail/` and add:

- `types.ts` — exports the `TabId` union and any shared narrowed types.
- `relative-time.ts` — hand-rolled helper returning "N units ago" from a `Date`.
- `DriverHeader.tsx` — title + metadata strip + "Add Version" action (role-gated).
- `VersionList.tsx` + `VersionListItem.tsx` — left rail.
- `VersionDetail.tsx` — right pane container with the version header + `<Tabs>` + `<TabPanel>` switch.
- `VersionHeader.tsx` — version label + source-type pill + source line.
- `tabs/OverviewTab.tsx`, `ParametersTab.tsx`, `ComponentsTab.tsx`, `ActionsTab.tsx`, `SourceTab.tsx`.

## 6. Frontend: rewrite `DriverDetailPage.tsx`

Replace the current implementation. The new page:

- Calls `useGetDriverQuery` (unchanged signature).
- Holds `selectedVersionId` and `activeTab` in local state.
- Initialises `selectedVersionId` on first successful query to the newest version (`createdOn` desc).
- Reconciles `selectedVersionId` on each refresh against the new versions list (silent fallback if missing).
- Passes the sorted list and the active version object down to `VersionList` / `VersionDetail`.

## 7. Frontend: unit tests

Add `frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx` and `VersionList.test.tsx`. Run:

```bash
cd frontend && pnpm test
```

Coverage:

- Tab switch preserves selected version.
- Version switch preserves active tab.
- Empty-versions branch renders the role-gated empty state.
- Versions render newest-first by `createdOn`.
- Source-type indicator differs for git vs local.

## 8. Run the page manually

```bash
uv run invoke dev      # or the project's standard dev launcher
```

Visit a driver detail page in the browser, click through all five tabs, switch between two versions, confirm:

- Latest version is selected by default.
- Tab persists across version switches.
- No `<pre>` JSON dump anywhere on the page (check with DevTools).
- Components tab handles missing data gracefully (test a driver with a `components: null` version if available).

## 9. E2E test

Add `backend/tests/e2e/test_driver_detail.py` containing `test_driver_detail_inspects_versions_via_tabs`, marked `@pytest.mark.ci` and `@pytest.mark.ui_only(reason="...")`.

Pattern: `backend/tests/e2e/test_deployment_detail_header.py`.

Run it with the standard E2E command (note the `sleep infinity |` prefix for non-interactive shells and the `--pdb` convention from `AGENTS.md`):

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_driver_detail.py -v -s --pdb 2>&1 | tee /tmp/driver-detail-e2e.log
```

**Capture local-PASS evidence** per Constitution §V NON-NEGOTIABLE: pytest node ID, exact command, ISO 8601 timestamp, vcluster id from `/tmp/pytest-of-*/pytest-*/`, verbatim `PASSED ...` line. Paste into the PR body or the task checklist.

## 10. Pre-flight before opening PR

```bash
uv run invoke format lint        # backend
cd frontend && pnpm lint && pnpm test
```

All must pass clean.

## Manual smoke checklist

After local install, visit `/drivers/<id>` for a driver with ≥ 2 versions and confirm:

- Left rail orders versions newest-first.
- Clicking an older version updates the right pane within ~1 s, no spinner (data is cached).
- Each of the five tabs renders without errors.
- Components tab shows structured rows for declared components; empty-state message for a version with `components: null`.
- "Add Version" button visible for a READ_WRITE user, hidden for a READ-only user.
- Auto-refresh indicator behaviour matches the existing page (toggle on/off, manual refresh, "last refreshed" timestamp).
