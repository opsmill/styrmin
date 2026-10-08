# Implementation Plan: Driver Logo, Description and Links

**Branch**: `fac/feat-driver-logo-image-icon-field-model-h8bv3` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-driver-info-display/spec.md`

## Summary

Driver authors already write `spec.info.icon`, `description` and `links` in `driver.styrmin.yml`. Styrmin parses them and then discards them. This change does the following:

- Validates `icon` and `links[].url` as absolute `http`/`https` URLs (Pydantic `HttpUrl`, using the existing `InfoLink` model).
- Stores the three values on `ApplicationDriverVersion` (three nullable columns, one Alembic revision that also merges the two current heads).
- Fills them in on a reload of an unchanged driver.
- Exposes them on the GraphQL `ApplicationDriverVersion` type.
- Renders them on the driver list and detail pages through one `DriverLogo` component, which falls back to the generic `Package` icon when there is no logo or the image fails to load.

The example drivers, `driver/DRIVERS.md`, `docs/`, `CONTEXT.md` and a changelog fragment are updated. A UI E2E in `test_ui_smoke.py` uses the session `simple-app` driver and a Playwright-served logo URL.

## Technical Context

**Language/Version**: Python 3.14+ (backend); TypeScript 5.9.3 / React 19.2.4 (frontend, Node 22)

**Primary Dependencies**: Pydantic v2 (`HttpUrl`), SQLModel/SQLAlchemy async, Alembic, Strawberry GraphQL; TanStack Query v5 + generated hooks, Tailwind, lucide-react; Playwright (E2E)

**Storage**: PostgreSQL. Three nullable columns on `applicationdriverversion` (`icon`, `description` text; `links` JSON) via one Alembic revision that merges heads `c2ff6dba5ffd` + `f3a4b5c6d7e8`.

**Testing**:
- pytest: unit tests for validation and the migration head; functional GraphQL propagation tests.
- Vitest + Testing Library: component and page tests.
- pytest E2E (`[ui-chromium]`, vCluster).

**Target Platform**: Styrmin server (Linux container) and evergreen browsers.

**Project Type**: Web application (backend + frontend) with driver examples and docs.

**Performance Goals**: No new requests to the Styrmin backend; the two queries gain three small fields. Logos load lazily in the browser.

**Constraints**:
- The backend never fetches the logo.
- The browser sends no referrer to the logo host.
- No Content-Security-Policy change.
- The E2E must not depend on internet access.

**Scale/Scope**: About 15 source files and 4 docs pages. One DB revision. Additive GraphQL change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How |
|-----------|--------|-----|
| I. Declarative reconciliation | Pass | Reconciliation is not touched. |
| II. Driver-based deployment | Pass | The values come only from the driver specification file; the driver stays self-contained. |
| III. Layered architecture | Pass | Validation sits in the driver models, persistence and backfill in `services/applications.py` through the UnitOfWork, projection in the GraphQL definitions. No cross-layer shortcut. |
| IV. Type safety and typed errors | Pass | `HttpUrl` and `InfoLink` replace `str` / `dict[str, str]`. Load errors use the existing `DeserializationError` → `DriverLoadingError` path; no union error types. |
| V. Test-first, E2E, propagation | Pass | Unit tests for validation, functional propagation tests for the 3 fields (write, backfill, read), the migration head test, Vitest, and an E2E extension of `test_ui_smoke.py` with local PASS evidence. |
| VI. Format/lint | Pass | `uv run invoke format lint`, frontend lint before each commit (pre-commit hooks). |
| VII. Documentation accuracy | Pass | `driver/DRIVERS.md`, `docs/docs/drivers/creating-a-driver.md`, `docs/docs/reference/driver-api.md`, `docs/docs/concepts-and-architecture/what-is-a-driver.md`, `CONTEXT.md` and a changelog fragment, all in the same change. |
| Governance gates: DB schema, GraphQL schema | Approved | The user asked for this feature (issue #272 names persistence and GraphQL exposure) and approved the design decisions before specification. |
| Governance gate: new dependencies | Pass | None. |

Post-design re-check: no violations; Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/020-driver-info-display/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql.md
│   ├── driver-spec.md
│   └── ui.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── services/driver/models/resources/driver.py      # Info.icon: HttpUrl, Info.links: list[InfoLink]
├── db/models.py                                    # ApplicationDriverVersion.icon/description/links
├── db/migrations/versions/<rev>_add_driver_version_info.py   # merge heads + 3 columns
├── services/applications.py                        # persist on create, fill on identity hit
└── api/definitions/application_driver/model.py     # DriverLink type + 3 fields

backend/tests/
├── unit/services/driver/test_driver_info.py        # validation
├── unit/db/test_driver_info_migration.py           # single head, columns
├── functional/graphql/test_application_driver_version_propagation.py  # + 3 tests
├── functional/graphql/operations/*.graphql         # test operations
└── e2e/
    ├── conftest.py                                 # git_server: inject simple-app info.icon/links
    ├── pages/drivers_list.py                       # driver_group_logo()
    └── test_ui_smoke.py                            # test_driver_logo_description_and_links_render

frontend/src/
├── graphql/list_drivers.graphql, get_driver.graphql
├── components/PageLayout.tsx                       # optional icon slot
├── pages/drivers/DriverLogo.tsx                    # new
├── pages/drivers/DriverListPage.tsx                # group header + flat rows
├── pages/drivers/DriverDetailPage.tsx              # header logo, description, links
├── pages/drivers/lib/driverList.ts                 # FilteredDriver.latestVersion
└── __tests__/drivers/*, __tests__/driver-detail/*  # tests

schema.graphql, python_sdk/src/styrmin_sdk/graphql/_generated/, frontend/src/generated/   # regenerated
driver/DRIVERS.md, driver/examples/infrahub*/driver.styrmin.yml
docs/docs/drivers/creating-a-driver.md, docs/docs/reference/driver-api.md,
docs/docs/concepts-and-architecture/what-is-a-driver.md
CONTEXT.md, changelog/272.added.md
```

**Structure Decision**: Existing web-application layout (`backend/` + `frontend/`). No new packages or modules beyond one React component and test files.

## Implementation Approach

1. **Driver model** (research R3): change `Info.icon` to `HttpUrl | None` and `Info.links` to `list[InfoLink] | None`. Unit-test valid and invalid values through `DriverSpec` and through `DriverLoader` (the error names the field).
2. **DB + migration** (R1, R2): add 3 nullable fields to `ApplicationDriverVersion`, and write the revision with `down_revision = ("c2ff6dba5ffd", "f3a4b5c6d7e8")`. Add a unit test that the script directory has one head equal to the new revision, following `test_steps_migration.py` / `test_empty_dedicated_ingress_migration.py`.
3. **Service** (R4, R5):
   - Add a helper `_driver_info_columns(spec) -> dict` that returns `{"icon", "description", "links"}`, with empty values normalized to `None`.
   - Pass it to the `ApplicationDriverVersion(...)` constructor.
   - On an identity hit, apply it to the existing row when any value differs, `await uow.commit()`, and return `await uow.application_driver_versions.get(id)`.
4. **GraphQL** (R6): add a `DriverLink` Strawberry type with `from_dict`, and add `icon`/`description` as plain fields set in `from_instance` and `links` as a resolver. Regenerate `schema.graphql` and run `uv run invoke generate`.
5. **Propagation tests** (contracts/graphql.md):
   - Add test `.graphql` operations under `backend/tests/functional/graphql/operations/`.
   - Add three tests to `test_application_driver_version_propagation.py`: load → DB + GraphQL; seeded NULL row → reload → same ID filled; seeded NULL row → `null`/`null`/`[]`.
   - Add a rejected load → no driver version for that name.
6. **Frontend** (R7, R8):
   - Add `icon`/`description` to `list_drivers.graphql`, and `icon`/`description`/`links { label url }` to `get_driver.graphql`, then regenerate.
   - Add `DriverLogo`.
   - Add `icon` to `PageLayout`.
   - Add `latestVersion` to `FilteredDriver`.
   - Update the list header, flat rows, detail header, description and Overview links section.
   - Vitest coverage for each.
7. **Examples and docs** (R11): set the infrahub/infrahub-enterprise `icon` to `https://docs.infrahub.app/img/infrahub-logo.svg`, and update `DRIVERS.md`, the three docs pages, `CONTEXT.md` (**Driver logo**) and `changelog/272.added.md`.
8. **E2E** (R10):
   - In the `git_server` fixture, set `spec.info.icon` (`https://styrmin-e2e.invalid/simple-app-logo.svg`) and one `links` entry on the `simple-app` copy.
   - Add `DriversListPage.driver_group_logo()`.
   - Add `test_driver_logo_description_and_links_render` to `test_ui_smoke.py`. It uses `page.route()` to serve an inline SVG, then asserts the list header logo (`data-logo-state="image"`, `naturalWidth > 0`), the detail header logo, the description and the link (`target=_blank`, `rel` contains `noopener`). It then removes the route.
   - Run locally with `--pdb` and record the PASS evidence.

## Risks

- **Develop gains its own merge revision first**: rebase and set `down_revision` to the new single head. The single-head unit test fails until that is done.
- **Third-party driver files with `icon: xxxx` stop loading**: intended (user decision). The changelog and `DRIVERS.md` state it.
- **`HttpUrl` normalization changes the displayed URL text** (trailing slash, lower-case host): accepted, documented in contracts/graphql.md.
- **Changing the `simple-app` E2E driver file** changes the session driver's commit SHA only. No test asserts on the `info` block or on a fixed SHA (verified by grep during implementation).

## Complexity Tracking

No constitution violations.
