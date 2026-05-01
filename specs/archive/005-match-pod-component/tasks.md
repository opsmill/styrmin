---
description: "Task list for matching pod statuses to driver components"
---

# Tasks: Match Pod Statuses to Driver Components

**Input**: Design documents from `/specs/005-match-pod-component/`
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Yes — required by Constitution §V (E2E coverage is part of done) and explicitly called out in spec.md FR-007.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared state)
- **[Story]**: US1 = component attribution; US2 = absent-label handling. Both ride the same code path; the user-story split exists for traceability of test scenarios, not for parallel implementation.

---

## Phase 1: Setup

No new tooling, dependencies, or scaffolding needed — this is a pure additive change to existing modules. Skipping.

---

## Phase 2: Foundational (Schema + Migration)

**Purpose**: Land the new column on the DB and the new field on the SQLModel before anything else touches it. The agent and service layers depend on the model accepting the field.

- [ ] **T001** Add `component_name: str | None = Field(default=None, nullable=True)` to `PodStatus` in `backend/styrmin_backend/db/models.py` (the row defined at line ~422). Place it next to `node_name`.
- [ ] **T002** Generate an Alembic migration: `uv run alembic revision -m "add component_name to pod_status"`. Edit the generated file in `backend/styrmin_backend/db/migrations/versions/` so `upgrade()` adds the nullable `component_name` column and `downgrade()` drops it. Verify `down_revision` chains from the latest existing revision (`alembic history` to confirm).
- [ ] **T003** Run `uv run alembic upgrade head` against a local dev DB and confirm the column exists (`\d podstatus`).

**Checkpoint**: DB and SQLModel accept the new field. Nothing else uses it yet.

---

## Phase 3: User Story 1 — Component Attribution (Priority: P1) 🎯 MVP

**Goal**: Pods produced from a declared component carry their component name through to the API.

**Independent Test**: Deploy a multi-component driver, query `deployment.podStatuses { componentName }`, see `componentName` matching the component that owns each pod.

### Tests (write first, expect them to fail)

- [ ] **T004** [P] [US1] Add unit test `test_extract_pod_data_reads_component_label` in `backend/tests/unit/agent/test_status_reporter.py`: build a fake pod with `metadata.labels = {"styrmin/component": "api"}`, call `_extract_pod_data`, assert `result.component_name == "api"`. Update the existing `_make_pod` helper to accept a `labels` kwarg defaulting to `None` so existing tests don't break.
- [ ] **T005** [P] [US1] Add unit test `test_pod_status_data_serializes_component_name` in the same file: construct `PodStatusData(componentName="api", ...)` and assert `model_dump(by_alias=True)["componentName"] == "api"`.
- [ ] **T006** [P] [US1] Add unit test `test_report_pod_statuses_persists_component_name` in `backend/tests/unit/services/test_pod_status_service.py`: send a report with `component_name="api"`, assert the persisted `PodStatus` model has `component_name == "api"` after upsert.

### Implementation

- [ ] **T007** [US1] Add `component_name: str | None = Field(default=None, alias="componentName")` to `PodStatusData` in `backend/styrmin_backend/agent/status/models.py`.
- [ ] **T008** [US1] In `backend/styrmin_backend/agent/status/reporter.py`, define a module-level constant `_COMPONENT_LABEL_KEY = "styrmin/component"` (above `_extract_pod_data`) and update `_extract_pod_data(pod)` to read the label from `pod.metadata.labels` and pass it as `componentName` to `PodStatusData`. Normalize empty/whitespace values to `None` before constructing the model.
- [ ] **T009** [US1] Update `PodStatus` and `PodStatusInput` in `backend/styrmin_backend/api/definitions/pod_status/model.py` to include `component_name: str | None = None`. Update `PodStatus.from_instance()` to pass `component_name=instance.component_name`.
- [ ] **T010** [US1] Update `report_pod_statuses` in `backend/styrmin_backend/services/pod_status.py` to forward `component_name` from the input dict to the `PodStatus` constructor (same pattern as `node_name`).
- [ ] **T011** [US1] Regenerate the GraphQL schema: `uv run styrmin export graphql-schema schema.graphql`. Verify the diff matches `specs/005-match-pod-component/contracts/graphql-schema.md`.
- [ ] **T012** [US1] Add `componentName` to the selection set in `python_sdk/src/styrmin_sdk/graphql/get_pod_statuses.graphql` and `python_sdk/src/styrmin_sdk/graphql/get_deployment_pod_statuses.graphql`.
- [ ] **T013** [US1] Run `uv run invoke validate-graphql` then `uv run invoke generate` to refresh SDK Pydantic types.

**Checkpoint**: Unit tests pass; the field is plumbed end-to-end.

---

## Phase 4: User Story 2 — Absent / Unknown Label Handling (Priority: P1)

**Goal**: A pod without the label, with a blank label, or with a label whose value isn't a declared component is still reported truthfully (no drops, no fabrication, no rejection).

**Independent Test**: Add an unlabelled pod to a deployment's namespace; query the deployment's pod statuses; the unlabelled pod is present with `componentName: null`.

### Tests

- [ ] **T014** [P] [US2] Add unit test `test_extract_pod_data_returns_none_when_label_missing` in `backend/tests/unit/agent/test_status_reporter.py`: pod with `metadata.labels = None`, `metadata.labels = {}`, and `metadata.labels = {"other": "thing"}` (no `styrmin/component` key) — all three must produce `result.component_name is None`.
- [ ] **T015** [P] [US2] Add unit test `test_extract_pod_data_normalizes_blank_label_to_none` in the same file: pod with `metadata.labels = {"styrmin/component": ""}` and `metadata.labels = {"styrmin/component": "   "}` — both must produce `result.component_name is None`.
- [ ] **T016** [P] [US2] Add unit test `test_extract_pod_data_passes_through_unknown_label_value` in the same file: pod with `metadata.labels = {"styrmin/component": "ghost"}` produces `result.component_name == "ghost"`. (Asserts no agent-side coercion against declared components.)
- [ ] **T017** [P] [US2] Add unit test `test_report_pod_statuses_persists_unknown_component_name` in `backend/tests/unit/services/test_pod_status_service.py`: send a report with `component_name="ghost"` for a deployment whose driver doesn't declare a `ghost` component; assert the row is persisted with `component_name == "ghost"` (no rejection, no coercion).

### Implementation

No additional implementation — the normalization in T008 and the absence of validation in T010 satisfy this story. Tests are the deliverable.

**Checkpoint**: All four scenarios from spec.md FR-002, FR-004, and Edge Cases are covered by passing unit tests.

---

## Phase 5: E2E Test (Constitution §V Gate)

**Goal**: A real cluster, a real multi-component driver, the agent's actual reporter writing the actual rows, the actual GraphQL API serving the actual field. This is what the constitution requires.

- [ ] **T018** Create `backend/tests/e2e/test_pod_component_attribution.py`. Use the `infrahub` driver (declares `server`, `task-worker`, `database`, `cache` — see `driver/examples/infrahub/driver.styrmin.yml`) deployed via the existing `scenario_driver` / `vcluster` fixtures (mirror the structure of `test_deploy_app.py`). Steps:
    1. Deploy the driver, wait for `RUNNING`.
    2. Poll `client.get_deployment_pod_statuses(deployment_id=...)` until at least one pod for each component is reported and `Ready=True` (use the existing wait helpers; bound at ~120s).
    3. Assert each returned pod's `component_name` matches the component name encoded in its pod-name prefix (or in the pod's actual label fetched via kr8s — the latter is more robust).
    4. `kubectl run` an unlabelled `busybox` pod into the deployment's namespace, wait one poll cycle (~10s), re-query, assert the busybox pod is present with `component_name is None`.
    5. Cleanup: delete the busybox pod.
- [ ] **T019** Run the new E2E test with `uv run pytest backend/tests/e2e/test_pod_component_attribution.py -v -s --pdb` per AGENTS.md. Iterate until it passes. (When invoked from a non-interactive shell, prefix with `sleep infinity |`.) `--pdb` keeps the cluster alive on failure for live debugging.

**Checkpoint**: E2E passes against a real Kind cluster. Definition of done satisfied.

---

## Phase 6: Polish & Verification

- [ ] **T020** Run `uv run invoke format lint` — must pass with zero issues. Constitution §VI is non-negotiable.
- [ ] **T021** Run the full unit test suite: `uv run invoke test` — must pass.
- [ ] **T022** Walk through `specs/005-match-pod-component/quickstart.md` against a fresh dev environment. Update the quickstart in place if anything is wrong; do not silently work around it.
- [ ] **T023** [P] Update the spec → ADR pipeline expectation: nothing here is ADR-worthy on its own (no architectural reversal), but the **decision not to validate against declared components** is exactly the kind of judgement future-us should be able to find. Capture it in `dev/adr/` during phase 6 (`/speckit.extract`) — do not pre-create it here.

---

## Dependencies & Execution Order

### Phase order

- **Phase 2 (foundational)** before **Phase 3** before **Phase 4** before **Phase 5** before **Phase 6**.
- Within Phase 3, T011/T012/T013 (schema/SDK regen) must run **after** T007–T010 (model + service edits). Otherwise schema regen produces stale output.
- Within Phase 5, T019 depends on T018.

### Parallelizable

- T004, T005, T006 — different test functions, can be authored in any order. ⚠ Do not run pytest until T007–T010 are in; they will fail.
- T014, T015, T016, T017 — same as above.
- T007 (agent model) and T009 (API model) and T010 (service) can be edited in parallel — different files, no inter-dependency at write-time. T008 depends on T007 (uses the new field on `PodStatusData`).

### Sequential (one shell, one editor)

- T002 → T003 (revision created → migration applied)
- T011 → T012 → T013 (schema → query files → SDK regen)
- T020 → T021 (format + lint before running tests so test failures aren't lint-noise)

---

## Implementation Strategy

This is a small additive feature. The right shape is:

1. **Foundation (Phase 2)**: land the column and SQLModel field. Migrate locally. ~10 min.
2. **Plumb the field (Phase 3)**: agent → API → service → DB. Tests for the happy path. Regenerate schema and SDK. ~30 min.
3. **Cover the unhappy paths (Phase 4)**: absent label, blank label, unknown label. Pure test-writing on already-implemented code. ~15 min.
4. **E2E (Phase 5)**: this is the real bar. Multi-component driver, real reporter cycle, real query. ~45–90 min including iteration.
5. **Polish (Phase 6)**: lint, full test run, walk the quickstart. ~10 min.

If the E2E phase takes more than ~2 hours of debugging, **stop and ask** — that's a signal something deeper is mis-wired (label not actually appearing on pods, schema regen broken, etc.) and burning more time without diagnosis is the wrong move.

---

## Notes

- The constitution-required E2E test is **T018/T019**, not the unit tests. Unit tests are necessary but not sufficient.
- The `styrmin/component` label string appears in multiple places already (`services/scheduling/validator.py:27`, `velero/hooks.py`). Resist consolidating into a shared constant in this PR — it's a separate cleanup with different stakeholders. Define `_COMPONENT_LABEL_KEY` locally in `reporter.py` and move on.
- No frontend work in this spec. The frontend is a downstream consumer; per-component UI is a separate piece of work.
- `report_pod_statuses.graphql` does **not** need editing — its response selection set doesn't include pod fields.
