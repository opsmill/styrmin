# Phase 0 Research: Bug-Fixing Pipeline as Skills with GHAW Thin Wrappers

This document captures the design decisions made during planning, the alternatives evaluated, and why each one was chosen. There were **no `[NEEDS CLARIFICATION]` markers** carried over from `spec.md`; every entry below resolves a design choice the spec deliberately left to the plan.

## R1. Skill packaging: per-stage directory, single `SKILL.md`

- **Decision**: Each stage is a separate directory under `.agents/skills/` (`bug-analyze/`, `bug-fix/`, `bug-test/`, `bug-review/`), each containing exactly one `SKILL.md` for v1.
- **Rationale**:
  - Matches the existing convention in `.agents/skills/` (`create-issue/`, `pr/`, `dev-validate/`, `rebase/` — all single-directory, single-`SKILL.md`).
  - Keeps the change surface minimal; supplementary files (scripts, asset templates) are easy to add later if a skill grows.
  - Satisfies FR-002 (each skill self-contained) without inventing a fifth "shared" skill.
- **Alternatives considered**:
  - **Single `bug-pipeline/` skill with sub-commands**: rejected — the source PRD and FR-001/FR-024 explicitly require four separately-invokable skills, and one umbrella skill would also blur the skill ↔ workflow 1:1 mapping that FR-024 requires.
  - **Shared instruction module (`.agents/skills/bug-pipeline-shared/`)** referenced from each of the four skills: rejected for v1 — couples the four skills together (defeats FR-002) and adds a level of indirection. If, after implementation, three or more skills end up duplicating ≥30 lines of identical instructions, the shared module is a worthwhile follow-up; not before.

## R2. Skill frontmatter conventions

- **Decision**: Each `SKILL.md` opens with YAML frontmatter following the existing pattern from `.agents/skills/create-issue/SKILL.md`:

  ```yaml
  ---
  name: bug-<stage>
  description: <one-line summary of what the skill does>
  argument-hint: <how the user types the argument>
  compatibility: Requires GitHub access (gh CLI authenticated, or equivalent) and write access to the target repository.
  ---
  ```

- **Rationale**: Aligns new skills with the conventions that other skills already follow, so the skill discovery output (the same list shown in the system prompt) reads consistently.
- **Alternatives considered**: A bespoke schema specific to bug-pipeline skills — rejected as an unnecessary departure from the existing convention.

## R3. Argument normalisation

- **Decision**: Argument normalisation is described as **instruction text** inside each `SKILL.md`. The agent at runtime parses the argument and uses `gh` / `git` to canonicalise. No script or Python helper is introduced.
- **Normalisation rule**: 
  - If the argument starts with `http`, parse as a URL and extract the issue/PR number from the path.
  - Otherwise, treat the argument as a bare numeric identifier and construct the canonical URL by combining it with the repo URL from `gh repo view --json url`.
  - Empty argument → fail loudly with a usage message.
- **Rationale**: Skills are agent-executed; encoding parsing as instruction text is sufficient and avoids introducing a separate tested helper for trivial logic.
- **Alternatives considered**:
  - A Python helper under `tasks/` or a small shell script: rejected — adds a piece of code that has to be tested, packaged, and discovered, for logic the agent can perform inline.
  - Punting normalisation to the workflow YAML: rejected — would leak logic into the YAML, violating FR-024.

## R4. Inter-stage data contract: fenced YAML "machine-readable summary" block

- **Decision**: The analyst's issue comment ends with a fenced YAML block whose schema is documented in `contracts/analyst-summary-schema.md`. The fence uses the language tag `yaml` and is framed by a stable HTML comment marker so consumers can locate it without fuzzy matching:

  ```markdown
  <!-- bug-pipeline:summary:start -->
  ```yaml
  schema_version: 1
  issue: { number: 206, url: "https://github.com/opsmill/styrmin/issues/206" }
  hypothesis: "…"
  affected_files: ["…", …]
  reproduction:
    - "…"
  short_description: "…"
  next_command: "/bug-fix 206"
  ```
  <!-- bug-pipeline:summary:end -->
  ```

- **Rationale**:
  - The HTML comment markers are invisible to GitHub readers but provide a deterministic anchor for `gh` / parser code.
  - YAML matches the source PRD; it's human-readable in a comment and supports nested structures naturally.
  - `schema_version` lets us evolve the schema later without breaking older consumers.
- **Alternatives considered**:
  - **JSON in a fenced block**: also valid but harder for humans to scan.
  - **Hidden comment-only payload (no fenced block)**: rejected — losing the human-readable form makes debugging harder.
  - **No machine-readable block, parse prose**: explicitly rejected by FR-006(d).

## R5. Branch naming and base branch

- **Decision**: Fix branches are named `bug/<NNN>-<short-description>` and are rooted at the project's default branch (`develop` per the gitStatus snapshot) at the time the fix stage runs. The `<short-description>` is derived from the analyst's `short_description` field (kebab-cased, max ~40 chars).
- **Branch-already-exists policy**: if a branch with the target name already exists locally or on the remote, the fix stage **fails with a clear comment** describing the collision rather than silently overwriting or namespacing. The maintainer can delete or rename the existing branch and re-run. This is a deliberate v1 simplicity choice.
- **Rationale**:
  - Matches the PRD prescription.
  - Failing on collision is the safest deterministic behaviour (no silent data loss); the alternative of auto-suffixing produces unpredictable branch names that downstream stages would then have to discover.
- **Alternatives considered**:
  - Auto-suffix (`bug/206-...-2`): rejected for v1 — pushes complexity into the test/review stages that have to find the right branch.
  - Reuse-and-amend: rejected — would silently modify previous attempts and break PR review history.

## R6. PR description template

- **Decision**: The fix stage opens a draft PR whose description follows the template:

  ```markdown
  Closes #<NNN>

  ## Summary

  <2–3 line summary derived from the analyst's hypothesis and the actual change>

  <details>
  <summary>Analyst summary (machine-readable)</summary>

  ```yaml
  <verbatim YAML from the analyst comment>
  ```
  </details>

  ## Test plan

  - [ ] <items derived from the reproduction steps; checkbox unchecked until the test stage adds tests>
  ```

- **Rationale**: `Closes #<NNN>` satisfies FR-011a; the `<details>` block satisfies FR-011b (full context in PR view); the test-plan checklist hooks into the test stage's expected behaviour.
- **Alternatives considered**: putting the analyst summary inline (not collapsed) — rejected because the YAML is dense and dominates the PR description visually.

## R7. Workflow trigger and gating

- **Decision**: All four workflows trigger on `issue_comment.created` events whose `body` matches the corresponding `/bug-*` command. The workflow `if:` clause matches the prefix only at the start of a line, so embedded mentions in long discussion comments don't fire it.
- **Rationale**: Mirrors the trigger style used by `claude.yml` (which gates on `@claude` substring), but tightens to a leading-prefix match so accidental mentions don't run the pipeline.
- **Permissions** (matching `claude.yml`):
  - `contents: write`, `pull-requests: write`, `issues: write`, `id-token: write`, `actions: read`.
- **Alternatives considered**:
  - Triggering on label events: rejected — FR-022 disallows label-gating.
  - Triggering on a custom `repository_dispatch` event: rejected — would require a separate trigger mechanism and break the "type a comment in the GitHub UI" UX.

## R8. Workflow YAML scope (FR-024 enforcement)

- **Decision**: Each workflow file contains, in order:
  1. `name:`
  2. `on:` (issue_comment trigger + the prefix-match `if:` per `contracts/slash-command-protocol.md`)
  3. `concurrency:` keyed on the issue number — `group: bug-pipeline-${{ github.event.issue.number }}`, `cancel-in-progress: false`. This is workflow orchestration, not agent logic, so it does not violate FR-024. It prevents two simultaneous `/bug-fix` (or any same-stage) invocations on the same issue from racing.
  4. `jobs.<stage>:` with `runs-on`, `permissions`, and exactly two `steps`:
     - `actions/checkout@v6` (with `fetch-depth: 0` so the agent can branch from history)
     - `anthropics/claude-code-action@v1` with `prompt: '/bug-<stage> ${{ github.event.issue.number }}'`
- **What's explicitly forbidden in YAML**: agent prompt text beyond the slash command, branch-naming logic, comment templates, summary parsing.
- **Rationale**: keeps FR-024 mechanically verifiable — a reviewer can read each YAML file in under 30 seconds and confirm there's no agent logic. The `concurrency:` block is admitted because it expresses *when the workflow runs*, not *what the agent does*.
- **Alternatives considered**:
  - Including a small `if:` to filter by user permissions: rejected for v1 — GitHub already gates the trigger by repo permissions; adding our own gate would diverge from the existing `claude.yml` precedent.
  - Pre-parsing the comment body in YAML to extract arguments before invoking Claude: rejected — that's logic, FR-024 forbids it; let the skill handle it.
  - Using `cancel-in-progress: true` instead of `false`: rejected — cancelling an in-flight fix mid-write could leave a half-pushed branch.

## R9. Test strategy (Constitution §V deviation)

- **Decision**: For v1, automated coverage is limited to:
  1. `yamllint` validation of the four new workflow files (runs in `prek` pre-commit and is enforced in CI).
  2. A documented manual smoke-test procedure in `quickstart.md` exercising each stage end-to-end against a sandbox issue.
- **Rationale**: see plan.md → Complexity Tracking. The deviation requires explicit reviewer approval per Constitution §V.
- **Alternatives considered and rejected**:
  - Pytest E2E hitting real GitHub + real LLM: too expensive (LLM credits per run, flakiness, secret management) for the value delivered.
  - Mocked pytest E2E: tests trivial parsing logic; doesn't test the integration that matters; produces false confidence.
- **Follow-up**: a future iteration may add a CI smoke-test job that creates a sandbox issue in a fixture repo and asserts the analyst comment appears. Out of scope for v1.

## R10. Documentation entry point

- **Decision**: A single guide at `dev/guides/bug-pipeline.md` covers: how to trigger from GitHub, how to trigger locally, the slash-command vocabulary, what each stage does, and how to inspect failure comments.
- **Rationale**: matches the existing `dev/guides/*.md` convention (cf. `pre-commit-hooks.md`, `local-demo.md`); single file keeps the surface low.
- **Alternatives considered**: scattering one README per skill — rejected, the SKILL.md frontmatter `description` plus the central guide is sufficient.

## Open questions deferred to implementation or follow-ups

- Should the workflows include a concurrency group keyed on the issue number to prevent two `/bug-fix` invocations from racing? **Deferred** — out-of-scope per spec Assumptions, revisit if it bites in practice.
- Should the analyst's "next command" suggestion include the issue URL or just the number? **Deferred** — implementation choice; either is acceptable. Default: number, matches the source PRD.
- Should each skill ship example outputs in its `SKILL.md`? **Yes** — improves CLI usability. Keep them short (≤20 lines each) so the skill stays readable.
