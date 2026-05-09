---
description: "Task list for 010-bug-pipeline-skills implementation"
---

# Tasks: Bug-Fixing Pipeline as Skills with GHAW Thin Wrappers

**Input**: Design documents from `specs/010-bug-pipeline-skills/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Per Constitution §V deviation (see plan.md Complexity Tracking), v1 testing is **manual smoke tests + `yamllint`**. No pytest E2E is part of v1 — proceeding requires explicit reviewer confirmation (T002).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4, US5)
- Include exact file paths in descriptions

## Path Conventions

- Skills: `.agents/skills/<skill-name>/SKILL.md`
- Workflows: `.github/workflows/bug-agent-<stage>.yml`
- Developer guide: `dev/guides/bug-pipeline.md`
- Contracts (design only, do not modify): `specs/010-bug-pipeline-skills/contracts/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the empty skill directories so SKILL.md authoring tasks have unambiguous targets.

- [X] T001 Create the four skill directories: `.agents/skills/bug-analyze/`, `.agents/skills/bug-fix/`, `.agents/skills/bug-test/`, `.agents/skills/bug-review/` (use `mkdir -p`; no files created in this task).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Resolve the one open governance gate before any user-story implementation begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Confirm with the reviewer that the Constitution §V deviation (no automated E2E for this meta-tooling feature, documented in `specs/010-bug-pipeline-skills/plan.md` → Complexity Tracking) is approved before implementation proceeds. Record the approval (or rejection) in the implementation PR description. If rejected, return to `/speckit-plan` and design an automated E2E approach before continuing.

  **Approval recorded 2026-05-09**: reviewer @damien (opsmill) approved the deviation during `/speckit-auto-implement` preflight. v1 testing is `yamllint` on the new workflow files plus the manual smoke-test procedure in `quickstart.md`; no pytest E2E. Smoke-test execution (T004, T006, T008, T010, T016) is **deferred to the reviewer**, who will run them post-merge against an issue of their choice — those tasks remain unchecked in this list.

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — bug-analyze (Priority: P1) 🎯 MVP

**Goal**: A maintainer can run `/bug-analyze <issue>` (locally or in CI) and receive a structured analyst comment on the target issue containing a hypothesis, affected files, reproduction steps, a `<!-- bug-pipeline:summary:start -->`-fenced YAML summary, and a suggested next command. Failure path posts a no-suggestion comment.

**Independent Test**: Per `quickstart.md` §1 — trigger `/bug-analyze <real-issue>` locally; verify the comment is posted and the YAML matches `contracts/analyst-summary-schema.md`. Trigger `/bug-analyze <vague-issue>` and verify a failure comment with no `next_command` is posted.

### Implementation for User Story 1

- [X] T003 [US1] Write `.agents/skills/bug-analyze/SKILL.md` with frontmatter (`name: bug-analyze`, `description`, `argument-hint`, `compatibility`) and body covering: (a) argument normalisation per research §R3, (b) fetching the issue body and comments via `gh`, (c) codebase investigation (root-cause hypothesis + affected files + reproduction steps), (d) posting a single comment whose final block is the YAML summary bracketed by the `<!-- bug-pipeline:summary:start -->` / `:end -->` markers and conforms to `contracts/analyst-summary-schema.md`, (e) success path ending with `> Next: /bug-fix NNN`, (f) failure path posting an explanation comment with no `next_command` and no YAML block, (g) handling missing/invalid arguments per `contracts/slash-command-protocol.md` "Skill responsibilities for invalid arguments". Skill MUST defer all coding-convention questions to existing `AGENTS.md` files (FR-003) and MUST NOT duplicate that content.

- [ ] T004 [US1] Smoke-test bug-analyze locally per `quickstart.md` §1 against (a) one well-described open issue and (b) one deliberately vague issue. Capture the comment URLs and confirm the YAML parses (e.g., `gh issue view <NNN> --json comments --jq '.comments[-1].body'` piped to a YAML reader). Both success and failure paths must behave as specified before declaring US1 done.

**Checkpoint**: US1 fully functional and independently testable from local CLI.

---

## Phase 4: User Story 2 — bug-fix (Priority: P2)

**Goal**: With an analyst comment present on an issue, `/bug-fix <issue>` creates a `bug/NNN-<short_description>` branch from `develop`, applies the fix, runs `uv run invoke format lint`, opens a draft PR (`Closes #NNN`, analyst summary in `<details>`), and posts an issue comment suggesting `/bug-test`. Lint failure or branch collision = failure path: no branch pushed, no PR opened, failure comment posted.

**Independent Test**: Per `quickstart.md` §2 — assumes US1's analyst comment exists; trigger `/bug-fix <issue>` locally; verify branch + draft PR + analyst block in `<details>`. Then trigger `/bug-fix <issue>` on an issue with no analyst comment to verify the failure path.

### Implementation for User Story 2

- [X] T005 [US2] Write `.agents/skills/bug-fix/SKILL.md` with frontmatter and body covering: (a) argument normalisation, (b) locating the most recent analyst comment with a `schema_version: 1` summary block on the target issue (failure if none), (c) branch creation `bug/<NNN>-<short_description>` rooted at `develop` (failure if branch already exists locally or remotely, per research §R5), (d) implementing the fix guided by the analyst summary, (e) running `uv run invoke format lint` and treating failure as a failure path per FR-010/FR-012 (no PR opened, failure comment with lint output verbatim, no branch pushed), (f) opening a **draft** PR using the template in research §R6 (`Closes #<NNN>`, summary in `<details>`, test-plan checklist), (g) posting an issue comment with `> Next: /bug-test NNN` on success, (h) posting a failure comment per FR-012 on any other failure path, (i) handling missing/invalid arguments per slash-command-protocol contract.

- [ ] T006 [US2] Smoke-test bug-fix locally per `quickstart.md` §2 on the issue from T004. Verify (i) branch named per pattern, (ii) draft PR with `Closes #NNN` and analyst `<details>`, (iii) `uv run invoke format lint` passes against the diff. Then trigger on an issue without an analyst comment to verify the missing-analyst-comment failure path. Optionally trigger on an issue where the chosen fix introduces a deliberate lint violation to verify the lint-failure path.

**Checkpoint**: US1 + US2 both work independently from local CLI.

---

## Phase 5: User Story 3 — bug-test (Priority: P2)

**Goal**: With an open draft PR linked to a bug issue, `/bug-test <issue|pr>` adds or modifies tests on the same branch covering the analyst's reproduction scenario, ensures the project test command passes, and posts a PR comment ending with a `/bug-review` suggestion.

**Independent Test**: Per `quickstart.md` §3 — assumes US2's draft PR exists; trigger `/bug-test` locally; verify new commits on the same branch, project test command passes, summary comment posted with `/bug-review` suggestion.

### Implementation for User Story 3

- [X] T007 [US3] Write `.agents/skills/bug-test/SKILL.md` with frontmatter and body covering: (a) argument normalisation (accepts issue or PR ref), (b) locating the open draft PR linked to the target issue and identifying its branch (must match `bug/<NNN>-*` pattern), (c) writing or extending tests on the **same branch** (NOT a new branch) such that they exercise the reproduction scenario from the analyst summary, (d) running the project's standard test command (delegated to `AGENTS.md`) and surfacing pass/fail honestly, (e) on success: pushing test commits and posting a PR comment summarising what was tested, ending with `> Next: /bug-review <pr-number>`, (f) on failure (cannot find PR, branch mismatch, tests don't pass): posting a failure comment with no next-command suggestion, (g) handling missing/invalid arguments per slash-command-protocol contract.

- [ ] T008 [US3] Smoke-test bug-test locally per `quickstart.md` §3 on the PR from T006. Verify new commits exist on the same branch, the project test command passes against the branch, and the PR comment ends with the `/bug-review` suggestion.

**Checkpoint**: US1, US2, US3 all work independently from local CLI.

---

## Phase 6: User Story 4 — bug-review (Priority: P2)

**Goal**: With a draft PR containing fix + tests, `/bug-review <pr>` reviews the diff against project conventions and either flips the PR to ready-for-review (pass) or keeps it draft and posts requested changes (fail).

**Independent Test**: Per `quickstart.md` §4 — exercise pass case (clean PR → ready-for-review) and fail case (deliberate lint or convention violation → stays draft, requested changes posted).

### Implementation for User Story 4

- [X] T009 [US4] Write `.agents/skills/bug-review/SKILL.md` with frontmatter and body covering: (a) argument normalisation (PR ref), (b) reviewing the PR diff against correctness, test coverage, formatting/linting compliance, and adherence to documented project conventions (defer to `AGENTS.md`), (c) posting a structured review comment that lists what was checked and any concerns, (d) on satisfied: marking the PR ready-for-review (`gh pr ready <N>`), (e) on not-satisfied: leaving the PR in draft, listing requested changes in the review comment, NOT marking ready-for-review, (f) respecting human-initiated draft flips per spec edge case (re-evaluate from current state on subsequent invocations), (g) handling missing/invalid arguments per slash-command-protocol contract. No `next_command` suggestion (review is the terminal stage).

- [ ] T010 [US4] Smoke-test bug-review locally per `quickstart.md` §4 on the PR from T008. Trigger once on the clean PR (pass case) and confirm ready-for-review transition. Then deliberately introduce a lint violation on the branch and re-trigger; confirm the PR returns to (or stays in) draft and requested changes are posted.

**Checkpoint**: All four skills work independently from local CLI. The pipeline is fully usable from the CLI; only US5 (GHAW wrappers) remains.

---

## Phase 7: User Story 5 — GHAW thin wrappers (Priority: P3)

**Goal**: Each `/bug-*` slash command, posted as a comment on a GitHub issue or PR, triggers the corresponding workflow which invokes the matching skill — with **no agent logic in the YAML** beyond checkout, permissions, concurrency control, and a single `claude-code-action@v1` invocation.

**Independent Test**: Per `quickstart.md` §1–§4 "Trigger from GitHub" — post each slash command as a comment and verify the same observable side effects as the local-CLI runs from US1–US4. Inspect each workflow file and confirm zero agent-prompt/branch/comment-formatting logic.

### Implementation for User Story 5

- [ ] T011 [P] [US5] Write `.github/workflows/bug-agent-analyst.yml` per research §R8 and slash-command-protocol contract: `name`, `on: issue_comment.created` with `if:` matching `/bug-analyze ` (with arg) and `/bug-analyze` (no arg, both line-anchored forms per the contract), `concurrency: { group: bug-pipeline-${{ github.event.issue.number }}, cancel-in-progress: false }`, `jobs.analyze` with `runs-on: ubuntu-latest`, `permissions: { contents: write, pull-requests: write, issues: write, id-token: write, actions: read }`, two steps: `actions/checkout@v6` (`fetch-depth: 0`) and `anthropics/claude-code-action@v1` with `anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}` and `prompt: '/bug-analyze ${{ github.event.issue.number }}'`. NO agent prompt text, branch logic, or comment-formatting logic anywhere in the YAML.

- [ ] T012 [P] [US5] Write `.github/workflows/bug-agent-fix.yml` mirroring T011's structure exactly, except: `if:` matches `/bug-fix`; `prompt: '/bug-fix ${{ github.event.issue.number }}'`.

- [ ] T013 [P] [US5] Write `.github/workflows/bug-agent-test.yml` mirroring T011's structure, except: `if:` matches `/bug-test`; the prompt invokes `/bug-test` against the issue or PR number depending on where the comment was posted (use `github.event.issue.number` since `issue_comment` events fire for both issue and PR comments and expose `issue.number`); `prompt: '/bug-test ${{ github.event.issue.number }}'`.

- [ ] T014 [P] [US5] Write `.github/workflows/bug-agent-review.yml` mirroring T011's structure, except: `if:` matches `/bug-review`; `prompt: '/bug-review ${{ github.event.issue.number }}'`.

- [ ] T015 [US5] Run `uv run yamllint .github/workflows/bug-agent-analyst.yml .github/workflows/bug-agent-fix.yml .github/workflows/bug-agent-test.yml .github/workflows/bug-agent-review.yml` and fix any violations until it passes clean. Confirm the same yamllint configuration that runs in `prek` pre-commit accepts the four files.

- [ ] T016 [US5] Smoke-test all four workflows by posting `/bug-analyze`, `/bug-fix`, `/bug-test`, `/bug-review` slash commands as comments on a sandbox issue/PR per `quickstart.md`. Verify (i) each workflow fires only for its corresponding command, (ii) the workflow logs show the skill being invoked with no extra prompt content, (iii) the produced GitHub side effects match the local-CLI smoke tests from T004/T006/T008/T010 (i.e., local-vs-CI parity per SC-006), (iv) inspecting each `.yml` file confirms zero agent logic. Record the workflow run URLs in the implementation PR description.

**Checkpoint**: Pipeline fully usable from both local CLI and GitHub UI; SC-006 (local-vs-CI parity) verified.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T017 [P] Write `dev/guides/bug-pipeline.md` covering: how to invoke each stage from GitHub (slash command on issue/PR) and from the local CLI; the four slash commands and their argument formats; what each stage does and what side effects to expect; the failure-comment vocabulary and how to recover; references to `specs/010-bug-pipeline-skills/contracts/` for the schema and trigger contracts. Follow `dev/guidelines/markdown.md` conventions; mirror the structure of existing guides like `dev/guides/local-demo.md` and `dev/guides/pre-commit-hooks.md`.

- [ ] T018 Run `uv run invoke format lint` and `uv run yamllint` (or equivalently, `prek run --all-files` if available) and confirm no regressions in linting/formatting are introduced by the implementation. `.agents/` is excluded from pre-commit by design, so SKILL.md content must be hand-reviewed for markdown conventions per `dev/guidelines/markdown.md`.

- [ ] T019 Update the implementation PR description to record: (a) the smoke-test URLs from T004, T006, T008, T010, T016; (b) the reviewer's confirmation of the Constitution §V deviation captured in T002; (c) any failure-path runs that were exercised. This satisfies SC-001 / SC-005 / SC-007 / SC-008 evidence.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup; **BLOCKS all user stories**. T002 must be resolved (approval recorded) before any skill or workflow file is written.
- **US1 (Phase 3)**: Depends on Foundational. No story-level deps.
- **US2 (Phase 4)**: Depends on Foundational. Smoke test (T006) depends on US1's analyst comment existing; SKILL writing (T005) is independent of US1 implementation.
- **US3 (Phase 5)**: Depends on Foundational. Smoke test (T008) depends on US2's draft PR; SKILL writing (T007) is independent.
- **US4 (Phase 6)**: Depends on Foundational. Smoke test (T010) depends on US3's tested PR; SKILL writing (T009) is independent.
- **US5 (Phase 7)**: Depends on Foundational. Smoke test (T016) depends on each underlying skill passing local smoke tests (T004, T006, T008, T010). Workflow YAML files (T011–T014) are independent of skill implementation.
- **Polish (Phase 8)**: T017 (dev guide) can be drafted any time after the contracts are stable (already true at Phase 2). T018 depends on all implementation tasks. T019 depends on all smoke tests being recorded.

### Within Each User Story

- SKILL.md authoring (single file per story) → smoke test against the previous story's output. No models/services/endpoints; meta-tooling is one-step-per-skill.

### Parallel Opportunities

- **T011, T012, T013, T014** (US5 workflow files): four independent files, can be authored in parallel.
- **T003, T005, T007, T009** (the four SKILL.md files): independent files. Story-priority ordering (US1 → US4) is recommended for staged delivery, but a single implementer with parallel agents could draft them concurrently. Smoke tests still follow priority order because they consume each other's outputs.
- **T017** (dev guide) can be drafted in parallel with T011–T014 since it touches a different file.

---

## Parallel Example: Phase 7 (US5)

```bash
# Launch all four workflow file authoring tasks in parallel:
Task: "Write .github/workflows/bug-agent-analyst.yml per research §R8"
Task: "Write .github/workflows/bug-agent-fix.yml per research §R8"
Task: "Write .github/workflows/bug-agent-test.yml per research §R8"
Task: "Write .github/workflows/bug-agent-review.yml per research §R8"

# Then sequentially:
yamllint pass (T015) → smoke-test in CI (T016)
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 (Setup) — T001.
2. Phase 2 (Foundational) — T002 reviewer approval.
3. Phase 3 (US1) — T003 (write `bug-analyze/SKILL.md`) + T004 (smoke test).
4. **STOP and VALIDATE**: maintainers can now triage bugs via `/bug-analyze` from the local CLI.
5. Optional early-MVP cut: also ship `bug-agent-analyst.yml` (T011 + T015) so the analyst is also usable from GitHub comments. This is the minimal end-to-end vertical slice.

### Incremental Delivery

1. Setup + Foundational + US1 → analyst available locally → demo.
2. Add US2 (fix) → maintainers can drive a fix end-to-end from the CLI → demo.
3. Add US3 (test) → fix + tests on the same branch → demo.
4. Add US4 (review) → AI gate before human review → demo.
5. Add US5 (workflows) → GitHub-comment trigger surface → demo.
6. Polish (T017–T019) → docs, lint pass, PR description.

### Parallel Team Strategy

With multiple implementers:

1. Foundational completed by one person (T002 is a process gate).
2. Once T002 approves, four implementers can take T003/T005/T007/T009 in parallel; smoke tests are coordinated sequentially because they chain on each other's GitHub side effects.
3. A fifth implementer can work on T011–T014 in parallel (workflows are independent of skill implementation files).
4. Polish (T017–T019) is the final integration step.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- `[Story]` label maps each task to its user story for traceability.
- Each user story is independently completable and testable (its smoke test consumes the prior story's GitHub side effects, which can be **manually prepared** if the prior story isn't done yet — preserving independent-testability per spec).
- No automated test tasks are listed: per Constitution §V deviation (T002 gate), v1 testing is `yamllint` + manual smoke tests documented in `quickstart.md`.
- Commit after each task or at logical groupings per `speckit-checkpoint-commit`.
- Stop at any checkpoint to validate the increment.
- The contracts in `specs/010-bug-pipeline-skills/contracts/` are design artifacts — do **not** modify them during implementation. If a contract change is needed, return to `/speckit-plan` and run a critique cycle.
