---

description: "Task list for Infrahub MCP Server Application Driver"
---

# Tasks: Infrahub MCP Server Application Driver

**Input**: Design documents from `/specs/015-infrahub-mcp-driver/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED. The unit deserialize + parameter-validator + Jinja2 render tests are the owner-approved substitute for an E2E (Constitution §V deviation, recorded in plan Complexity Tracking). They are part of this feature's definition of done.

**Organization**: Tasks grouped by user story. This is a single-Driver, two-artifact feature, so US2–US4 extend the same manifest/template/test files US1 creates and therefore run **sequentially after US1** (not in parallel across stories).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US4)

## Path Conventions

Driver artifacts under `driver/examples/infrahub-mcp/`; docs under `driver/DRIVERS.md` and `docs/docs/drivers/`; unit tests under `backend/tests/unit/services/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the driver directory and pin the external contract before any manifest is written.

- [X] T001 Create the driver directory `driver/examples/infrahub-mcp/` (empty, ready for the two artifacts).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Resolve the PRD Open Question (critique E1/X1) so the manifest is built against the real chart, not assumptions.

**⚠️ CRITICAL**: T002 MUST complete before any manifest/values task (T004, T010) — the chart coordinates and pod selector label are otherwise unverified and the unit tests would pass against a manifest that cannot actually deploy.

- [X] T002 Verify the published Helm chart contract for `infrahub-mcp`: confirm the OCI coordinates (`oci://registry.opsmill.io/opsmill/chart/infrahub-mcp`) and chart `version` (assumed `0.1.0`, appVersion `v1.1.6`), and inspect the chart `templates/` to confirm the pod selector label (assumed `app.kubernetes.io/name: infrahub-mcp`) and the values key paths (`mcp.authMode`, `mcp.readOnly`, `mcp.logLevel`, `infrahub.address`). Record the confirmed values in `specs/015-infrahub-mcp-driver/research.md` (update R5/R6). If any differ from the assumptions, the corrected values are what T004/T010 MUST use.

**Checkpoint**: Real chart contract known — manifest authoring can begin.

---

## Phase 3: User Story 1 - Deploy an Infrahub MCP server in passthrough mode (Priority: P1) 🎯 MVP

**Goal**: An operator selects the `infrahub-mcp` Driver, supplies `infrahub_address`, and gets a managed MCP service (one `server` Component, one internal `infrahub-mcp` http Service on 8001) in fixed token-passthrough mode — no stored credential.

**Independent Test**: Deserialize the manifest → 1 `server` Component + 1 `infrahub-mcp` http/internal/8001 Service + `infrahub_address` required string param + `actions == []`; render `values.j2.yml` with only `infrahub_address` set → `fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`, `infrahub.address` mapped, and **no** `apiToken` key.

### Implementation for User Story 1

- [X] T003 [US1] Write `driver/examples/infrahub-mcp/driver.styrmin.yml` core: `apiVersion`/`kind`/`metadata.name: infrahub-mcp`, `spec.version: "1"`, `supported_versions: ">=1.1,<2.0"`, `info` block (description + Homepage/Documentation/Github links), `helm.main.location`/`version` (from T002), one `server` Component with the confirmed selector label, one `services` entry `infrahub-mcp` (kind http, scope internal, port 8001, component server), the `infrahub_address` parameter (kind string, **no default** ⇒ required), and **no `actions` block**. Model on `driver/examples/infrahub/` and `driver/examples/simple-app/`. (FR-001, FR-002, FR-003 partial, FR-005)
- [X] T004 [US1] Write `driver/examples/infrahub-mcp/values.j2.yml`: `fullnameOverride: styrmin-infrahub-mcp`, fixed `mcp.authMode: token-passthrough`, and `infrahub.address` mapped from `{{ parameters.infrahub_address }}`. No token/`apiToken` key anywhere. Use the confirmed key paths from T002. (FR-004, FR-006)

### Tests for User Story 1

- [X] T005 [US1] In `backend/tests/unit/services/driver/test_deserializer.py`, add a test that loads the real `driver/examples/infrahub-mcp/driver.styrmin.yml`, deserializes it via `DriverSpecDeserializer`, and asserts: `metadata.name == "infrahub-mcp"`, exactly one `server` Component with the confirmed selector label, exactly one Service (`infrahub-mcp`, http, internal, 8001, component=server), and `spec.actions == []`. (SC-001; contracts/driver-manifest.md)
- [X] T006 [US1] In `backend/tests/unit/services/driver/test_deserializer.py`, add a render test that renders `driver/examples/infrahub-mcp/values.j2.yml` (Jinja2) against a sample context with `parameters.infrahub_address` set, `yaml.safe_load`s the output, and asserts `fullnameOverride == "styrmin-infrahub-mcp"`, `mcp.authMode == "token-passthrough"`, `infrahub.address == <supplied>`, valid YAML, and **no `apiToken` key anywhere** in the rendered tree. (SC-002, SC-004; contracts/rendered-values.md)
- [X] T007 [US1] In `backend/tests/unit/services/test_parameters.py`, add tests for the infrahub-mcp parameter set asserting: supplying only `infrahub_address` resolves successfully with defaults applied; omitting `infrahub_address` raises `ServiceError` (missing required); an unknown parameter raises `ServiceError`. (FR-003, SC-003)

**Checkpoint**: MVP — the Driver deploys in passthrough mode with `infrahub_address` only, fully covered by unit tests.

---

## Phase 4: User Story 2 - Restrict the MCP server to read-only access (Priority: P2)

**Goal**: Operators can set `mcp_read_only` per deployment to expose query-only access.

**Independent Test**: Render with `mcp_read_only: true` → `mcp.readOnly: true`; omit it → `mcp.readOnly: false`.

### Implementation for User Story 2

- [X] T008 [US2] Add the `mcp_read_only` parameter (kind boolean, `default: false`) to `driver/examples/infrahub-mcp/driver.styrmin.yml`, and map it to `mcp.readOnly` in `driver/examples/infrahub-mcp/values.j2.yml`. (FR-003, FR-004) (depends on T003, T004)

### Tests for User Story 2

- [X] T009 [US2] Extend the deserialize test (T005) to assert the `mcp_read_only` param exists with `kind=boolean`, `default is False`; extend the render test (T006) to assert `mcp.readOnly is False` by default and `is True` when `mcp_read_only=True` is supplied; extend the parameter-validator test (T007) to assert a non-boolean `mcp_read_only` raises `ServiceError`. (User Story 2 acceptance) (depends on T008)

**Checkpoint**: US1 + US2 work; read-only is operator-controllable.

---

## Phase 5: User Story 3 - Tune the MCP server log level per deployment (Priority: P3)

**Goal**: Operators can set `mcp_log_level` (enum) per deployment; bad values are rejected before render.

**Independent Test**: Render with `mcp_log_level: debug` → `mcp.logLevel: debug`; supplying an out-of-enum value raises `ServiceError`.

### Implementation for User Story 3

- [X] T010 [US3] Add the `mcp_log_level` parameter (kind enum, `values: ["debug","info","warning","error"]`, `default: info`) to `driver/examples/infrahub-mcp/driver.styrmin.yml`, and map it to `mcp.logLevel` in `driver/examples/infrahub-mcp/values.j2.yml`. (FR-003, FR-004) (depends on T003, T004)

### Tests for User Story 3

- [X] T011 [US3] Extend the deserialize test (T005) to assert `mcp_log_level` has `kind=enum`, `values == ["debug","info","warning","error"]`, `default == "info"`; extend the render test (T006) to assert a supplied valid enum value flows to `mcp.logLevel`; extend the parameter-validator test (T007) to assert an out-of-enum `mcp_log_level` raises `ServiceError`. (User Story 3 acceptance) (depends on T010)

**Checkpoint**: All three parameters present, validated, and rendered.

---

## Phase 6: User Story 4 - Discover and catalogue the new Driver (Priority: P3)

**Goal**: The Driver loads/validates cleanly (no `actions.py`) and is discoverable in the docs.

**Independent Test**: `driver/DRIVERS.md` and `docs/docs/drivers/loading-drivers.md` both reference `infrahub-mcp`; the deserialize test confirms clean load with `actions == []`.

### Implementation for User Story 4

- [X] T012 [P] [US4] Add `infrahub-mcp` to the Examples list in `driver/DRIVERS.md` (the `## Examples` section, alongside `simple-app`, `infrahub`, `slurpit`, `semaphore`, `db-test`) with a one-line description. (FR-007)
- [X] T013 [P] [US4] Add `infrahub-mcp` to the example-driver list in `docs/docs/drivers/loading-drivers.md` ("Where to put your own drivers" / reference-repo list), including a one-line note that `infrahub_address` is accepted as a free-form string and is **not URL-validated** — connection failures surface at agent-query time, not deploy time (critique P1; spec Edge Cases). (FR-007)

### Tests for User Story 4

- [X] T014 [US4] Confirm the deserialize test (T005) asserts `spec.actions == []` (clean load with no `actions.py` required — FR-005). Add the assertion if not already present.

**Checkpoint**: Driver is catalogued and confirmed to load cleanly.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole feature against the quickstart and project gates.

- [ ] T015 Run `uv run invoke format lint` and fix any issues in the new/changed test code. (Constitution §VI)
- [ ] T016 Run the full unit suite for the touched modules: `uv run pytest backend/tests/unit/services/driver/test_deserializer.py backend/tests/unit/services/test_parameters.py -v` and confirm all infrahub-mcp tests pass. (quickstart steps 1–3)
- [ ] T017 Run `uv run invoke validate-graphql` is **not** required (no GraphQL change); instead run the quickstart's doc-reference check (`grep` for `infrahub-mcp` in `driver/DRIVERS.md` and `docs/docs/drivers/loading-drivers.md`) and confirm both surfaces reference the Driver. (quickstart step 5)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately.
- **Foundational (Phase 2 / T002)**: depends on Setup; **BLOCKS** all manifest/values authoring (T003, T004, T008, T010).
- **User Story 1 (Phase 3)**: depends on T002. Delivers the MVP.
- **User Stories 2–4 (Phases 4–6)**: depend on US1's manifest/template/test files (T003–T007). US2 and US3 edit the same two artifacts and the same test functions, so they run **sequentially** (T008→T009, then T010→T011). US4 docs tasks (T012, T013) are independent files and can run in parallel with each other and with US2/US3.
- **Polish (Phase 7)**: depends on all desired stories complete.

### Within Each User Story

- Manifest/template change before its test extension.
- Tests must be observed to pass (the unit suite is the definition of done — no E2E).

### Parallel Opportunities

- T012 and T013 (US4 docs) are `[P]` — different files, no code dependency.
- T002 must finish before any `[P]` authoring; there is otherwise little parallelism because the manifest and values template are single shared files.

---

## Parallel Example: User Story 4

```bash
# Docs tasks touch different files and can run together:
Task: "Add infrahub-mcp to driver/DRIVERS.md Examples list"
Task: "Add infrahub-mcp to docs/docs/drivers/loading-drivers.md with the URL-not-validated note"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup (T001).
2. Phase 2 Foundational (T002 — verify chart contract). **Do not skip.**
3. Phase 3 US1 (T003–T007).
4. **STOP and VALIDATE**: run the US1 deserialize/render/validator tests green.

### Incremental Delivery

1. Setup + Foundational → contract pinned.
2. US1 → MVP (deploy in passthrough, tests green).
3. US2 → read-only knob.
4. US3 → log-level knob.
5. US4 → catalogue + clean-load confirmation.
6. Polish → format/lint + full suite + doc-reference check.

---

## Notes

- **No E2E task** — owner-approved deviation from Constitution §V; the unit deserialize + parameter-validator + Jinja2 render tests are the agreed substitute (spec Assumptions/Out of Scope, plan Complexity Tracking).
- No GraphQL/DB/SDK/CLI/frontend tasks — none of those surfaces change; no propagation test required.
- T002 is the single most important risk-reducer: it converts the PRD Open Question into confirmed facts before the manifest is finalized.
- Commit after each phase (or logical task group).
