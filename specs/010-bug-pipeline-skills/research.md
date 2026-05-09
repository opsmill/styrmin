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

- **Decision**: All four workflows trigger on `issue_comment.created` events whose `body` matches the corresponding `/bug-*` command. As of Iteration 2026-05-09 (GHAW adoption), the trigger is declared in the GHAW `.md` frontmatter via `slash_command:` rather than a hand-written `if:` clause. The GHAW compiler emits the line-anchored matching logic into the `.lock.yml`; matching semantics (line-start prefix, both with-arg and no-arg forms) are preserved.
- **Rationale**: Mirrors the trigger style used by `claude.yml` (which gates on `@claude` substring), but tightens to a leading-prefix match so accidental mentions don't run the pipeline. Using GHAW's `slash_command:` primitive replaces the bespoke `if:` clause with a maintained tooling abstraction; behaviour is identical from the maintainer's perspective.
- **Permissions** (matching `claude.yml`):
  - `contents: write`, `pull-requests: write`, `issues: write`, `id-token: write`, `actions: read`.
- **Alternatives considered**:
  - Triggering on label events: rejected — FR-022 disallows label-gating.
  - Triggering on a custom `repository_dispatch` event: rejected — would require a separate trigger mechanism and break the "type a comment in the GitHub UI" UX.
  - Keeping a hand-written `if:` clause instead of GHAW's `slash_command:`: rejected by Iteration 2026-05-09 — the iteration adopts GHAW tooling so the workflow source is authored in the upstream-supported abstraction.

## R8. Workflow source scope (FR-024 enforcement)

- **Decision (post-Iteration 2026-05-09)**: Each workflow is now a GHAW `.md` source plus a `gh aw compile`-generated `.lock.yml` artifact. The `.md` is the authoritative source; the `.lock.yml` is an opaque build output committed to git for CI to consume.
- **`.md` source structure** (in order):
  1. **Frontmatter** declaring: `description`, `on: slash_command:` (with `name`, `events`), `engine: claude`, `permissions:` (matching `claude.yml`), `concurrency:` (`group: bug-pipeline-${{ github.event.issue.number }}`, `cancel-in-progress: false`), auth wiring (`anthropic_api_key` via `secrets.ANTHROPIC_API_KEY`), checkout config (`fetch-depth: 0`).
  2. **Body** = exactly one line: the slash-command invocation, e.g. `/bug-analyze ${{ github.event.issue.number }}`. **No prose, no agent prompt, no instructions.** All agent logic lives in `.agents/skills/bug-<stage>/SKILL.md`.
- **What's explicitly forbidden** in either the `.md` source or the `.lock.yml` output: agent prompt text beyond the slash command, branch-naming logic, comment templates, summary parsing.
- **Rationale**: keeps FR-024 mechanically verifiable — a reviewer reads each `.md` in under 30 seconds and confirms the body is one slash-command line. The `concurrency:` block is admitted because it expresses *when the workflow runs*, not *what the agent does*. GHAW's `slash_command:` trigger replaces the hand-written `if:` clause without changing behaviour.
- **Lock file**: `gh aw compile` produces `<stage>.lock.yml` next to the `.md`. The lock file embeds shell/JS that exceeds normal `yamllint` rules; per Iteration 2026-05-09 it is excluded from `yamllint` via `.yamllint.yml` (mirrors `opsmill/infrahub#9043`).
- **Alternatives considered**:
  - Hand-authored `.yml` files (the pre-Iteration form): rejected by user request to adopt `gh aw compile`.
  - Full Infrahub-style (agent prompt inline in the `.md` body): rejected — would walk back FR-001 (local-CLI parity) and FR-002 (skill self-containment); was explicitly the pattern the source PRD set out to avoid.
  - Including a small `if:` to filter by user permissions: rejected for v1 — GitHub already gates the trigger by repo permissions; adding our own gate would diverge from the existing `claude.yml` precedent.
  - Pre-parsing the comment body to extract arguments before invoking the skill: rejected — that's logic, FR-024 forbids it; let the skill handle it.
  - Using `cancel-in-progress: true` instead of `false`: rejected — cancelling an in-flight fix mid-write could leave a half-pushed branch.

## R11. GHAW adoption (HYBRID mode) — added 2026-05-09

- **Decision**: Adopt the `gh aw` GitHub CLI extension as the project's workflow-authoring tool for the four bug-agent stages. Workflow definitions are authored as `.md` source files; `gh aw compile` produces `.lock.yml` artifacts that GitHub Actions runs.
- **HYBRID specifically**: only the workflow surface uses GHAW. Agent logic stays in `.agents/skills/bug-*/SKILL.md`. The `.md` body is the slash-command invocation only — GHAW gives us its `slash_command:` trigger and validated compilation, without taking over the prompt-authoring surface that the original PRD reserved for skills.
- **Rationale**:
  - Preserves FR-001 (local-CLI parity) and FR-002 (skill self-containment) — the original design point that motivated the source PRD.
  - Adopts the upstream-maintained GHAW compilation layer, satisfying the user's request and aligning with the Infrahub precedent at the workflow-source level.
  - The `.md` + `.lock.yml` pair is a familiar "source + build artifact" model; the operational gap (drift) is minimised in HYBRID mode because the `.md` body is one stable line.
- **Alternatives considered**:
  - **Full Infrahub-style** (agent prompt in `.md`): rejected as above.
  - **No GHAW** (keep hand-authored `.yml`): rejected by user request.
  - **GHAW for one stage as a pilot, hand-authored for the others**: rejected — inconsistent surface; not worth the irregularity for a 4-file change.
- **Tooling**: `gh extension install github/gh-aw` (one-time per contributor machine). Required only for editing workflow sources; CI consumes the committed `.lock.yml`.

## R12. Drift policy v1 — added 2026-05-09

- **Decision**: Drift between `.md` source and `.lock.yml` artifact is **manually managed** in v1. Contributors run `gh aw compile` before committing changes to a workflow `.md`; the developer guide (FR-027) documents this requirement.
- **Rationale**:
  - In HYBRID mode the `.md` body is a one-line slash-command invocation. Post-creation churn is minimal — there is little surface for drift to creep in.
  - A CI drift-check (`gh aw compile --check` or equivalent) requires `gh aw` on the runner. The project does not currently install `gh` extensions in CI; adding that pipeline plumbing is out of scope for v1.
  - A pre-commit hook running `gh aw compile --check` is a possible v2 — pre-commit already runs `prek` for project hooks; adding one more is cheap once the team agrees to require `gh aw` on every contributor's machine.
- **Follow-up trigger**: if drift bites in practice (a contributor edits a `.md` and forgets to recompile, breaking the workflow), open a follow-up to add either the pre-commit hook or a CI check.

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
