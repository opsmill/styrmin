---

description: "Task list for Python SDK AGENTS.md"
---

# Tasks: Python SDK AGENTS.md

**Input**: Design documents from `/specs/001-sdk-agents-md/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/agents-md-outline.md, quickstart.md

**Tests**: Not applicable. This is a documentation-only feature; the spec
explicitly invokes the Constitution §V exemption for docs-only changes.
Verification is by review against `quickstart.md`'s mechanical and review
checklists.

**Organization**: Tasks are grouped by user story so each story can be
delivered as an independent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- File paths are absolute or repo-root-relative.

## Path Conventions

- New file: `python_sdk/AGENTS.md`
- Modified file: `AGENTS.md` (repo root)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the working environment and design artifacts are in place.

- [X] T001 Verify the feature branch is `001-sdk-agents-md` and the spec directory `specs/001-sdk-agents-md/` exists with `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/agents-md-outline.md`, and `quickstart.md` present
- [X] T002 Confirm the SDK source layout matches what `data-model.md` and `contracts/agents-md-outline.md` describe by listing `python_sdk/src/styrmin_sdk/` and `python_sdk/src/styrmin_sdk/resources/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. Both user-story phases can begin as soon as Setup is done; there is no shared infrastructure to build for a docs-only change.

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — SDK orientation document exists (Priority: P1) 🎯 MVP

**Goal**: A new `python_sdk/AGENTS.md` describes the SDK's architecture (transport, client, resources, generated models, `.graphql` operations + `load_query()`), plus the worked example required by FR-009. The top-level `AGENTS.md` references it from both **File Structure** and **Component Maps**.

**Independent Test**: Following `quickstart.md`'s mechanical checks 1, 2, and 6 plus US1 review checklist items passes.

### Implementation for User Story 1

- [X] T003 [US1] Create `python_sdk/AGENTS.md` with the title, one-line description, **Tech Stack**, **File Structure** (table covering `client.py`, `_transport.py`, `_queries.py`, `exceptions.py`, `resources/`, `resources/_base.py`, `graphql/*.graphql`, `graphql/_generated/`, `tests/`), and **Commands** sections from `contracts/agents-md-outline.md`. Use module roles from `research.md` R3.
- [X] T004 [US1] Append the **Worked example** section to `python_sdk/AGENTS.md`, copying the `ClusterResource.get` snippet from `python_sdk/src/styrmin_sdk/resources/clusters.py` and a one-paragraph explanation of how `load_query()` and the generated Pydantic types fit together (FR-009)
- [X] T005 [P] [US1] Edit the repo-root `AGENTS.md`: in the **File Structure** section, insert `python_sdk/ – Python client SDK - see [python_sdk/AGENTS.md](python_sdk/AGENTS.md)` between the existing `frontend/` and `dev/` entries (FR-006)
- [X] T006 [P] [US1] Edit the repo-root `AGENTS.md`: in the **Component Maps** section, insert a `Python SDK: python_sdk/AGENTS.md` bullet between the existing Frontend and Drivers entries (FR-007)

**Checkpoint**: `python_sdk/AGENTS.md` exists with architecture map + example, and the root `AGENTS.md` links to it from two sections. The doc is discoverable but does not yet contain the GraphQL operation workflow or boundaries — those are User Story 2 and 3.

---

## Phase 4: User Story 2 — GraphQL operation workflow with explicit "regen is not enough" warning (Priority: P1)

**Goal**: `python_sdk/AGENTS.md` documents the full step-by-step workflow for adding a new SDK operation, with a prominent callout that adding the `.graphql` file and regenerating types alone does NOT expose the operation through the SDK. This is the highest-cost recurring failure mode the source issue calls out.

**Independent Test**: Following `quickstart.md` mechanical checks 3 and 4, plus US2 review checklist items, passes. Smoke test (the "pretend you are an agent" walkthrough) leads a reader to update Python code without prompting.

### Implementation for User Story 2

- [X] T007 [US2] Append the **Adding or changing a GraphQL operation** section to `python_sdk/AGENTS.md`. Lead with the standalone warning callout (`> ⚠️ Regenerating types is not enough.` …) per `contracts/agents-md-outline.md` and `research.md` R4. The callout MUST state that `.graphql` + `uv run invoke generate` does not auto-wire `client.py` or `resources/<area>.py` (FR-003).
- [X] T008 [US2] In the same section, add the numbered step-by-step workflow: (1) create/edit `.graphql` file (one operation per file, snake_case, named operation; reference root `AGENTS.md` for repo-wide rules — do not duplicate); (2) run `uv run styrmin export graphql-schema schema.graphql` then `uv run invoke generate`; (3) run `uv run invoke validate-graphql`; (4) wire Python — split into "existing area" (add method to `resources/<area>.py`) vs "new area" (new resource module + instantiate in `StyrminClient.__init__`); (5) add tests under `python_sdk/tests/`; (6) `uv run invoke format lint` (FR-004, FR-008).

**Checkpoint**: A reader following the doc end-to-end produces a fully wired new operation without missing the Python step.

---

## Phase 5: User Story 3 — Always Do / Ask First / Never Do boundaries (Priority: P2)

**Goal**: `python_sdk/AGENTS.md` ends with an "Always Do / Ask First / Never Do" boundaries section structurally analogous to the root `AGENTS.md`, with SDK-specific entries.

**Independent Test**: `quickstart.md` mechanical check 5, plus US3 review checklist items, passes.

### Implementation for User Story 3

- [X] T009 [US3] Append the **Always Do / Ask First / Never Do** section to `python_sdk/AGENTS.md` per `contracts/agents-md-outline.md`. Required entries:
  - **Always Do**: run `validate-graphql` after touching `.graphql`; regenerate types after `.graphql` change; update both `.graphql` AND Python wiring in the same change; run `uv run invoke format lint` before commit; write tests for new resource methods.
  - **Ask First**: changes to `_transport.py`; breaking the public client API surface (`StyrminClient` or `*Resource` public method signatures); new third-party dependencies in `python_sdk/pyproject.toml`; reorganizing `resources/`.
  - **Never Do**: hand-edit `src/styrmin_sdk/graphql/_generated/`; inline GraphQL strings in Python; add unnamed operations; skip `validate-graphql` after `.graphql` changes (FR-005).

**Checkpoint**: All three user stories landed. `python_sdk/AGENTS.md` is complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification.

- [X] T010 Run `uv run invoke format lint` from the repo root and confirm clean (Constitution §VI). Result: 46 pre-existing diagnostics on the branch baseline; this docs-only change adds zero new diagnostics (verified via `git stash`/`stash pop` baseline comparison).
- [X] T011 Walk `quickstart.md`'s mechanical checks (1–6) and review checklist (US1-S1 through US3-S3); confirm every item passes. All five mechanical greps return expected counts; all eight review-checklist items satisfied by the produced doc.
- [X] T012 [P] Verify markdown links from the root `AGENTS.md` resolve (`python_sdk/AGENTS.md` exists at the linked path) and that internal anchors in `python_sdk/AGENTS.md` (if any) match heading slugs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Empty — does not block.
- **Phase 3 (US1)**: Can start after Setup. T003 must complete before T004 (both edit the same new file). T005 and T006 are parallel-safe with each other and with T003/T004 (they edit a different file).
- **Phase 4 (US2)**: Depends on T003 (the SDK doc must exist). T007 must precede T008 (same file, ordered append).
- **Phase 5 (US3)**: Depends on T003. T009 appends to the same file, ordered after T008.
- **Phase 6**: Depends on Phases 3–5.

### Within Each User Story

- All tasks within a single phase that touch the same file are sequential.
- Tasks marked [P] (T005, T006, T012) touch different files and can run alongside others.

### Parallel Opportunities

- T005 and T006 can run in parallel (both edit `AGENTS.md` but in disjoint sections — coordinate at edit time, but they're independent in design intent).
- T012 can run alongside any later cleanup work.

---

## Parallel Example: User Story 1

```bash
# After T003 (SDK doc skeleton) is in place, the two root-AGENTS.md edits
# can be done in parallel:
Task: "Edit AGENTS.md File Structure section to reference python_sdk/AGENTS.md"
Task: "Edit AGENTS.md Component Maps section to reference python_sdk/AGENTS.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 3: User Story 1 — SDK doc with architecture map, worked example, and root-`AGENTS.md` references
3. **STOP and VALIDATE**: A reader can find and orient inside the SDK doc. Stories 2 and 3 add the workflow detail and boundaries.

### Incremental Delivery

1. US1 → SDK doc is discoverable and orients the reader (MVP).
2. US2 → Add the GraphQL operation workflow with the explicit warning. The most user-valuable layer.
3. US3 → Add boundaries.
4. Polish → Lint + walkthrough.

### Single-Developer Strategy

This is a small docs change; one developer/agent runs all phases sequentially.

---

## Notes

- [P] tasks touch different files (or different sections of `AGENTS.md` that are non-conflicting in practice).
- All tasks operate on Markdown only; the `python_sdk/` Python source is read for accuracy but never modified.
- Commits should follow phase boundaries: one commit per user story phase, plus a final polish commit.
- Constitution §V E2E exemption applies (docs-only); reviewer approval substitutes for E2E execution per the spec's Assumptions.
