---

description: "Task list for 020-driver-info-display"
---

# Tasks: Driver Logo, Description and Links

**Input**: Design documents from `specs/020-driver-info-display/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution §V asks for unit tests, GraphQL propagation tests and an E2E test with local PASS evidence.

**Organization**: Tasks are grouped by user story. The backend storage and API are shared by every story, so they are in Phase 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story from spec.md (US1–US4)

## Path Conventions

Web application: `backend/styrmin_backend/`, `backend/tests/`, `frontend/src/`, plus `driver/`, `docs/docs/`, `CONTEXT.md`, `changelog/` at the repository root.

---

## Phase 1: Setup

**Purpose**: Tooling the later tasks need.

- [X] T001 Install frontend dependencies so `uv run invoke generate` can run the frontend codegen: `cd frontend && pnpm --ignore-workspace install`. Confirm that `frontend/node_modules/.bin/graphql-codegen` exists. Do not commit lockfile changes. This worktree sits inside emdash's pnpm workspace, so `export npm_config_ignore_workspace=true` before `uv run invoke generate|lint` and before each `git commit` (the pre-commit frontend hook calls pnpm).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Validate, store and expose `spec.info.icon`, `description` and `links`. All four user stories depend on this phase.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] In `backend/styrmin_backend/services/driver/models/resources/driver.py`, change `Info.icon` to `HttpUrl | None = None` and `Info.links` to `list[InfoLink] | None = None`; keep `InfoLink` (`link: str`, `url: HttpUrl`, `extra="forbid"`). Update the module docstring example (line ~12, `icon: xxxx`) to a valid `https` URL (research R3).
- [X] T003 [P] Replace `icon: xxxx` with `icon: https://docs.infrahub.app/img/infrahub-logo.svg` in the two test fixtures `backend/tests/unit/services/driver/fixtures/local_driver_directory/driver.styrmin.yml` and `backend/tests/unit/services/driver/fixtures/syntax/valid.yaml` (critique E2). Run `uv run pytest backend/tests/unit/services/driver backend/tests/unit/services/test_applications_upsert_idempotent.py -q` and confirm it passes after T002.
- [X] T004 Add three nullable fields to `ApplicationDriverVersion` in `backend/styrmin_backend/db/models.py`, after `container_overrides`: `icon: str | None = None`, `description: str | None = None`, `links: list | None = Field(default=None, sa_column=Column(JSON))`. Add a 1–2 line comment per field naming `spec.info.<field>` (data-model.md).
- [X] T005 Create the Alembic revision `backend/styrmin_backend/db/migrations/versions/<rev>_add_driver_version_info.py`, with `down_revision = ("c2ff6dba5ffd", "f3a4b5c6d7e8")` (merge of the two current heads, research R2). `upgrade()` adds `icon` and `description` (`sqlmodel.sql.sqltypes.AutoString()`, nullable) and `links` (`sa.JSON()`, nullable) to `applicationdriverversion`; `downgrade()` drops them in reverse order. Follow the docstring style of `a8b9c0d1e2f3_add_driver_fingerprint_and_container_overrides.py`. Then confirm one head with `uv run python -c 'from alembic import command; from styrmin_backend.cli.db import _get_alembic_config; command.heads(_get_alembic_config())'`.
- [X] T006 [P] Add `backend/tests/unit/db/test_driver_info_migration.py`, modeled on `backend/tests/unit/db/test_empty_dedicated_ingress_migration.py` (parametrized `postgresql` + `sqlite`). Assert:
  - The script directory has exactly one head, equal to the new revision.
  - Upgrading from each parent to the new revision adds the three columns, and an existing `applicationdriverversion` row reads NULL in all three.
  - Downgrading removes them.
- [X] T007 In `backend/styrmin_backend/services/applications.py`, add a module-level helper `_driver_info_columns(info: Info) -> dict[str, object]` (import `Info` from `styrmin_backend.services.driver.models.resources.driver`; `Specification.info` is a required field) that returns `{"icon": str(info.icon) if info.icon else None, "description": info.description or None, "links": [link.model_dump(mode="json") for link in info.links or []] or None}` (research R4). Pass `**_driver_info_columns(driver_object.driver_spec.spec.info)` to the `ApplicationDriverVersion(...)` constructor in `load_application_driver_from_object`.
- [X] T008 In `backend/styrmin_backend/api/definitions/application_driver/model.py`:
  - Add a Strawberry type `DriverLink` (`label: str`, `url: str`, `from_dict(data)` mapping `data["link"]` → `label`), with the descriptions from contracts/graphql.md.
  - On `ApplicationDriverVersion`, add `icon: str | None = None` and `description: str | None = None` as fields set in `from_instance`, and a `links` resolver returning `[DriverLink.from_dict(d) for d in self.instance.links or []]`.
  - Use the field descriptions from contracts/graphql.md.
- [X] T009 Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`). Add `icon` and `description` to `versions` in `frontend/src/graphql/list_drivers.graphql`, and `icon`, `description` and `links { label url }` to `versions` in `frontend/src/graphql/get_driver.graphql`. Then run `uv run invoke generate` and `uv run invoke validate-graphql`. Commit `schema.graphql`, `python_sdk/src/styrmin_sdk/graphql/_generated/` and `frontend/src/generated/graphql.ts`.
- [X] T010 Add GraphQL propagation tests to `backend/tests/functional/graphql/test_application_driver_version_propagation.py`, with new operations in `backend/tests/functional/graphql/operations/` (`load_local_driver_info.graphql`: mutation `LoadLocalDriverInfo` returning `id applicationDriverId icon description links { label url }`; `get_driver_info.graphql`: query `GetDriverInfo` over `applicationDriver.versions { id icon description links { label url } }`). Tests:
  - (a) Write a local driver with `info.icon`, `info.description` and two `info.links` (helper next to `_write_container_driver`), load it, read the `ApplicationDriverVersion` row from `session`, and assert the three columns.
  - (b) Query `GetDriverInfo` and assert `icon`, `description` and `links` (labels and URLs in file order).
  - (c) Seed a row with `seed_application_driver_version` (no info) and assert GraphQL returns `null`, `null` and `[]`.
  - (d) Load a driver with `description: ""` and `links: []`, and assert `null` and `[]`.

**Checkpoint**: The backend stores and exposes the three fields; `uv run pytest backend/tests/unit/db backend/tests/functional/graphql/test_application_driver_version_propagation.py -q` passes.

---

## Phase 3: User Story 1 - Recognize each driver by its application's logo (Priority: P1) 🎯 MVP

**Goal**: The driver list and detail pages show each driver version's logo, and the generic package icon when there is none or it fails to load.

**Independent Test**: Load a driver with `spec.info.icon` and one without, open `/drivers` and `/drivers/<id>`, and check the image or fallback in each place (spec US1).

### Tests for User Story 1

- [ ] T011 [P] [US1] Add `frontend/src/__tests__/drivers/DriverLogo.test.tsx`. Assert:
  - With `icon` set, an `<img>` with that `src`, `alt=""` and `referrerpolicy="no-referrer"` renders inside `[data-testid=driver-logo][data-logo-state=image]`.
  - With `icon` null or `""`, `data-logo-state="fallback"` and no `<img>`.
  - After `fireEvent.error(img)`, it switches to fallback.
  - Re-rendering with a different `icon` returns to `image`.
- [ ] T012 [P] [US1] In `frontend/src/__tests__/drivers/driverList.test.ts`, add tests that `filterDrivers` sets `latestVersion` to the latest-wins version of the full set, including when the query filters that version out of `versions`.

### Implementation for User Story 1

- [ ] T013 [P] [US1] Create `frontend/src/pages/drivers/DriverLogo.tsx` per contracts/ui.md and research R7:
  - Props `icon?: string | null` and `size?: "sm" | "md"` (`sm` = 20 px, `md` = 32 px frame with the current `AppGroup` frame style).
  - A `failed` state that `onError` sets and that resets when `icon` changes.
  - Renders the `<img alt="" referrerPolicy="no-referrer" loading="lazy" decoding="async" className="h-full w-full object-contain">`, or the lucide `Package` icon with `aria-hidden`.
  - Root carries `data-testid="driver-logo"` and `data-logo-state`.
- [ ] T014 [P] [US1] In `frontend/src/pages/drivers/lib/driverList.ts`, add `latestVersion: DriverListVersion | undefined` to `FilteredDriver`, and set it in both branches of `filterDrivers` from the unfiltered latest-first list (the same source as `latestVersionId`).
- [ ] T015 [P] [US1] In `frontend/src/components/PageLayout.tsx`, add an optional `icon?: ReactNode` prop rendered before the `<h1>` inside a `flex items-center gap-3` wrapper; the layout is unchanged when `icon` is not passed.
- [ ] T016 [US1] In `frontend/src/pages/drivers/DriverListPage.tsx`:
  - `AppGroup`: give the root `data-testid="driver-group"` and `data-driver-name={driver.name}`, and replace the `<Package>` frame with `<DriverLogo icon={driver.latestVersion?.icon} size="md" />`.
  - `FlatTable` rows: render `<DriverLogo icon={version.icon} size="sm" />` before the driver name.
  - Remove the `Package` import if it is no longer used.
- [ ] T017 [US1] In `frontend/src/pages/drivers/DriverDetailPage.tsx`, pass `icon={<DriverLogo icon={selected.icon} size="md" />}` to `PageLayout`.
- [ ] T018 [US1] Extend `frontend/src/__tests__/drivers/DriverListPage.test.tsx` and `frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx`. Assert:
  - The group header shows the latest version's logo `src`.
  - A driver without `icon` shows `data-logo-state="fallback"`.
  - The flat view shows one logo per row.
  - The detail header shows the selected version's logo and switches when the selected version changes.
  - Update the mocked query fixtures with `icon`, `description` and `links` fields.

### E2E for User Story 1

- [ ] T019 [US1] In `backend/tests/e2e/conftest.py` `git_server`, inside the existing `chart_name` rewrite block, for `name == "simple-app"` only: set `driver_config["spec"].setdefault("info", {})["icon"] = SIMPLE_APP_LOGO_URL` and `["links"] = [{"link": "Documentation", "url": SIMPLE_APP_DOCS_URL}]`. Define module constants `SIMPLE_APP_LOGO_URL = "https://styrmin-e2e.invalid/simple-app-logo.svg"` and `SIMPLE_APP_DOCS_URL = "https://styrmin-e2e.invalid/docs"`. Before editing, grep `backend/tests/e2e` for assertions on the simple-app `info` block or a fixed commit SHA, and confirm none exist (plan Risks).
- [ ] T020 [P] [US1] In `backend/tests/e2e/pages/drivers_list.py`, add `DriversListPage.goto()` (navigate to `/drivers`) and `driver_group_logo(driver_name) -> Locator` for `[data-testid=driver-group][data-driver-name="<name>"] [data-testid=driver-logo]` (contracts/ui.md).
- [ ] T021 [US1] Add `test_driver_logo_description_and_links_render(styrmin_resources, session_ui_page)` to `backend/tests/e2e/test_ui_smoke.py` (module markers already `ci`, `ui_only`, `shard_general`):
  - Inside `try`, register `page.route(SIMPLE_APP_LOGO_URL, ...)` fulfilling with `content_type="image/svg+xml"` and an inline SVG with `width="24" height="24"`.
  - Open `/drivers`. Assert the `simple-app` group logo has `data-logo-state="image"`, its `img` has `src == SIMPLE_APP_LOGO_URL`, and `naturalWidth > 0` (use `expect.poll` or `wait_for_function`).
  - Open `/drivers/<driver_id>`. Assert the header `[data-testid=driver-logo]` is in the `image` state with the same `src`.
  - Call `page.unroute(...)` in `finally` (critique E7/E8).

**Checkpoint**: US1 is visible in the UI and covered by unit tests and the E2E logo assertions.

---

## Phase 4: User Story 2 - Read what the application is and open its links (Priority: P2)

**Goal**: The description is on the list and detail pages, and the links are on the detail Overview tab.

**Independent Test**: Load a driver with a description and two links, then check the list header description and the detail description and links (spec US2).

### Tests for User Story 2

- [ ] T022 [P] [US2] Extend `frontend/src/__tests__/drivers/DriverListPage.test.tsx`. Assert:
  - The group header renders `[data-testid=driver-description]` with the latest version's description and a `title` with the full text.
  - It is absent when the description is null.
  - The flat view renders no description.
- [ ] T023 [P] [US2] Extend `frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx`. Assert:
  - `[data-testid=driver-description]` shows the full text, and HTML characters in it render as text.
  - The Overview tab lists `[data-testid=driver-links]` anchors in order, with `href`, `target="_blank"` and `rel="noopener noreferrer"`.
  - Both elements are absent when the description is null and the links are empty.

### Implementation for User Story 2

- [ ] T024 [US2] In `frontend/src/pages/drivers/DriverListPage.tsx` `AppGroup` header, render `driver.latestVersion?.description` under the driver name as `<p data-testid="driver-description" title={description} className="truncate text-xs text-muted-foreground">` only when set. Keep the version-count text on the right, and make the name/description column `min-w-0` so truncation works.
- [ ] T025 [US2] In `frontend/src/pages/drivers/DriverDetailPage.tsx`:
  - Render `selected.description` as `<p data-testid="driver-description" className="whitespace-pre-line pb-5 text-sm text-muted-foreground">` between the version header row and `<Tabs>`, only when set.
  - In `OverviewPanel`, after the details table, render a "Links" section `<ul data-testid="driver-links">` with one `<a href={url} target="_blank" rel="noopener noreferrer">{label}</a>` per link, only when `version.links.length > 0`, styled like the existing panel (border, `text-sm`, primary link color).
- [ ] T026 [US2] Extend `test_driver_logo_description_and_links_render` in `backend/tests/e2e/test_ui_smoke.py`. On the detail page, assert:
  - `[data-testid=driver-description]` contains the `simple-app` example description ("Simple 3-tier FastAPI application with PostgreSQL").
  - `[data-testid=driver-links] a` with name "Documentation" has `href` starting with `SIMPLE_APP_DOCS_URL`, `target="_blank"`, and `rel` containing `noopener`.
  - On the list page, the `simple-app` group shows the same description.

**Checkpoint**: US1 and US2 work together in the UI and in the E2E.

---

## Phase 5: User Story 3 - Driver authors set and validate the logo, description and links (Priority: P2)

**Goal**: Wrong values fail the load with a field-specific error. The examples and documentation show the format.

**Independent Test**: Load drivers with `icon: xxxx`, `icon: javascript:alert(1)` and a link with no `url`, check each error, then load the `infrahub` example successfully (spec US3).

### Tests for User Story 3

- [ ] T027 [P] [US3] Add `backend/tests/unit/services/driver/test_driver_info.py`:
  - Parametrized valid `icon` values (`https://…/logo.svg`, `http://…/logo.png`) build a `DriverSpec`.
  - Invalid `icon` values (`xxxx`, `logo.svg`, `javascript:alert(1)`, `data:image/png;base64,AAAA`, `ftp://host/logo.png`) raise `pydantic.ValidationError` whose text contains `spec.info.icon`.
  - Invalid `links` entries (missing `url`, extra key `name`, `url: javascript:x`, `url: not-a-url`) raise with `spec.info.links.0`.
  - Through `get_local_driver_loader(tmp_path).load_driver()`, a driver file with `icon: xxxx` raises `DriverLoadingError` whose message contains `spec.info.icon`.
- [ ] T028 [P] [US3] In `backend/tests/functional/graphql/test_application_driver_version_propagation.py`, add a test: loading a local driver with `icon: xxxx` through `loadLocalApplicationDriverVersion` returns a GraphQL error that mentions `spec.info.icon`, and `session` contains no `ApplicationDriver` row with that driver name (FR-005).

### Implementation for User Story 3

- [X] T029 [P] [US3] In `driver/examples/infrahub/driver.styrmin.yml` and `driver/examples/infrahub-enterprise/driver.styrmin.yml`, replace `icon: xxxx` with `icon: https://docs.infrahub.app/img/infrahub-logo.svg` (research R11).
- [ ] T030 [P] [US3] Update `driver/DRIVERS.md`:
  - Schema block comments for `icon` (absolute http/https image URL), `description` and `links` (`link` label + `url`). Correct the `info:` comment from "Optional metadata" to "Required block; every key is optional", which matches `Specification.info: Info` (no default).
  - Replace `icon: xxxx` in the example.
  - Add an "Info block" subsection that covers the following, per contracts/driver-spec.md:
    - Accepted formats.
    - Where each value appears (list group header, flat rows, detail header, description, Overview links).
    - That each viewer's browser loads the image from the URL, so use a trusted, reachable host, or leave it out in air-gapped installations.
    - Square SVG or PNG recommended.
    - The generic icon fallback.
    - That `authors`/`license` are accepted but not shown.
    - That invalid values fail the load.
- [ ] T031 [P] [US3] Update `docs/docs/drivers/creating-a-driver.md` Step 2:
  - Add `icon` and `links` to the example `info` block.
  - Add a note bullet on `info.icon`/`description`/`links` that covers format, where they appear, the viewer's browser loading the image from a host you trust, and validation at load.
- [ ] T032 [P] [US3] Update `docs/docs/reference/driver-api.md` (the `spec.info` line becomes "icon (logo URL), description, links — shown on the driver pages; authors, license") and `docs/docs/concepts-and-architecture/what-is-a-driver.md` (add `icon` to the example `info` block and one sentence saying the driver pages show the logo, description and links).

**Checkpoint**: The validation is tested, and the examples and docs match the implementation.

---

## Phase 6: User Story 4 - Driver versions loaded before this feature get their logo on reload (Priority: P3)

**Goal**: Reloading an unchanged driver fills in its logo, description and links on the existing driver version.

**Independent Test**: Load a driver, clear its three info columns to simulate a pre-feature row, reload, and check the same ID now has the values (spec US4).

### Tests for User Story 4

- [ ] T033 [P] [US4] In `backend/tests/functional/graphql/test_application_driver_version_propagation.py`, add a test:
  - Load the info driver from T010 via `LoadLocalDriverInfo`.
  - Set `icon`, `description` and `links` to `None` on that row through `session`, then commit.
  - Load again, and assert the same `id` is returned and the DB row and `GetDriverInfo` carry the three values.
  - Load a third time, and assert the same `id` and that the number of driver versions for that driver is still 1.

### Implementation for User Story 4

- [ ] T034 [US4] In `backend/styrmin_backend/services/applications.py` `load_application_driver_from_object`, in the `existing_identity is not None` branch:
  - Compute `info = _driver_info_columns(driver_object.driver_spec.spec.info)`.
  - When any `getattr(existing_identity, key) != value`, assign the values, `await uow.commit()`, and return `await uow.application_driver_versions.get(existing_identity.id)` (eager-loaded).
  - Otherwise return `existing_identity` unchanged.
  - Add a 1–2 line comment: the identity tuple pins the file content, so this only fills rows stored before the info columns existed (research R5).
- [ ] T035 [US4] Run `uv run pytest backend/tests/unit/services/test_applications_upsert_idempotent.py backend/tests/functional/graphql/test_application_driver_version_propagation.py -q`, and confirm the existing idempotency tests still pass with the new identity-hit branch.

**Checkpoint**: All four user stories work.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T036 [P] Add a **Driver logo** entry to `CONTEXT.md` under "Application drivers": the image URL in `spec.info.icon` of the driver specification file, stored per application driver version, shown on the driver pages and loaded by each viewer's browser (Styrmin never fetches it), with the generic package icon when it is absent or fails to load. Include `_Avoid_: "driver icon file", "driver avatar"`.
- [ ] T037 [P] Add `changelog/272.added.md` (one line, past tense, user perspective: the driver list and detail pages show each driver's logo, description and links from `spec.info`) and `changelog/272.changed.md` (one line: loading a driver now fails when `spec.info.icon` is not an http/https URL or a `spec.info.links` entry is not exactly `link` + an http/https `url`; replace placeholders such as `icon: xxxx`). Follow `dev/guidelines/changelog.md`.
- [ ] T038 Run `grep -rn "icon: xxxx" --exclude-dir=archive --exclude-dir=node_modules .`, and confirm that the only remaining matches are in `specs/archive/` and in this spec's own artifacts (critique E2).
- [ ] T039 Run `uv run invoke format lint` (stage regenerated files first, because its generated-types check reverts unstaged changes), `cd frontend && pnpm --ignore-workspace lint && pnpm --ignore-workspace exec tsc -b --noEmit`, and `uv run pytest backend/tests/unit backend/tests/functional -q`; fix every failure. Only Node 18 is installed, so run Vitest with a portable Node 22 in the session scratchpad and a scratch `vitest.config.mjs` with absolute paths (see the memory note `pnpm-ignore-workspace-in-emdash-worktrees`).
- [ ] T040 Run `uv run invoke generate-validate` (or `uv run invoke generate` followed by `git diff --exit-code schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated`), and confirm the generated files are current.
- [ ] T041 Run the E2E locally to a PASS:
  - Command: `sleep infinity | uv run pytest "backend/tests/e2e/test_ui_smoke.py::test_driver_logo_description_and_links_render" -v -s --pdb 2>&1 | tee /tmp/e2e-020.log` (the node ID gets the `[ui-chromium]` suffix).
  - Also run `backend/tests/e2e/test_driver_reload_identity.py -k api-chromium` (its fixture changed in T003) in a **separate** pytest session: one entrypoint variant per session, because running `[api-chromium]` and `[ui-chromium]` together breaks the ui variant's `styrmin_resources` setup.
  - For each test, record in the implementation report: node ID, exact command, ISO 8601 timestamp of the passing run, vcluster ID and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, and the verbatim `PASSED` line (Constitution §V).
- [ ] T042 Walk through `specs/020-driver-info-display/quickstart.md` steps 1–4 and 7, and confirm each expected result.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none. T001 is needed before T009.
- **Foundational (Phase 2)**: T002 → T003 (fixtures load only after the model change is in place; both can be edited in parallel). T004 → T005 → T006. T002 + T004 → T007 → T008 → T009 → T010.
- **US1 (Phase 3)**: depends on T009 (generated types). T011/T012/T013/T014/T015 run in parallel; T016 depends on T013 + T014; T017 depends on T013 + T015; T018 depends on T016 + T017; T019 → T021, T020 → T021.
- **US2 (Phase 4)**: depends on US1 T016/T017 (same files) and T021 (same test function).
- **US3 (Phase 5)**: depends on Phase 2 only; it can run in parallel with US1/US2.
- **US4 (Phase 6)**: depends on T007 and T010.
- **Polish (Phase 7)**: after all stories. T041 needs everything, including T003, T019 and T021–T026.

### User Story Dependencies

- **US1 (P1)**: Phase 2.
- **US2 (P2)**: Phase 2, and edits the same files as US1, so it runs after US1.
- **US3 (P2)**: Phase 2. Independent of US1/US2.
- **US4 (P3)**: Phase 2. Independent of the UI stories.

### Parallel Opportunities

- Phase 2: T002 ∥ T003 ∥ T004. T006 ∥ T007 once T005/T004 are done.
- US1: T011 ∥ T012 ∥ T013 ∥ T014 ∥ T015 ∥ T020.
- US3: T027 ∥ T028 ∥ T029 ∥ T030 ∥ T031 ∥ T032, and the whole phase in parallel with US1.
- Polish: T036 ∥ T037.

---

## Parallel Example: User Story 1

```text
Task: "T011 DriverLogo tests in frontend/src/__tests__/drivers/DriverLogo.test.tsx"
Task: "T013 DriverLogo component in frontend/src/pages/drivers/DriverLogo.tsx"
Task: "T014 FilteredDriver.latestVersion in frontend/src/pages/drivers/lib/driverList.ts"
Task: "T015 PageLayout icon slot in frontend/src/components/PageLayout.tsx"
Task: "T020 DriversListPage.driver_group_logo in backend/tests/e2e/pages/drivers_list.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + Phase 2: the backend stores and exposes the fields.
2. Phase 3 (US1): logos appear with a fallback, and the E2E asserts them.
3. Stop and validate with quickstart steps 2, 4 and 6.

### Incremental Delivery

1. US1: logo.
2. US2: description + links.
3. US3: validation tests, examples and docs. Run in parallel with US1 when two people work on it.
4. US4: reload fills in older rows.
5. Polish: glossary, changelog, full checks and E2E evidence.

---

## Notes

- Commit after each phase with a Conventional Commit message (`feat(drivers): …`, `test(drivers): …`, `docs(drivers): …`).
- Keep code comments to 1–3 lines; put the reasoning in commit messages.
- Never edit `CHANGELOG.md`, `schema.graphql` or generated files by hand; regenerate them.
- Use `pnpm --ignore-workspace` for frontend commands in this worktree.
