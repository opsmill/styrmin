# Implementation Plan: Pre-Commit Hooks via prek

**Branch**: `006-prek-pre-commit-hooks` | **Date**: 2026-05-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/006-prek-pre-commit-hooks/spec.md`

## Summary

Add a `.pre-commit-config.yaml` at the repo root and adopt `prek` as the sole runner (locally and in CI) to run the project's mandatory checks before each commit. Wire the hook config into the existing CI workflow as a new dedicated job, keep the existing per-tool jobs in place for parity validation, and expose installation/run wrappers via `invoke` so onboarding stays a single command. Slow checks (GraphQL schema freshness, generated-type freshness) are gated to `pre-push` so per-commit latency stays under the 10-second target.

## Technical Context

**Language/Version**: Python 3.14 (managed by uv); TypeScript via pnpm (frontend); YAML (hook config + CI)
**Primary Dependencies**: `prek` (Rust binary) as the sole hook runner; existing tools — `ruff`, `ty`, `yamllint`, `rumdl` (the project uses rumdl for markdown, not markdownlint, per `tasks/format.py:55-58` and `.github/workflows/ci.yml:168-169`), `pnpm lint` (ESLint + Prettier), `helm lint`, `uv run invoke validate-graphql`, `uv run styrmin export graphql-schema`, `ariadne-codegen` + `pnpm codegen`
**Storage**: N/A — all state is files committed to the repo (`.pre-commit-config.yaml`, invoke task additions, CI workflow update, AGENTS.md edits)
**Testing**: CI job `prek run --all-files` on every PR is the E2E test for this feature (proves hooks resolve, install, and execute against the real repo). The existing per-tool CI jobs continue to provide independent coverage of each underlying linter. No new pytest/Vitest tests are added — this is a build/dev-tooling feature with no production runtime surface.
**Target Platform**: Local developer machines (macOS/Linux) and the GitHub Actions Ubuntu runner used by CI
**Project Type**: Build/dev-tooling (single declarative config + thin invoke wrappers + CI job + docs)
**Performance Goals**: A clean commit on a typical change runs all configured pre-commit hooks in under 10 seconds on a warm cache (per spec SC-003). The CI hook job completes within a comparable budget to the slowest existing per-tool job.
**Constraints**: Hook config MUST use only standard `.pre-commit-config.yaml` syntax (no prek-only extensions) to keep the format portable. Generated directories MUST NOT be linted. Must not regress any existing CI signal — keep the per-tool jobs in place for at least one release cycle (per spec FR-013).
**Scale/Scope**: ~1 new top-level YAML file, ~1 new CI job, ~2 new invoke tasks, ~30–50 lines of AGENTS.md additions, 1 new dev guide page.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / Gate | Status | Notes |
|---|---|---|
| I. Declarative State Reconciliation | N/A | Feature does not touch deployment reconciliation. |
| II. Driver-Based Deployment | N/A | Feature does not introduce or modify drivers. |
| III. Layered Architecture | N/A | Feature does not introduce code that crosses GraphQL → Service → Repository layers. |
| IV. Type Safety and Typed Errors | PASS | Any new Python in `tasks/` will be type-annotated and pass `ty`. |
| V. Test-First Development (E2E required) | PASS *with caveat* | This is a build/dev-tooling feature with no runtime surface. The constitution's E2E requirement is most naturally satisfied here by the CI job that runs `prek run --all-files` on every PR — that job *is* the end-to-end exercise of the hook config against the real repo. No Kind/vcluster E2E is meaningful for this feature. Per the constitution and AGENTS.md, this caveat is documented here for reviewer awareness; if a reviewer disagrees, the appropriate alternative is a small shell-level smoke test that intentionally violates one hook and asserts the runner exits non-zero. |
| VI. Format and Lint Before Commit | PASS | Feature *strengthens* this principle by enforcing it locally instead of only in CI. |
| Governance Gate: CI/CD workflow changes | ACK | This feature touches `.github/workflows/ci.yml`. The plan keeps the existing per-tool jobs in place and adds the hook job alongside, so signal cannot regress. |
| Governance Gate: New dependencies | ACK | `prek` is added as a new contributor and CI prerequisite, installed out-of-band (brew, release tarball, or `j178/setup-prek` action on CI). No new Python or JS package dependency is introduced. The issue explicitly authorises this. |

**Result**: PASS. No constitutional violations to justify. The Governance Gates ("CI/CD changes", "new dependencies") are acknowledged here and proceed under explicit user direction via issue #154.

## Project Structure

### Documentation (this feature)

```text
specs/006-prek-pre-commit-hooks/
├── plan.md              # This file
├── research.md          # Phase 0 — tool/runner/stage research
├── data-model.md        # Phase 1 — hook config entities
├── quickstart.md        # Phase 1 — contributor onboarding flow
├── contracts/
│   └── pre-commit-config.schema.md   # The hook config "contract" (file format + required fields)
└── tasks.md             # Generated by /speckit-tasks
```

### Source Code (repository root)

```text
.pre-commit-config.yaml                # NEW — single declarative source of truth for hooks

.github/workflows/
└── ci.yml                              # MODIFIED — add `pre-commit` job that runs prek/pre-commit run --all-files

tasks/
├── __init__.py                         # MODIFIED — register pre-commit-install / pre-commit-run tasks
└── pre_commit.py                       # NEW — invoke task wrappers that shell out to prek

AGENTS.md                               # MODIFIED — Always Do (install hooks); contributor bypass note

dev/guides/
└── pre-commit-hooks.md                 # NEW — full contributor-facing guide
```

**Structure Decision**: This is a repo-wide tooling feature. There is no new package or service to scaffold — only a config file, two invoke tasks, a CI job tweak, and documentation. No source code is added under `backend/` or `frontend/`.

## Complexity Tracking

> Constitution check passed without violations. No entries.
