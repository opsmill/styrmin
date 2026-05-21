# Idea Brief: Driver Detail Page Redesign (Tabbed Layout)

**Status**: Ready for /speckit-specify
**Seed**: Redesign the **application driver** detail page (`frontend/src/pages/drivers/DriverDetailPage.tsx`) using "Option A" from the Paper mocks: a left rail listing all **driver versions** + a vertical divider + a right pane with **Overview / Parameters / Components / Actions / Source** tabs. Replace the current raw-JSON dumps of `components` and `componentConfigs` with structured rendering. Selected version persists across tab switches; selected tab persists across version switches.

## Users and Value

**Primary user**: a **platform engineer** who maintains the catalogue of **application drivers**. They land on the driver detail page from the Drivers list to:

- verify what a specific **driver version** declares (helm chart, parameters, components, actions),
- trace where a deployment's behaviour comes from (driver source repo / branch / subpath, or local path),
- decide whether to register a new version.

**Secondary user**: a developer or operator inspecting which **driver version** a live deployment is using, navigating here to understand its declared shape.

**Pain points the redesign targets**:

1. `components` and `componentConfigs` are rendered as raw JSON dumps — hard to scan, looks unfinished.
2. Every **driver version** renders at once, so finding "what does v1.3.0 expose?" requires scrolling past unrelated versions.
3. There is no source-level visibility (repo, branch, subpath) on the page; the user has to click out to GitHub.

**Smallest observable better**: opening any **application driver**, picking a **driver version** from the left rail, and immediately seeing a structured table of that version's parameters — without scrolling past stale content.

## User Journeys

### P1 — Inspect a driver version's parameters

- **Journey**: A platform engineer navigates from the Drivers list to a specific **application driver**'s detail page; they need to confirm which parameters (and defaults) the latest **driver version** exposes.
- **Given** an **application driver** named `nginx-app` with three **driver versions** (`v1.3.0`, `v1.2.1`, `v1.0.0`) exists
- **When** the user navigates to that driver's detail page
- **Then** the left rail shows the three versions in newest-first order, `v1.3.0` is selected by default, and the right pane shows the v1.3.0 overview and parameters table without rendering any other version's content
- **Ships with**: left rail, vertical divider, tab scaffold, Overview tab, Parameters tab.

### P2 — Inspect a driver version's components and actions

- **Journey**: A platform engineer wants to see what components a **driver version** declares and which actions it exposes, in a structured form (not JSON).
- **Given** a **driver version** is selected
- **When** the user clicks the Components tab, then the Actions tab
- **Then** each component renders as a structured row (name + readable subset of declared fields) and each action renders as a card (name, description, location) — with zero raw JSON output on the page
- **Ships independently on top of P1.**

### P3 — Trace where a driver version came from

- **Journey**: A platform engineer needs to know which repository/branch/subpath (or local path) a **driver version** was sourced from.
- **Given** a **driver version** is selected
- **When** the user clicks the Source tab
- **Then** the source repository or local path is rendered (with branch and subpath where applicable), differentiated by `sourceType`
- **Ships independently on top of P1.**

## Functional Requirements (draft)

### System

- **FR-001** System MUST render all **driver versions** for an **application driver** in a left rail in newest-first order by `createdOn`, with the most recent version selected by default on page load. *Verify:* unit test seeds three versions at distinct `createdOn` timestamps and asserts rail order + active-state class.
- **FR-002** System MUST render `parameters` for the selected **driver version** as a structured table — columns: name, label, kind, required-flag, default. *Verify:* unit test asserts N rows for N parameters and a REQUIRED badge where `default` is null/undefined.
- **FR-003** System MUST render `components` and `actions` as structured rows — never as a raw JSON dump. *Verify:* unit test asserts no `<pre>` block with JSON output in either tab.
- **FR-004** System MUST distinguish git-sourced from local-sourced **driver versions** in both the left rail and the Source tab. *Verify:* unit test renders one of each and asserts source-type-specific text.
- **FR-005** System MUST preserve the existing 10-second auto-refresh and the `AutoRefreshIndicator` toggle. *Verify:* the existing query hook usage stays intact; no regression.
- **FR-006** System MUST gate the "Add Version" action behind `IfRole minimum="READ_WRITE"`. *Verify:* unit test renders with a `READ` role and asserts the button is absent.
- **FR-007** System MUST expose `createdOn: DateTime!` on `ApplicationDriver` and `ApplicationDriverVersion` in the GraphQL schema. *Verify:* GraphQL propagation test per `dev/guides/graphql-propagation-tests.md`.
- **FR-008** System MUST display a relative-time label (e.g. "2 days ago") on each **driver version** row, derived from `createdOn`. *Verify:* unit test asserts rendered text given a fixed `createdOn`.

### Users

- **FR-009** Users MUST be able to switch the active **driver version** by clicking a row in the left rail; the right pane updates without a route change; the active tab is preserved. *Verify:* unit test clicks a non-active row and asserts the right pane updates while the active-tab state stays unchanged.
- **FR-010** Users MUST be able to switch between Overview / Parameters / Components / Actions / Source tabs by clicking a tab header; the selected **driver version** is preserved across tab switches. *Verify:* unit test clicks a tab → asserts active panel; clicks a different version → asserts tab stays on the previously-active one.
- **FR-011** Users MUST be able to navigate back to the Drivers list via the breadcrumb. *Verify:* existing breadcrumb behaviour from `PageLayout`.

## Key Entities

| Entity | Status | Role on this page |
| --- | --- | --- |
| **Application driver** | existing | Root of the page; gains `createdOn` field exposure. |
| **Application driver version** | existing | Selected via left rail; drives all tabs; gains `createdOn` field exposure; ordered newest-first. |
| **Parameter** | existing | Rendered as a structured table in the Parameters tab. |
| **Component** (driver-declared) | existing | Rendered as structured rows in the Components tab. Only **driver-declared** shape is surfaced; no runtime data (pods, live containers) is consulted. |
| **Action** | existing | Rendered as a structured card per action in the Actions tab. |

**No new entities.**

## Edge Cases

- **EC-001 Driver with zero versions.** Left rail shows a short "No versions yet" line; right pane shows an empty state with the role-gated "Add Version" button; tabs are not rendered.
- **EC-002 Selected version no longer exists after auto-refresh.** Silently fall back to the new newest version. No error, no toast.
- **EC-003 New version appears during auto-refresh.** Append to the list; do not auto-switch — the user's current selection wins.
- **EC-004 `components` JSON is `null` or unexpectedly shaped.** Components tab shows "This version declares no components" — no JSON dump fallback.
- **EC-005 Empty `parameters` / `actions` / `components`.** Per-tab empty state ("No parameters declared", etc.); no table header when empty.
- **EC-006 Local-source driver version (`sourceType === "local"`).** Source tab renders `sourcePath` (no branch); left rail row shows "local" instead of "git".
- **EC-007 Long parameter list.** Page scrolls naturally; no internal scrolling region inside the tab.

## Success Criteria (draft)

- **SC-001** A platform engineer can locate any declared parameter (name, kind, default, required status) for any **driver version** in under 5 seconds, regardless of how many other versions the driver has.
- **SC-002** Components and actions render structured (one row per item, name visible at first glance) — no raw JSON output appears on the page. Verified by an automated assertion that no `<pre>` block contains JSON-shaped content for any driver's content tabs.
- **SC-003** The page renders without overflow or layout breakage for drivers with up to 20 **driver versions** (left rail scrolls within its column, right pane unaffected). Verified by a fixture-based render test.
- **SC-004** A platform engineer can identify the source (repository or local path; branch where applicable) of any **driver version** without leaving the page.
- **SC-005** Switching between any two **driver versions** of the same **application driver** updates the right pane in under 1 second on a typical engineering laptop. No fresh network round-trip is required (data is cached by the existing query).

## Constitution Alignment

- **§I Declarative state reconciliation.** N/A — read-only UI rendering of existing data; no reconciliation behaviour added or changed.
- **§II Driver-based deployment.** Aligned — this displays what a driver declares; no ad-hoc deployment logic is introduced.
- **§III Layered architecture.** Aligned — the one backend change (`createdOn` exposure) is a thin resolver addition on existing GraphQL types; no cross-layer shortcuts.
- **§IV Typed errors.** No new `ServiceError` subclasses required. View degrades through empty states for missing data; query failures continue to flow through the existing `ErrorState` component.
- **§V E2E coverage (mandatory).** UI-only test: `test_driver_detail_inspects_versions_via_tabs`. Seed an **application driver** with three **driver versions** (distinct `createdOn` timestamps, parameters, components, sources). Navigate to the driver detail page; assert (a) three rows in newest-first order, latest selected by default, parameters table rendered; (b) clicking an older version updates the right pane; (c) Components tab renders structured rows (no `<pre>` JSON); (d) Source tab renders the seeded repo/branch/subpath. Marked `@pytest.mark.ui_only(reason="...")`. Local PASS evidence per §V NON-NEGOTIABLE clause: must record pytest node ID, exact command, ISO timestamp, vcluster id, and verbatim PASSED line.
- **§V GraphQL propagation test (mandatory).** New field; propagation test asserts that `ApplicationDriver(Version).createdOn` propagates from DB row → resolver for both types. Procedure: `dev/guides/graphql-propagation-tests.md`.
- **§VI Format and lint.** Standard pre-commit gate.

## Governance Gates Crossed

- [ ] Database schema change — **No** (`created_on` already exists via `StyrminModel`)
- [x] GraphQL schema change — **Yes**: `createdOn: DateTime!` added to `ApplicationDriver` and `ApplicationDriverVersion`. Acknowledged. Propagation test mandatory.
- [ ] New dependency — **No** (reuses existing `Tabs`/`TabPanel`, `Card`, `Badge`, `Button`, `PageLayout`, `AutoRefreshIndicator`, `IfRole`)
- [ ] CI/CD change — **No**
- [ ] Auth change — **No** (existing `IfRole minimum="READ_WRITE"` gating is preserved)

**Required post-gate artefact regeneration steps** (not separate gates):

1. `uv run styrmin export graphql-schema schema.graphql` — regenerate root schema.
2. Update `frontend/src/graphql/get_driver.graphql` to request `createdOn` on both types.
3. `uv run invoke generate` — regenerate SDK Pydantic types and frontend TypeScript types.

## Assumptions

- `applicationDriver.versions` returns a populated list for normal drivers (≥1 version); zero-version is an edge case.
- `createdOn` will be a timezone-aware timestamp suitable for client-side relative-time formatting; precision matches `StyrminModel.created_on`.
- Platform engineers have **READ_WRITE** role to add versions; **READ** users browse without the "Add Version" affordance.
- Auto-refresh at 10s is acceptable (matches current behaviour); not changing.
- "Newest by `createdOn`" is an acceptable proxy for "latest" — drivers are typically registered in chronological order matching semver progression. Edge cases (re-registering an older version after a newer one) may mis-order; users can scan the version string to confirm.

## Out of Scope (v1)

- Per-version "Used by N deployments" count.
- Action `inputs[]` data and any "Run action" UI (no triggering, not even a stub button).
- Component runtime data (pods, live containers, ports, resource usage).
- Latest commit metadata for git-sourced versions (message, author, sha, file tree).
- Side-by-side diff view between two **driver versions**.
- Inline editing of a **driver version** (the existing "Add Version" flow remains the only mutation path).
- URL search-param persistence for active tab (tab state is local; matches existing convention).
- Filter / search inside the Parameters table.
- Any change to the Drivers list page or other unrelated pages.

## Open Questions

_None remaining. All decisions resolved during grilling on 2026-05-21._
