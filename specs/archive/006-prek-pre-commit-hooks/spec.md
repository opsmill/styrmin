# Feature Specification: Pre-Commit Hooks via prek

**Feature Branch**: `006-prek-pre-commit-hooks`
**Created**: 2026-05-01
**Status**: Extracted
**Input**: GitHub issue [#154](https://github.com/opsmill/styrmin/issues/154) — Add pre-commit hooks (via prek) to enforce mandatory checks before commit

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Local hook enforcement on every commit (Priority: P1)

A contributor edits Python, frontend, or YAML files and runs `git commit`. Before the commit is created, fast lint and format checks run automatically and either pass or fail the commit. The contributor catches issues in seconds instead of waiting for CI.

**Why this priority**: This is the core value of the feature — eliminating the multi-minute CI round-trip for the most common class of failures (formatting, lint, hygiene). Without it, none of the other goals are reachable.

**Independent Test**: Install hooks on a fresh clone, deliberately introduce a `ruff` formatting violation, attempt `git commit`, and confirm the commit is blocked with a clear failure pointing to the offending file. Fix the violation and confirm the commit succeeds.

**Acceptance Scenarios**:

1. **Given** a contributor has installed the hooks, **When** they commit a Python file with a formatting error, **Then** the commit is rejected with a `ruff format` failure message.
2. **Given** a contributor has installed the hooks, **When** they commit a clean change, **Then** all hooks complete in under 10 seconds combined and the commit proceeds.
3. **Given** a contributor stages a YAML file with invalid syntax, **When** they commit, **Then** `yamllint` blocks the commit and reports the line number.
4. **Given** a contributor commits a Markdown file, **When** the file violates the project's markdown rules, **Then** `markdownlint` blocks the commit.
5. **Given** a contributor edits a `.graphql` file, **When** they commit, **Then** `validate-graphql` runs against the change and blocks invalid syntax or schema violations.

---

### User Story 3 — CI parity job that runs the same hooks (Priority: P2)

The CI pipeline runs `prek run --all-files` on every PR, so the hook config itself is enforced and stays in sync with whatever local contributors run.

**Why this priority**: This protects against drift — a contributor who skips hooks (legitimately or with `--no-verify`) still hits the same checks in CI, and the hook config can't silently rot. P2 because the existing per-tool CI jobs already provide coverage; this job adds belt-and-suspenders enforcement and is what allows us to dedupe later.

**Independent Test**: Open a PR that disables a hook locally and pushes a violation. Confirm the CI hook job fails with the same message a contributor would have seen locally.

**Acceptance Scenarios**:

1. **Given** a PR contains a file that violates a configured hook, **When** CI runs, **Then** the pre-commit CI job fails and surfaces the same hook output a local run would produce.
2. **Given** the per-tool CI jobs all pass, **When** the pre-commit CI job runs, **Then** it also passes (no drift between the two enforcement layers).
3. **Given** the pre-commit CI job runs, **When** the cache is warm, **Then** it completes within a comparable time budget to the existing slowest individual lint job.

---

### User Story 4 — Onboarding via a single invoke task (Priority: P2)

A new contributor clones the repo and runs `uv run invoke pre-commit-install` (or equivalent). Hooks are installed in their local clone and they're ready to commit compliant changes.

**Why this priority**: We already standardize developer commands behind `invoke` tasks, so wrapping pre-commit installation in the same pattern keeps the onboarding doc trivially short ("run this one command"). P2 because the underlying `prek install`/`pre-commit install` is already a single command — the wrapper is convenience, not a blocker.

**Independent Test**: On a fresh clone with no hooks installed, run the new invoke task and confirm `git commit` invokes the hooks.

**Acceptance Scenarios**:

1. **Given** a fresh clone, **When** a contributor runs the install task, **Then** the git hook is created and subsequent commits trigger the configured checks.
2. **Given** a contributor wants to manually run all hooks against the whole repo, **When** they run the corresponding invoke task, **Then** every hook executes against every relevant file.

---

### User Story 5 — Slow checks gated to pre-push or manual stages (Priority: P3)

Expensive checks (full GraphQL schema regeneration, full SDK + frontend type regeneration) run at `pre-push` or `manual` rather than every commit, so pre-commit stays under the "feels instant" bar.

**Why this priority**: Without this gating, a slow check on every commit would push contributors to bypass hooks. P3 because the project's only truly slow checks are well-understood and can be added under the right stage from day one — it's a design choice, not extra work.

**Independent Test**: Commit a change that touches a `.graphql` file and confirm only fast checks run on commit. Run `git push` (or invoke the pre-push stage manually) and confirm the schema/type freshness check fires.

**Acceptance Scenarios**:

1. **Given** a contributor commits a change to a `.graphql` query, **When** the commit hook runs, **Then** the lightweight `validate-graphql` runs but the full SDK/frontend regeneration check does not.
2. **Given** a contributor pushes the same change, **When** the pre-push stage runs, **Then** the schema/type freshness check runs and blocks the push if generated artifacts are stale.

---

### Edge Cases

- **Bypassing hooks for emergencies**: How does a contributor bypass the hooks (e.g., committing during an outage when the network is down and a hook needs network)? Documentation must explain `git commit --no-verify` and when it's appropriate (rare, well-justified).
- **First-run dependency bootstrap**: What happens the first time a contributor runs hooks on a clone where `uv sync` has not yet been performed? Hooks that shell out to `uv run …` will fail; the install task or onboarding doc must make `uv sync` a prerequisite.
- **Hook needs a tool not on PATH**: A contributor without `pnpm`, `helm`, `markdownlint-cli`, or `yamllint` installed should get a clear error pointing to the install instructions, not a cryptic "command not found".
- **CI cache miss on the pre-commit hook environment**: If the cache is cold, the CI hook job should still complete within a reasonable budget (no worse than running each tool independently in CI).
- **Files outside the configured `files:` patterns**: A renamed or moved file that crosses an `exclude` boundary should still be checked correctly by the appropriate hook on its new path.
- **Generated files**: The repo contains generated files (e.g., `python_sdk/src/styrmin_sdk/graphql/_generated/`, frontend GraphQL types) that must NOT be reformatted or linted by the hooks.
- **Drift between hook job and per-tool CI jobs**: If the per-tool CI jobs and the hook job disagree (one passes, the other fails), this drift must be visible and fixable, not silently tolerated.

## Requirements *(mandatory)*

### Functional Requirements

#### Hook configuration

- **FR-001**: The repository MUST contain a `.pre-commit-config.yaml` at the root that defines all mandatory pre-commit and pre-push hooks for the project.
- **FR-002**: The hook config MUST cover every mandatory check currently enforced in `.github/workflows/ci.yml`: Python format check (`ruff format --check`), Python lint (`ruff check`), Python type check (`ty`), YAML lint (`yamllint`), Markdown lint (the project uses `rumdl`), frontend lint (ESLint/Prettier via `pnpm lint`), GraphQL operations validation (`uv run invoke validate-graphql`), GraphQL schema freshness (`schema.graphql` matches `styrmin export graphql-schema`), generated SDK + frontend type freshness, and Helm chart lint.
- **FR-003**: The hook config MUST include standard hygiene hooks: trailing-whitespace, end-of-file-fixer, large-files guard, merge-conflict marker detection, and a basic secrets scan.
- **FR-004**: Every hook MUST be scoped via `files:` and/or `exclude:` patterns so it runs only on files it can meaningfully check (e.g., Python hooks skip frontend files, frontend lint skips Python files, generated directories are excluded).
- **FR-005**: Hooks whose runtime exceeds an acceptable per-commit budget — specifically the GraphQL schema freshness check and the generated-type freshness check — MUST be assigned to `stages: [pre-push]` (or `manual`) so they do not run on every commit.
- **FR-006**: The hook config MUST use only standard `.pre-commit-config.yaml` syntax (no prek-only extensions). This keeps the format portable in case the project ever revisits the runner choice.

#### Tooling and onboarding

- **FR-007**: An invoke task MUST exist to install the git hooks (e.g., `uv run invoke pre-commit-install`) and another to run them against all files (e.g., `uv run invoke pre-commit-run`).
- **FR-008**: The invoke install task MUST install hooks for every relevant stage (`pre-commit` and `pre-push`).
- **FR-009**: The invoke tasks MUST shell out to `prek`. If `prek` is not on PATH, the task MUST fail fast with a clear pointer to install instructions (no silent fallback).
- **FR-010**: `AGENTS.md` MUST be updated so the "Always Do" section instructs contributors to install hooks once after cloning, and a contributor-facing note MUST describe how (and when) to bypass hooks via `git commit --no-verify`.

#### CI integration

- **FR-011**: A new CI job MUST run `prek run --all-files` on every pull request, for both the `pre-commit` and `pre-push` stages.
- **FR-012**: The pre-commit CI job MUST fail the PR check suite if any hook fails.
- **FR-013**: The pre-commit CI job is the canonical lint/format/freshness gate for the repo. Per-tool CI jobs that the hook job fully subsumes (`python-lint`, `yaml-lint`, `markdown-lint`, `frontend-lint`, `helm-lint`, `graphql-schema-check`, `graphql-operations-check`, `sdk-codegen-check`, `frontend-codegen-check`) MUST be removed; downstream jobs (`unit-tests`, `frontend-test`, `frontend-build`, `e2e-tests-*`) MUST `needs:` the hook job instead.
- **FR-014**: The pre-commit CI job MUST cache hook environments between runs so cold-start cost is paid at most once per dependency change.

#### Behavior on bypass and failure

- **FR-015**: When a hook fails, the failure output MUST clearly identify the file(s) involved and the reason, so the contributor can fix without re-reading the hook config.
- **FR-016**: A contributor MUST be able to bypass hooks with `git commit --no-verify` for emergency commits; this path is intentionally not blocked, but the project documents the expected (rare) use cases.

### Key Entities

- **`.pre-commit-config.yaml`**: The single declarative source of truth for what "clean" means. Each entry pairs a hook id (from a published or local repo) with file globs, excludes, optional args, and a stage.
- **Mandatory check set**: The list of checks the project considers blocking — currently encoded across CI jobs and the `lint` invoke task. After this feature ships, the hook config is the canonical list and CI/invoke must agree with it.
- **Hook stage (`pre-commit` vs `pre-push` vs `manual`)**: The lifecycle gate at which a hook fires. Fast hooks fire on commit; slow hooks fire on push or only when explicitly invoked.
- **Hook runner (`prek`)**: The tool that interprets the config and executes hooks. Required on every contributor's machine and on the CI runner.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this feature ships, the rate of CI runs that fail purely on the checks now covered by hooks (formatting, lint, yaml-lint, markdown-lint, GraphQL validation, frontend lint) drops by at least 75% on the `develop` branch over the following month, measured against the prior month.
- **SC-002**: A new contributor can go from `git clone` to "ready to commit compliant code" in a single documented command, taking under 60 seconds on a warm machine (excluding `uv sync` and `pnpm install` time).
- **SC-003**: A clean `git commit` on a typical change runs all configured pre-commit hooks in under 10 seconds on a warm cache.
- **SC-004**: The pre-commit CI job is the only enforcement gate for the checks it covers; no per-tool CI duplicates remain. Any regression in coverage (a check that previously failed CI but now passes) is treated as a bug and fixed.
- **SC-005**: The number of "fix lint" / "fix format" follow-up commits merged into `develop` drops by at least 50% in the month after rollout, measured against the prior month.

## Assumptions

- Contributors already have `uv` and `pnpm` installed (these are existing project prerequisites). `prek` is added as a new prerequisite, installed out-of-band via `brew`, the project's release tarball, or a distro package.
- The CI runner installs `prek` by piping the upstream `prek-installer.sh` (pinned to a tagged release) into `sh`.
- Generated directories (`python_sdk/src/styrmin_sdk/graphql/_generated/`, frontend GraphQL generated types, build artifacts) are well-known and stable enough to add to `exclude` patterns up front.
- The per-tool CI jobs that the hook job fully subsumes are removed in the same change. Parity is validated by running the hook job on this PR alongside the prior per-tool jobs (one CI run is judged sufficient given the small, additive nature of the change).
- The acceptable per-commit time budget is "fast enough that contributors do not routinely use `--no-verify`". Ten seconds is the working target; checks that exceed this go to `pre-push`.
- Helm lint applies only when `helm/**` files change; other contributors should not need Helm installed locally.
- The `ty` type checker is already an established part of the project's mandatory check set per `AGENTS.md` and is fast enough to run on every commit when scoped to changed files.
