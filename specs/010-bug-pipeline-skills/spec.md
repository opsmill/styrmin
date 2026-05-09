# Feature Specification: Bug-Fixing Pipeline as Skills with GHAW Thin Wrappers

**Feature Branch**: `010-bug-pipeline-skills`
**Created**: 2026-05-09
**Status**: Draft
**Input**: GitHub issue [opsmill/styrmin#206](https://github.com/opsmill/styrmin/issues/206), comment [4412408973](https://github.com/opsmill/styrmin/issues/206#issuecomment-4412408973) — "PRD: Bug-Fixing Pipeline as Skills with GHAW Thin Wrappers"

## Summary

Bug fixes in Styrmin are currently handled ad-hoc: triage, root-cause hunting, fix, tests, and review all happen by hand, with no shared structure and no easy way to invoke AI assistance without bespoke prompting. The Infrahub project (`opsmill/infrahub#9043`) ships a four-stage AI bug-fixing pipeline, but its agent logic is buried inside `.github/bug-agent-pipeline/` files reachable only through GitHub Actions — developers cannot run any stage locally, and improving the prompts requires a CI round-trip.

This feature adapts that pipeline for Styrmin so that the agent logic lives in **standalone skills**, with GitHub Actions workflows acting as **thin wrappers** that simply invoke the corresponding skill. The same logic that runs in CI is also runnable from a developer's local CLI.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Investigate a reported bug with one command (Priority: P1)

A maintainer sees a freshly filed bug report and wants a structured first-pass investigation: a root-cause hypothesis, a list of suspect files, and reproduction steps — without crafting a custom prompt every time.

**Why this priority**: This is the foundational stage. It produces the structured analysis that every downstream stage consumes. Even without the rest of the pipeline, an automated triage step is independently valuable — it accelerates every bug, including those that ultimately need human follow-up.

**Independent Test**: A maintainer triggers the analyze stage on an open Styrmin issue (passing either the issue number or a full issue URL). Within a single run, a comment is posted on the issue containing a hypothesis, affected files, reproduction steps, a machine-readable summary block, and a suggested next-stage command. The same trigger works locally on a developer's CLI without invoking GitHub Actions.

**Acceptance Scenarios**:

1. **Given** an open bug issue with a clear description, **When** a maintainer triggers the analyze stage with the issue number, **Then** a comment is posted on the issue containing a hypothesis, affected files, reproduction steps, a fenced machine-readable summary block, and a suggested command to invoke the next stage.
2. **Given** the same trigger but with a full issue URL, **When** the analyze stage runs, **Then** the URL is normalised and the same comment is produced.
3. **Given** an issue where the description is too vague to support a hypothesis, **When** the analyze stage runs, **Then** a failure comment is posted explaining what was investigated and where the analysis got stuck, and **no** next-stage command is suggested.
4. **Given** a developer working locally, **When** they invoke the analyze stage from their CLI with an issue argument, **Then** the same comment is produced as in CI without any GitHub Actions context.

---

### User Story 2 — Implement a fix on a feature branch and open a draft PR (Priority: P2)

After validating the analysis, the maintainer wants to turn the hypothesis into an actual code change on a clearly-named branch, with the analyst's findings carried into the PR description so reviewers don't have to bounce back to the issue.

**Why this priority**: This is the value-creating stage — it produces the candidate fix. It depends on US1 (it consumes the analyst's machine-readable summary) but is independently valuable: even with no further stages, a maintainer gets a draft PR ready for human review.

**Independent Test**: With an analyst comment already on an issue, a maintainer triggers the fix stage and observes that a `bug/NNN-*` branch is created, the fix is applied, linting/formatting passes, and a draft PR is opened with `Closes #NNN`, the standard PR template, and the analyst's summary embedded in a collapsible section.

**Acceptance Scenarios**:

1. **Given** an issue with a complete analyst comment, **When** the fix stage is triggered with the issue number, **Then** a branch named `bug/NNN-<short-description>` is created from the default branch and a fix is committed to it.
2. **Given** the fix has been committed, **When** the fix stage finishes, **Then** project formatting and linting have been run successfully on the changes.
3. **Given** the branch is ready, **When** the fix stage opens a PR, **Then** the PR is in **draft** state, includes `Closes #NNN`, and embeds the analyst's machine-readable summary inside a collapsible section in the PR description.
4. **Given** the fix stage cannot determine a clean fix from the analysis (e.g., conflicting hypotheses, missing context), **When** it gives up, **Then** it posts a failure comment on the issue explaining what was attempted, and does **not** open a PR or push a branch.

---

### User Story 3 — Add tests covering the fixed behaviour (Priority: P2)

Once a fix exists on a branch, the maintainer wants to ensure regression coverage by writing or extending tests that exercise the previously-broken behaviour, on the same branch as the fix so they travel together.

**Why this priority**: Tests are required for merging under existing project conventions. The stage is independently valuable: even if review is done by humans, having Claude write the regression tests saves significant manual work and ensures fixes don't regress.

**Independent Test**: With an open draft PR linked to a bug issue, the maintainer triggers the test stage and observes that test files are added or extended on the same branch, the additions cover the bug's reproduction scenario, the tests pass, and a comment is posted on the PR summarising what was tested and suggesting the review stage.

**Acceptance Scenarios**:

1. **Given** an open draft PR linked to a bug issue, **When** the test stage is triggered, **Then** new or modified test files are pushed to the **same branch** as the fix.
2. **Given** the tests are pushed, **When** they run as part of the project's test command, **Then** they pass and exercise the reproduction scenario from the analyst's summary.
3. **Given** the test stage completes successfully, **When** it posts its summary comment on the PR, **Then** the comment ends with a suggested command to invoke the review stage.

---

### User Story 4 — Review the fix and tests, gate ready-for-review state (Priority: P2)

When the fix and tests are in place, the maintainer wants an AI quality gate that reviews the diff against project conventions and either flips the draft PR to ready-for-review (if satisfied) or posts requested changes and keeps it in draft (if not).

**Why this priority**: The review stage is the safety valve that prevents incomplete fixes from reaching human reviewers with a green signal. Like the other stages, it's independently valuable on a manually-prepared draft PR.

**Independent Test**: With a draft PR containing a fix and tests, the maintainer triggers the review stage and observes a structured review comment posted on the PR detailing what was checked. If the review passes, the PR moves to ready-for-review; if not, it stays in draft and the comment lists requested changes.

**Acceptance Scenarios**:

1. **Given** a draft PR with a fix and tests that satisfy project conventions, **When** the review stage runs, **Then** it posts a structured review comment listing what was checked (correctness, coverage, lint, conventions) and marks the PR ready-for-review.
2. **Given** the review identifies issues (e.g., missing edge case, lint violation, mismatch with conventions), **When** the review stage finishes, **Then** the PR remains in draft, the review comment lists the requested changes, and ready-for-review is **not** flipped.

---

### User Story 5 — Trigger any stage from a GitHub comment (Priority: P3)

A maintainer wants to drive the entire pipeline from the GitHub UI by typing slash commands as comments on the issue or PR — without leaving the browser to open a terminal.

**Why this priority**: This makes the pipeline accessible to maintainers who triage from GitHub on mobile or who don't have a local checkout handy. It's an extension on top of US1–US4: the skills already work locally; this story adds a GitHub-side trigger surface.

**Independent Test**: A maintainer types `/bug-analyze <issue>` (or the corresponding command for any stage) as a comment on the relevant issue or PR. Within a few minutes, the same observable side effects occur as when the stage is triggered locally, and the agent logic invoked is **identical** to the local skill (no logic duplicated in the workflow YAML).

**Acceptance Scenarios**:

1. **Given** a maintainer has the required permissions, **When** they post a comment containing `/bug-analyze <issue-number-or-url>` on any issue, **Then** a workflow runs that invokes the analyze skill and the analyst comment appears on the issue.
2. **Given** a maintainer posts `/bug-fix`, `/bug-test`, or `/bug-review` with the appropriate target, **When** the corresponding workflow runs, **Then** the same outputs as the local-CLI invocation are produced.
3. **Given** the workflow files are inspected, **When** a developer reads them, **Then** they contain only repository checkout, permissions setup, and a single skill invocation — **no agent prompt, branch logic, or comment-formatting logic** lives in the workflow YAML.

---

### Edge Cases

- **Issue argument formats**: Both bare issue numbers (`206`) and full URLs (`https://github.com/opsmill/styrmin/issues/206`) must be accepted by every stage that takes an issue argument; both must produce the same result.
- **Stage skipped**: A maintainer triggers `/bug-fix` on an issue that has no analyst comment yet. The fix stage must handle the missing analyst summary gracefully — posting a failure comment that points the maintainer to run analyze first, rather than producing a broken PR.
- **Multiple analyst comments**: An issue may accumulate several analyze runs over time. The fix stage must use the **most recent** analyst comment that contains a valid machine-readable summary block.
- **Branch already exists**: A previous fix attempt may have left a `bug/NNN-*` branch. The fix stage must either reuse, replace, or namespace its branch in a deterministic way that is documented in the failure comment if it cannot proceed.
- **Lint or test failure during fix**: If the fix passes the agent's correctness check but fails project linting or tests, the fix stage MUST treat this as a failure path per FR-010 / FR-012 (failure comment, no branch pushed, no PR opened). This is the deterministic behaviour for v1; the previously-mentioned alternative ("clearly-flagged draft PR with the failure recorded") is rejected to keep CI and local runs identical.
- **No bug label gating**: The pipeline must work on **any** issue regardless of labels — no label is required to trigger the stages, so the pipeline is usable for triage as well as for confirmed bugs.
- **Reviewer flips PR back to draft**: If a human reviewer manually reverts the PR to draft after the review stage marked it ready-for-review, subsequent re-runs of `/bug-review` must respect the human action and re-evaluate from the current state.

## Requirements *(mandatory)*

### Functional Requirements

#### Skills — general

- **FR-001**: The system MUST provide four standalone skills — analyze, fix, test, review — each runnable from a developer's local CLI without any GitHub Actions context.
- **FR-002**: Each skill MUST be self-contained and accompanied by skill-level documentation that explains its purpose, inputs, outputs, and failure modes — sufficient for a developer to understand and improve the skill without reading any CI configuration.
- **FR-003**: Skills MUST rely on the existing project guidelines for coding conventions, test commands, and stack layout — they MUST NOT duplicate that information inside the skill files.
- **FR-004**: Every skill that takes an issue or PR argument MUST accept either a bare numeric identifier or a full GitHub URL, and MUST normalise both to the canonical form internally.

#### Analyze stage

- **FR-005**: The analyze stage MUST fetch the target issue's body and existing comments and use them as the basis for investigation.
- **FR-006**: On success, the analyze stage MUST post a single comment on the issue containing: (a) a prose root-cause hypothesis; (b) a list of affected files; (c) reproduction steps; (d) a fenced machine-readable summary block in a structured format that downstream stages can parse without fuzzy matching; (e) a suggested command for the next stage.
- **FR-007**: On failure (e.g., insufficient information to produce a hypothesis), the analyze stage MUST post a comment explaining what was investigated and where it got stuck, and MUST NOT include a next-stage command suggestion.

#### Fix stage

- **FR-008**: The fix stage MUST consume the most recent valid analyst comment on the issue (i.e., the most recent comment containing a parseable machine-readable summary).
- **FR-009**: The fix stage MUST create a branch named `bug/<NNN>-<short-description>` from the default branch, where `<NNN>` is the issue number.
- **FR-010**: The fix stage MUST run the project's standard formatting and linting commands on its changes before opening a PR. If those commands fail, the stage MUST treat the failure as a failure path per FR-012 — no PR is opened, no branch is pushed, and a failure comment is posted on the issue with the lint output included verbatim. The fix stage MUST NOT open a PR with known formatting or linting violations.
- **FR-011**: On success, the fix stage MUST open a **draft** PR whose description (a) contains `Closes #<NNN>` and (b) embeds the analyst's machine-readable summary inside a collapsible section so reviewers have full context without leaving the PR view.
- **FR-012**: On failure, the fix stage MUST post a comment on the issue explaining what was attempted, MUST NOT push a branch, and MUST NOT open a PR.

#### Test stage

- **FR-013**: The test stage MUST locate the open draft PR linked to the target issue and identify the fix branch from it.
- **FR-014**: The test stage MUST add or modify tests on the **same branch** as the fix (not on a new branch).
- **FR-015**: The added or modified tests MUST exercise the reproduction scenario described in the analyst's summary, and MUST pass when run via the project's standard test command.
- **FR-016**: On success, the test stage MUST post a comment on the PR summarising what was tested and ending with a suggested command for the review stage.

#### Review stage

- **FR-017**: The review stage MUST review the PR diff against: correctness of the fix, sufficiency of test coverage, formatting/linting compliance, and adherence to documented project conventions.
- **FR-018**: The review stage MUST post a structured review comment that lists what was checked and any concerns found.
- **FR-019**: When the review is satisfied with all checks, the review stage MUST mark the PR as ready-for-review.
- **FR-020**: When the review is not satisfied, the review stage MUST keep the PR in draft, MUST list requested changes in the review comment, and MUST NOT mark the PR ready-for-review.

#### Stage chaining and triggers

- **FR-021**: Stages MUST chain via a hybrid model: each stage is triggered manually by a comment command, and on success the previous stage's output comment includes a suggestion for the next command. Stages MUST NOT auto-fire the next stage without a human comment trigger.
- **FR-022**: The pipeline MUST work on any issue regardless of labels — label-gating MUST NOT be a precondition for triggering any stage.

#### GitHub Actions workflows (thin wrappers)

- **FR-023**: The system MUST provide four workflow files — one per stage — that are triggered by the corresponding `/bug-analyze`, `/bug-fix`, `/bug-test`, `/bug-review` comment commands on issues or PRs.
- **FR-024**: Each workflow file MUST contain only repository checkout, permission setup, and a single invocation of the corresponding skill — **no agent prompts, no branch logic, no comment-formatting logic** may live in the workflow YAML.
- **FR-025**: Each workflow MUST request the same permission scope used by the existing Claude integration: write access to repository contents, pull requests, and issues.
- **FR-026**: Workflow files MUST pass the project's existing GitHub Actions linting (the same linter already run in CI on workflow files).

#### Documentation

- **FR-027**: The system MUST include a short developer guide explaining how to trigger each stage from GitHub (via the comment command) and from the local CLI.

### Key Entities

- **Bug-issue argument**: A reference to a GitHub issue, accepted in two forms (bare number or full URL) and normalised to a canonical issue number plus URL pair internally.
- **Analyst comment**: A GitHub issue comment containing prose investigation sections plus a fenced machine-readable summary block. The summary block is the contract between the analyze stage and downstream stages.
- **Fix branch**: A git branch named `bug/<NNN>-<short-description>` rooted at the default branch, containing the fix commit(s) from the fix stage and any test commits added by the test stage.
- **Pipeline draft PR**: A draft pull request opened by the fix stage, identified by its link to a bug issue (`Closes #<NNN>`), and progressed by the test stage (more commits) and review stage (state change).
- **Stage suggestion**: The trailing line in a successful stage's output comment naming the next command a maintainer should type. Absent on failure paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer can take a previously unanalysed bug from issue to a draft PR with passing tests and a positive review by typing exactly four comment commands (one per stage), with no manual prompt crafting required.
- **SC-002**: For at least 80% of well-described bug issues exercised during validation, the analyze stage produces a hypothesis specific enough that the fix stage can act on it without human intervention between the two stages.
- **SC-003**: 100% of fix-stage runs that complete successfully open a draft PR that links to its source issue via `Closes #<NNN>` and embeds the analyst summary in a collapsible section.
- **SC-004**: 100% of test-stage runs that complete successfully push their tests to the same branch as the fix and produce a passing run of the project's standard test command.
- **SC-005**: 100% of review-stage runs leave the PR in a state consistent with the review verdict — ready-for-review on pass, draft on fail — with **no** false-positive ready-for-review flips.
- **SC-006**: A developer can run any stage locally from their CLI and observe the same side effects (comment posted, branch pushed, PR state updated) as the equivalent CI run, with no logic divergence between the two paths.
- **SC-007**: All agent prompt and orchestration logic lives in skill files; no workflow YAML file contains agent prompts, branch-naming rules, or comment-formatting templates. Verified by inspection of each workflow file.
- **SC-008**: A failure path on any stage produces a clear failure comment that names what was attempted and where the stage gave up, and does **not** suggest a next-stage command — verified by triggering each stage against an input designed to fail.

## Assumptions

- The pipeline targets the `opsmill/styrmin` repository and is invoked by maintainers with write access to issues, PRs, and contents. Permissions for non-maintainer users are out of scope.
- The machine-readable summary format is a fenced YAML block. (Per the source PRD; alternative structured formats like JSON would also satisfy the requirements as long as downstream stages can parse without fuzzy matching.)
- The fix stage uses the project's default branch (e.g., `develop`) as the base for new fix branches; no other base branches are supported in v1.
- The review stage's "satisfied" criterion is judged by the agent against documented project conventions; there is no separate threshold or scoring system in v1.
- Workflow triggers are GitHub `issue_comment` events matched on the `/bug-*` command. Other trigger styles (label-add, schedule) are out of scope.
- Stages are invoked sequentially by humans. Concurrency control (e.g., preventing two `/bug-fix` invocations on the same issue from racing) is out of scope; if it becomes an operational issue, it is addressed in a follow-up.
- The pipeline coexists with the existing general-purpose `@claude` review workflow. The bug-review stage is pipeline-aware; the existing workflow remains the general-purpose path.
- Out-of-scope items per the source PRD: the `gh aw compile` / `.lock.yml` GHAW compilation step, streaming CI logs into the analyst's investigation, auto-chaining stages without human confirmation, label-gating eligibility.
