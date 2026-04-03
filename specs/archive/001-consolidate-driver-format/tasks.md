# Tasks: Consolidate Driver Format

**Input**: Design documents from `/specs/001-consolidate-driver-format/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests are included — the spec requires updating existing tests and adding new error case tests.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: Create error types and prepare the foundation for model changes

- [x] T001 Add `DeprecatedDriverFormatError` and `AmbiguousDriverFormatError` to `backend/styrmin_backend/services/driver/errors.py` (create file if it does not exist; import from existing exception patterns in `backend/styrmin_backend/services/exceptions.py`)

---

## Phase 2: Foundational (Pydantic Model & Config Changes)

**Purpose**: Update all Pydantic models, enums, config, and type aliases. These are blocking prerequisites — every downstream loader/validator/test change depends on the model shape.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T002 [P] Add optional `actions: list[ActionDefinition] = []` field to `Specification` model in `backend/styrmin_backend/services/driver/models/resources/driver.py` (import `ActionDefinition` from the existing `actions.py` module)
- [x] T003 [P] Remove the `ActionsSpec` envelope model (`ActionsSpec`, its inner `Metadata`, `Spec` classes) from `backend/styrmin_backend/services/driver/models/resources/actions.py` — keep `ActionDefinition`, `HookKind`, `ParameterKind`, `Parameter` intact
- [x] T004 [P] Remove `ACTIONS_SPEC` value from `Role` enum in `backend/styrmin_backend/services/driver/models/structure/resource.py`
- [x] T005 [P] Update `DriverResource` type alias in `backend/styrmin_backend/services/driver/models/resources/__init__.py` — remove `ActionsSpec` from the union
- [x] T006 Update `DriverSettings` in `backend/styrmin_backend/config.py`: change `spec_file` default to `"driver.styrmin.yml"`, rename `chart_values_template` to `values_template` with default `"values.j2.yml"`, remove `actions_spec_file` field, keep `actions_code_file`
- [x] T007 Remove `actions_spec` field from `ApplicationDriver` dataclass in `backend/styrmin_backend/services/driver/__init__.py`
- [x] T008 Update `DriverDirectory` in `backend/styrmin_backend/services/driver/models/structure/directory.py`: remove `actions_spec` resource file, update `driver_spec` path to use new config default, update `values_template` path to use renamed config field and make it optional

**Checkpoint**: All models, config, and type aliases reflect the new 3-file format. Code will not compile/pass mypy yet — downstream consumers updated in US1.

---

## Phase 3: User Story 1 — Single-File Driver Authoring (Priority: P1) MVP

**Goal**: The loader pipeline reads all declarative configuration (driver spec + actions) from a single `driver.styrmin.yml` file and correctly builds an `ApplicationDriver`.

**Independent Test**: Load a driver directory containing only `driver.styrmin.yml` (with actions), `values.j2.yml`, and `actions.py` — verify all configuration is parsed correctly.

### Implementation for User Story 1

- [x] T009 [US1] Update `load_driver()` in `backend/styrmin_backend/services/driver/loaders.py`: remove `actions_spec` loading step, remove `actions_spec` from `ApplicationDriver` construction, add post-deserialization validation (if `driver_spec.spec.actions` is non-empty, load and validate `actions.py` using `UserActionsValidator`)
- [x] T010 [US1] Remove `ActionsSpecDeserializer` and update `get_deserializer()` factory to remove `ACTIONS_SPEC` case in `backend/styrmin_backend/services/driver/deserializers.py`
- [x] T011 [US1] Update `get_validator()` factory in `backend/styrmin_backend/services/driver/validators.py`: remove `ACTIONS_SPEC` case, update `build_user_actions_validator()` to accept `list[ActionDefinition]` instead of `ActionsSpec`
- [x] T012 [US1] Update `validate_driver_backup_configs()` in `backend/styrmin_backend/services/driver/validators.py`: change `actions_spec: ActionsSpec | None` parameter to accept `list[ActionDefinition]` (or equivalent) and update the hook extraction logic
- [x] T013 [US1] Update all consumers of `driver_object.actions_spec` in `backend/styrmin_backend/services/applications.py`: change `driver_object.actions_spec.spec.actions` to `driver_object.driver_spec.spec.actions` (two locations: workflow builder loop ~line 139 and action creation loop ~line 220)
- [x] T014 [US1] Add old-format detection logic to the loader in `backend/styrmin_backend/services/driver/loaders.py`: after failing to find `driver.styrmin.yml`, check for old filenames (`styrmin_driver.yaml`, `actions.yaml`, `chart_values.j2.yaml`) and raise `DeprecatedDriverFormatError`; if both old and new exist, raise `AmbiguousDriverFormatError`
- [x] T015 [US1] Update test fixtures in `backend/tests/unit/services/driver/fixtures/local_driver_directory/`: rename `styrmin_driver.yaml` to `driver.styrmin.yml` (merging in `actions.yaml` content), rename `chart_values.j2.yaml` to `values.j2.yml`, delete `actions.yaml`
- [x] T016 [US1] Update `test_loaders.py` in `backend/tests/unit/services/driver/test_loaders.py`: adjust tests for 3-file loading, add tests for deprecated format error and ambiguous format error
- [x] T017 [US1] Update `test_deserializer.py` in `backend/tests/unit/services/driver/test_deserializer.py`: remove `ActionsSpecDeserializer` tests, add test for `DriverSpec` with embedded actions, update deserializer factory tests
- [x] T018 [US1] Update `test_validators.py` in `backend/tests/unit/services/driver/test_validators.py`: update `UserActionsValidator` tests, update backup config validator tests to use new `actions_spec` parameter type
- [x] T019 [US1] Update `test_driver_config.py` in `backend/tests/unit/services/backup/test_driver_config.py`: update `_make_actions_spec_with_hooks` helper and `validate_driver_backup_configs` calls to match new parameter signature
- [x] T020 [US1] Update any remaining test files that construct `ApplicationDriver` with `actions_spec` field: `backend/tests/unit/services/fakes.py`, `backend/tests/unit/services/test_application_services.py`, and `backend/tests/unit/services/conftest.py`
- [x] T021 [US1] Run `uv run invoke format lint` and fix any issues
- [x] T022 [US1] Run `uv run invoke test` and verify all tests pass

**Checkpoint**: The loader pipeline works with the new consolidated format. All unit tests pass. This is the MVP — a driver with `driver.styrmin.yml` + `values.j2.yml` + `actions.py` loads correctly.

---

## Phase 4: User Story 2 — Renamed Values Template (Priority: P1)

**Goal**: The system loads the Helm values template from `values.j2.yml` instead of `chart_values.j2.yaml`.

**Independent Test**: Load a driver with `values.j2.yml` — verify the template is correctly processed. Load a driver with both old and new values filenames — verify error.

**Note**: Most of this work is already covered by T006/T008/T015 in Phase 2-3. This phase captures any remaining validation and edge case testing.

### Implementation for User Story 2

- [x] T023 [US2] Verify that `values_template` config change (T006) and directory model change (T008) correctly resolve `values.j2.yml` — add a specific test case in `backend/tests/unit/services/driver/test_loaders.py` for loading a driver with `values.j2.yml`
- [x] T024 [US2] Add test case for ambiguous values template: driver directory contains both `chart_values.j2.yaml` and `values.j2.yml` — should raise `AmbiguousDriverFormatError` (in `backend/tests/unit/services/driver/test_loaders.py`)

**Checkpoint**: Values template loading works with the new filename. Edge cases tested.

---

## Phase 5: User Story 3 — Example Driver Migration (Priority: P2)

**Goal**: All 5 example drivers use the new consolidated format and load without errors.

**Independent Test**: For each example driver, verify the directory contains only new filenames and the system can load it.

### Implementation for User Story 3

- [x] T025 [P] [US3] Migrate `driver/examples/simple-app/`: merge `styrmin_driver.yaml` + `actions.yaml` into `driver.styrmin.yml`, rename `chart_values.j2.yaml` to `values.j2.yml`, delete old files
- [x] T026 [P] [US3] Migrate `driver/examples/infrahub/`: merge `styrmin_driver.yaml` + `actions.yaml` into `driver.styrmin.yml`, rename `chart_values.j2.yaml` to `values.j2.yml`, delete old files
- [x] T027 [P] [US3] Migrate `driver/examples/slurpit/`: merge `styrmin_driver.yaml` + `actions.yaml` into `driver.styrmin.yml`, rename `chart_values.j2.yaml` to `values.j2.yml`, delete old files
- [x] T028 [P] [US3] Migrate `driver/examples/semaphore/`: merge `styrmin_driver.yaml` + `actions.yaml` into `driver.styrmin.yml`, rename `chart_values.j2.yaml` to `values.j2.yml`, delete old files
- [x] T029 [P] [US3] Migrate `driver/examples/db-test/`: merge `styrmin_driver.yaml` + `actions.yaml` into `driver.styrmin.yml`, rename `chart_values.j2.yaml` to `values.j2.yml`, delete old files

**Checkpoint**: All example drivers use the new format. No old filenames remain in `driver/examples/`.

---

## Phase 6: User Story 4 — Updated Documentation (Priority: P2)

**Goal**: Driver documentation reflects the new file structure, naming conventions, and consolidated actions format.

**Independent Test**: Review `driver/DRIVERS.md` — all file references, directory structures, and examples use new filenames.

### Implementation for User Story 4

- [x] T030 [US4] Update `driver/DRIVERS.md`: update file structure table, update driver specification section to show `driver.styrmin.yml` schema with embedded actions, update values template section to reference `values.j2.yml`, update action definition section to show actions as part of `driver.styrmin.yml`, update loading section, update examples section

**Checkpoint**: Documentation is consistent with the new format.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup across all user stories

- [x] T031 [P] Run `uv run invoke format lint` across entire codebase and fix any issues
- [x] T032 Run `uv run invoke test` — verify all tests pass with no regressions
- [x] T033 Grep the entire codebase for references to old filenames (`styrmin_driver.yaml`, `chart_values.j2.yaml`, `actions.yaml` as a driver file, `actions_spec_file`, `chart_values_template` as a config key) and update any remaining references
- [x] T034 Verify no `ActionsSpec` imports remain in any file outside of the preserved `ActionDefinition` models

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — this is the MVP
- **US2 (Phase 4)**: Depends on Phase 3 (values template changes overlap with loader changes)
- **US3 (Phase 5)**: Depends on Phase 3 (need working loader to validate migrated examples)
- **US4 (Phase 6)**: Can start after Phase 3 (documentation can be written once format is finalized)
- **Polish (Phase 7)**: Depends on all previous phases

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational only — core MVP
- **User Story 2 (P1)**: Largely covered by US1 changes; Phase 4 adds edge case tests
- **User Story 3 (P2)**: Depends on US1 (needs working loader); all 5 migrations can run in parallel
- **User Story 4 (P2)**: Independent of US2/US3; can start once format is finalized in US1

### Within Each User Story

- Models/config before loader changes
- Loader changes before test updates
- Tests before lint/format validation

### Parallel Opportunities

- T002, T003, T004, T005 can all run in parallel (different files, no dependencies)
- T025, T026, T027, T028, T029 can all run in parallel (different example directories)
- T031 and T033 can run in parallel (different concerns)

---

## Parallel Example: Phase 2 (Foundational)

```bash
# Launch all model changes in parallel:
Task T002: "Add actions field to Specification in backend/styrmin_backend/services/driver/models/resources/driver.py"
Task T003: "Remove ActionsSpec envelope from backend/styrmin_backend/services/driver/models/resources/actions.py"
Task T004: "Remove ACTIONS_SPEC from Role enum in backend/styrmin_backend/services/driver/models/structure/resource.py"
Task T005: "Update DriverResource type alias in backend/styrmin_backend/services/driver/models/resources/__init__.py"
```

## Parallel Example: Phase 5 (Example Migration)

```bash
# Launch all example driver migrations in parallel:
Task T025: "Migrate driver/examples/simple-app/"
Task T026: "Migrate driver/examples/infrahub/"
Task T027: "Migrate driver/examples/slurpit/"
Task T028: "Migrate driver/examples/semaphore/"
Task T029: "Migrate driver/examples/db-test/"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002-T008)
3. Complete Phase 3: User Story 1 (T009-T022)
4. **STOP and VALIDATE**: Run full test suite, verify loader works with new format
5. This is a deployable increment — the system works with the new driver format

### Incremental Delivery

1. Setup + Foundational → Model layer ready
2. User Story 1 → Loader works with new format → MVP
3. User Story 2 → Edge cases for values template covered
4. User Story 3 → All examples migrated → Complete format migration
5. User Story 4 → Documentation updated → Feature complete
6. Polish → Final validation → Ready for merge

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- The `ActionsSpec` removal (T003) preserves `ActionDefinition` and related models — only the envelope is removed
- `applications.py` (T013) is a critical consumer that accesses `actions_spec.spec.actions` — must be updated to `driver_spec.spec.actions`
- The backup validator (T012, T019) uses `ActionsSpec` to extract action hook names — parameter signature must change
- Total: 34 tasks across 7 phases
