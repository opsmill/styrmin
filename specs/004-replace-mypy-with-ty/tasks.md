# Tasks: Replace mypy with ty and Increase Type Checking Coverage

**Input**: Design documents from `/specs/004-replace-mypy-with-ty/`
**Prerequisites**: plan.md (required), spec.md (required), research.md

**Tests**: No new test tasks — this is a tooling refactor. Verification is done via `uv run ty check` and `uv run invoke lint`.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: Ensure clean starting state

- [ ] T001 Verify current `uv run ty check` passes on develop branch baseline
- [ ] T002 Verify current `uv run invoke lint` passes on develop branch baseline

---

## Phase 2: Foundational (Remove mypy)

**Purpose**: Remove mypy entirely from the project — MUST complete before ty rule enablement

**⚠️ CRITICAL**: No ty rule work (US2) can begin until mypy is fully removed

- [ ] T003 Remove `mypy>=1.19.1` from dev dependencies in `pyproject.toml`
- [ ] T004 [P] Remove `types-jsonschema>=4.23.0.20241208` from dev dependencies in `pyproject.toml`
- [ ] T005 [P] Remove `types-pyyaml>=6.0.12.20241230` from dev dependencies in `pyproject.toml`
- [ ] T006 [P] Remove `types-requests>=2.32.0.20250306` from dev dependencies in `pyproject.toml`
- [ ] T007 [P] Remove `types-toml>=0.10.8.20240310` from dev dependencies in `pyproject.toml`
- [ ] T008 Remove `[tool.mypy]` section (lines 120-124) and all `[[tool.mypy.overrides]]` sections (lines 125-148) from `pyproject.toml`
- [ ] T009 Remove `lint_mypy` function and its `ns.add_task(lint_mypy)` call from `tasks/format.py`
- [ ] T010 Add `ns.add_task(lint_ty)` to the task collection in `tasks/format.py`
- [ ] T011 Remove `fmt.lint_mypy(context)` call from `lint_all` function in `tasks/__init__.py`
- [ ] T012 Remove the `uv run mypy backend` CI step from `.github/workflows/ci.yml`
- [ ] T013 Run `uv sync --all-groups` to verify dependency resolution succeeds without mypy
- [ ] T014 Run `uv run ty check` to verify type checking still passes

**Checkpoint**: mypy is fully removed. Type checking is ty-only.

---

## Phase 3: User Story 1 - Enable unused-type-ignore-comment and Clean Up Orphaned Comments (Priority: P1) 🎯 MVP

**Goal**: Enable the `unused-type-ignore-comment` ty rule and remove all orphaned `# type: ignore` comments that were only needed by mypy.

**Independent Test**: Run `uv run ty check` — it must pass with the `unused-type-ignore-comment` rule enabled and no orphaned comments.

### Implementation for User Story 1

- [ ] T015 [US1] Remove `unused-type-ignore-comment = "ignore"` from the `tasks/**` ty override in `pyproject.toml`
- [ ] T016 [P] [US1] Remove `unused-type-ignore-comment = "ignore"` from the `backend/**` ty override in `pyproject.toml`
- [ ] T017 [P] [US1] Remove `unused-type-ignore-comment = "ignore"` from the `driver/**` ty override in `pyproject.toml`
- [ ] T018 [P] [US1] Remove `unused-type-ignore-comment = "ignore"` from the `python_sdk/**` ty override in `pyproject.toml`
- [ ] T019 [US1] Run `uv run ty check 2>&1` to identify all orphaned `# type: ignore` comments flagged by `unused-type-ignore-comment`
- [ ] T020 [US1] Remove orphaned `# type: ignore` comments in `backend/` files identified by ty
- [ ] T021 [P] [US1] Remove orphaned `# type: ignore` comments in `python_sdk/` files identified by ty
- [ ] T022 [P] [US1] Remove orphaned `# type: ignore` comments in `tasks/` files identified by ty
- [ ] T023 [P] [US1] Remove orphaned `# type: ignore` comments in `driver/` files identified by ty
- [ ] T024 [US1] Run `uv run ty check` to verify it passes cleanly with `unused-type-ignore-comment` enabled
- [ ] T025 [US1] Run `uv run invoke lint` to verify full lint pipeline passes

**Checkpoint**: `unused-type-ignore-comment` is enabled, orphaned comments are removed. This is the MVP — type checking is consolidated on ty.

---

## Phase 4: User Story 2 - Increase ty Rule Coverage (Priority: P2)

**Goal**: Audit and enable suppressed ty rules, reducing suppressions by at least 50% (from ~21 remaining after Phase 3 to <=10).

**Independent Test**: Run `uv run ty check` after each rule enablement — must pass. Count remaining suppressed rules in `pyproject.toml` — must be <=10.

### Implementation for User Story 2

#### Audit: cli/ module (1 rule)

- [ ] T026 [US2] Enable `unresolved-attribute` for `cli/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker

#### Audit: driver/ module (1 remaining rule after Phase 3)

- [ ] T027 [P] [US2] Enable `unresolved-import` for `driver/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker

#### Audit: tasks/ module (2 remaining rules after Phase 3)

- [ ] T028 [P] [US2] Enable `invalid-argument-type` for `tasks/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T029 [P] [US2] Enable `unresolved-attribute` for `tasks/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker

#### Audit: python_sdk/ module (3 remaining rules after Phase 3)

- [ ] T030 [US2] Enable `invalid-argument-type` for `python_sdk/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T031 [P] [US2] Enable `invalid-assignment` for `python_sdk/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T032 [P] [US2] Enable `invalid-type-form` for `python_sdk/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker

#### Audit: backend/ module (14 remaining rules after Phase 3)

- [ ] T033 [US2] Enable `invalid-newtype` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T034 [P] [US2] Enable `not-subscriptable` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T035 [P] [US2] Enable `unsupported-operator` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T036 [P] [US2] Enable `unknown-argument` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T037 [P] [US2] Enable `missing-argument` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T038 [US2] Enable `no-matching-overload` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T039 [US2] Enable `invalid-await` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T040 [US2] Enable `invalid-type-arguments` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T041 [US2] Enable `invalid-type-form` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T042 [US2] Enable `invalid-method-override` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T043 [US2] Enable `invalid-return-type` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T044 [US2] Enable `invalid-assignment` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T045 [US2] Enable `invalid-argument-type` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker
- [ ] T046 [US2] Enable `unresolved-attribute` for `backend/**` by removing from ty overrides in `pyproject.toml`, run `uv run ty check`, fix violations or document as upstream blocker

- [ ] T047 [US2] Verify remaining suppressed rules count is <=10 (50%+ reduction from 21)
- [ ] T048 [US2] Run `uv run ty check` to verify all changes pass cleanly
- [ ] T049 [US2] Run `uv run invoke lint` to verify full lint pipeline passes

**Checkpoint**: ty rule coverage increased by at least 50%. All remaining suppressions are documented.

---

## Phase 5: User Story 3 - Documentation Updates (Priority: P3)

**Goal**: Update project documentation to reflect ty as the sole type checker.

**Independent Test**: Search all documentation files for "mypy" — only historical references (ADRs) should remain.

### Implementation for User Story 3

- [ ] T050 [US3] Update linting line in `AGENTS.md` from "ruff, mypy (backend)" to "ruff, ty"
- [ ] T051 [P] [US3] Update Principle IV in `.specify/memory/constitution.md` to reference ty instead of mypy
- [ ] T052 [P] [US3] Search `dev/` directory for any mypy references in guides or documentation and update them

**Checkpoint**: All documentation reflects ty as the sole type checker.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification and cleanup

- [ ] T053 Run `uv run invoke format` to format all modified Python files
- [ ] T054 Run `uv run invoke lint` for final full lint pass
- [ ] T055 Run `uv run invoke test` to verify no tests are broken
- [ ] T056 Verify `uv run ty check` passes cleanly on the entire project

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — verify baseline
- **Foundational (Phase 2)**: Depends on Phase 1 — remove mypy entirely
- **User Story 1 (Phase 3)**: Depends on Phase 2 — enable unused-type-ignore-comment
- **User Story 2 (Phase 4)**: Depends on Phase 3 — audit and enable ty rules
- **User Story 3 (Phase 5)**: Can run in parallel with Phase 4 (independent documentation)
- **Polish (Phase 6)**: Depends on all previous phases

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Phase 2 (mypy removal) — orphaned comments can only be identified after mypy is gone
- **User Story 2 (P2)**: Depends on US1 — rule audit requires `unused-type-ignore-comment` to be resolved first
- **User Story 3 (P3)**: Independent — can run after Phase 2, in parallel with US2

### Within Each User Story

- Config changes before running ty check
- ty check to identify violations
- Fix violations before next config change
- Full lint pass at end of each story

### Parallel Opportunities

- T004-T007 (remove stub packages) can run in parallel
- T015-T018 (remove unused-type-ignore-comment suppressions) can run in parallel
- T020-T023 (remove orphaned comments per directory) can run in parallel
- T026-T029 (audit cli/driver/tasks rules) can run in parallel
- T050-T052 (documentation updates) can run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (verify baseline)
2. Complete Phase 2: Foundational (remove mypy)
3. Complete Phase 3: User Story 1 (enable unused-type-ignore-comment, clean orphaned comments)
4. **STOP and VALIDATE**: `uv run ty check` passes, `uv run invoke lint` passes
5. This alone delivers the core value: single type checker, clean codebase

### Incremental Delivery

1. Complete Setup + Foundational → mypy removed
2. Add User Story 1 → orphaned comments cleaned → Deploy/Demo (MVP!)
3. Add User Story 2 → ty rules enabled → stronger type checking
4. Add User Story 3 → documentation updated → clean developer experience
5. Polish → final verification

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each rule audit (Phase 4) follows the same pattern: enable → check → fix or document
- If a rule has too many violations to fix, re-suppress with a documentation comment explaining the upstream issue
- Commit after each logical group of tasks (per-phase or per-rule-audit)
