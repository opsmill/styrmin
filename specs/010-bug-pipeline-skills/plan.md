# Implementation Plan: Bug-Fixing Pipeline as Skills with GHAW Thin Wrappers

**Branch**: `010-bug-pipeline-skills` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/010-bug-pipeline-skills/spec.md`

## Summary

Ship four standalone Claude Code skills under `.agents/skills/` — `bug-analyze`, `bug-fix`, `bug-test`, `bug-review` — that implement a four-stage AI bug-fixing pipeline. Each skill is independently runnable from the local CLI and from a corresponding GitHub Actions workflow under `.github/workflows/bug-agent-*.yml` that does nothing except check out the repo and call `anthropics/claude-code-action@v1` with `prompt: '/bug-* …'`. Stages chain via a hybrid model: every stage is human-triggered by a slash-command comment, and a successful stage suggests the next command in its output comment. Inter-stage data flows through a fenced YAML "machine-readable summary" block in the analyst's issue comment, which the fix stage and (transitively) the test/review stages consume.

## Technical Context

**Language/Version**: Skill content is markdown with YAML frontmatter (Claude Code skill format). Workflow files are GitHub Actions YAML. No new Python helpers are introduced — argument normalisation, comment formatting, and branch naming are described as instruction text inside each `SKILL.md` and executed by the Claude Code agent at runtime via `gh` CLI, `git`, and standard shell commands.
**Primary Dependencies**:
- `gh` CLI (already in CI; assumed authenticated for local CLI runs)
- `git` (standard)
- `anthropics/claude-code-action@v1` (already used by `.github/workflows/claude.yml`)
- **`gh aw` GitHub CLI extension** (`gh extension install github/gh-aw`) — added by Iteration 2026-05-09 for GHAW adoption. Required on contributor machines that edit workflow `.md` sources; the `.lock.yml` artifacts are committed so CI runners do not need it.
- Project formatting/linting: `uv run invoke format lint` (existing)
- Existing project test command (existing)
**Storage**: None. All durable state lives in GitHub (issue comments, branches, PRs).
**Testing**:
- `yamllint` over the four new workflow files (project's existing YAML linter; runs in `prek` pre-commit + CI). The source PRD mentioned `actionlint` / `.github/actionlint.yaml`, but the project does not currently configure actionlint — `yamllint` is the active enforcement. We do **not** introduce actionlint as part of this feature.
- Skill `SKILL.md` files render correctly under the existing `rumdl` markdown lint — but `.agents/` is excluded from pre-commit by design, so this is a manual check, not an automated gate.
- Manual smoke test on a sandbox issue, documented in `quickstart.md`, exercising each stage end-to-end.
- See **Constitution Check / Principle V** below for the E2E deviation that requires human confirmation.
**Target Platform**:
- Local: macOS / Linux running Claude Code CLI
- CI: `ubuntu-latest` GitHub-hosted runner (matches `claude.yml`)
**Project Type**: Meta-tooling (developer-facing automation; no application code, no GraphQL schema change, no database).
**Performance Goals**: N/A. End-to-end stage runtime is bounded by Claude Code action runtime (a few minutes on average, dominated by LLM calls); no project-side optimisation is required.
**Constraints**:
- FR-024: workflow YAML may contain only checkout + permissions + a single skill invocation. No agent prompt, branch logic, or comment-formatting logic in YAML.
- FR-002: each skill `SKILL.md` is self-contained; no fifth "shared" skill is introduced (would couple the four skills and defeat self-containment).
- FR-003: skills delegate project-conventions reading to the existing `AGENTS.md` files; they do not duplicate that content.
**Scale/Scope**: 4 skill directories, 4 workflow files, 1 developer guide, 2 contract documents under `specs/`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Notes |
|-----------|---------|-------|
| I. Declarative State Reconciliation | N/A | Feature does not touch deployment reconciliation. |
| II. Driver-Based Deployment | N/A | No driver changes. |
| III. Layered Architecture | N/A | No backend code changes; no GraphQL → service → repository flow involved. |
| IV. Type Safety and Typed Errors | N/A | No new Python code. If a future iteration adds a Python helper for parsing the analyst summary, type hints + ty enforcement apply automatically via existing pre-commit. |
| V. Test-First Development (E2E + GraphQL propagation) | ⚠️ **Deviation** — see Complexity Tracking | No GraphQL schema change → no propagation test required. The E2E rule applies because this is a new feature, but the project's E2E suite (`backend/tests/e2e/`) targets the deployment platform on a real vcluster and is not a fit for skills that produce GitHub side effects. We propose a manual smoke-test procedure and `yamllint` automation in lieu of a pytest E2E. The constitution requires explicit reviewer confirmation for this kind of deviation; that confirmation must be obtained during Phase 3 (critique) or before implementation begins. |
| VI. Format and Lint Before Commit | ✅ | `uv run invoke format lint` is unaffected by this feature (no Python touched). `yamllint` runs against new workflow files via existing pre-commit. `.agents/` is excluded from pre-commit by design, so skill markdown is hand-curated and reviewed in PR. |

### Governance Gates

- **CI/CD workflow changes**: requires explicit discussion. The four new workflow files are part of the in-scope spec; the user has already approved this scope by opening issue #206 and supplying the PRD. We do **not** modify existing workflows (`claude.yml`, `ci.yml`, etc.).
- **Authentication/authorization**: no changes. New workflows reuse the existing `ANTHROPIC_API_KEY` secret already configured for `claude.yml`.
- **New dependencies**: `gh aw` GitHub CLI extension added by Iteration 2026-05-09 (HYBRID-mode GHAW adoption). User explicitly authorised this dependency in the iteration request. `anthropics/claude-code-action@v1`, `gh`, `git`, and `actions/checkout` were already in use.

## Project Structure

### Documentation (this feature)

```text
specs/010-bug-pipeline-skills/
├── plan.md                      # This file
├── spec.md                      # Feature spec (Phase 1 of speckit)
├── research.md                  # Phase 0 — design decisions & rationale
├── data-model.md                # Phase 1 — entities and the analyst-summary schema
├── quickstart.md                # Phase 1 — manual smoke-test walkthrough
├── contracts/
│   ├── analyst-summary-schema.md   # YAML schema for the machine-readable summary block
│   └── slash-command-protocol.md   # Comment-trigger contract for /bug-* commands
├── checklists/
│   └── requirements.md             # Spec quality checklist (created in Phase 1)
└── tasks.md                     # Phase 2 — created by /speckit-tasks (NOT this command)
```

### Source Code (repository root)

```text
.agents/skills/
├── bug-analyze/
│   └── SKILL.md
├── bug-fix/
│   └── SKILL.md
├── bug-test/
│   └── SKILL.md
└── bug-review/
    └── SKILL.md

.github/workflows/
├── bug-agent-analyst.md          # GHAW source (authored by hand)
├── bug-agent-analyst.lock.yml    # generated by `gh aw compile`
├── bug-agent-fix.md
├── bug-agent-fix.lock.yml
├── bug-agent-test.md
├── bug-agent-test.lock.yml
├── bug-agent-review.md
└── bug-agent-review.lock.yml

.yamllint.yml                     # excludes `.github/workflows/*.lock.yml` (FR-026)

dev/guides/
└── bug-pipeline.md              # FR-027 — how to invoke each stage from GitHub and the CLI; how to edit a workflow source (gh aw compile)
```

**Structure Decision**:
- Skills follow the **existing one-directory-per-skill convention** in `.agents/skills/` (cf. `create-issue/`, `pr/`, `dev-validate/`, `rebase/`).
- Each skill directory contains exactly one `SKILL.md` for v1. We do **not** introduce sub-files (assets, scripts) to keep the surface minimal; if shared instruction blocks become repetitive across skills, that refactor is deferred to a follow-up iteration.
- Workflow filenames mirror the source PRD (`bug-agent-<stage>`) so they are visually grouped in the `.github/workflows/` listing. As of Iteration 2026-05-09, each stage produces a `.md` source plus a `.lock.yml` build artifact, both committed.
- Each workflow source includes a `concurrency:` block keyed on the issue number to serialise same-stage invocations on the same issue (see `research.md` §R8). This is workflow orchestration, not agent logic, and remains FR-024-compliant.
- The `.lock.yml` files are excluded from `yamllint` because GHAW-compiled output embeds shell/JS that exceeds normal lint rules (mirrors `opsmill/infrahub#9043`). Exclusion lives in `.yamllint.yml`.
- Tests for this feature are **manual smoke tests + `yamllint`**, not pytest. Rationale documented under Complexity Tracking.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **No automated E2E test for this feature (Principle V deviation)** | The skills' user-visible flow is "type a slash command on a GitHub issue → side effect appears on GitHub". A faithful E2E test would need (a) a sandbox repo, (b) a valid `ANTHROPIC_API_KEY` available to test runners, and (c) the willingness to consume LLM credits on every CI run. Each of those is an operationally significant choice. | A pytest E2E that mocks `gh`, `git`, and the LLM would test argument-routing logic (which is trivial) without testing the actual integration the user cares about — the same critique the source PRD levels at the existing Infrahub pipeline ("buried in CI, can't run locally"). A manual smoke-test procedure documented in `quickstart.md` is the most honest substitute for v1, and it preserves the option to add a real CI E2E in a follow-up once the team agrees on infrastructure. **Per Constitution §V this deviation requires explicit reviewer confirmation before implementation.** |
