# Phase 0 — Research

## R1. Hook runner: prek vs pre-commit

**Decision**: Use `prek` as the **recommended** runner; support `pre-commit` (upstream Python tool) as an officially-tested fallback. The hook config format is a strict subset that works on both.

**Rationale**:
- `prek` is a drop-in reimplementation in Rust with parallel hook execution and no per-hook Python virtualenv bootstrap, so the per-commit latency target (≤10 s) is realistic.
- The config syntax is identical, so there is no lock-in.
- Some contributors (corporate machines, restricted shells) will not be able to install `prek`. Falling back to `pre-commit` keeps them productive.
- CI uses `pre-commit` (installed via `uv`) for reproducibility — `prek` requires fetching a binary from GitHub releases, which adds a network failure mode we don't need on the runner. Local users benefit from the speed; CI is not latency-sensitive.

**Alternatives considered**:
- *prek only*: rejected — locks out contributors who can't install Rust binaries.
- *pre-commit only*: rejected — too slow per-commit; defeats the "fast feedback" motivation of the feature.
- *Custom invoke script that wraps the same checks*: rejected — duplicates the declarative config that pre-commit / prek already provide; we'd lose the published-hook ecosystem (e.g., `pre-commit-hooks` for hygiene checks).

## R2. Which hooks to enable, and at which stage

**Decision**:

| Hook | Source | Stage | Rationale |
|---|---|---|---|
| `ruff format --check` | local (`ruff` CLI) | `pre-commit` | <1 s on changed files; matches CI `python-lint` job. |
| `ruff check` | local | `pre-commit` | Same. |
| `ty check` | local | `pre-commit` | Project's authoritative type checker; fast enough on warm cache. Constitution §IV makes this mandatory. |
| `yamllint` | local | `pre-commit` | Matches CI `yaml-lint` job. |
| `rumdl check` | local | `pre-commit` | Matches CI `markdown-lint` job. (Note: project uses `rumdl`, not `markdownlint` — see `tasks/format.py` and `ci.yml:168`.) |
| `pnpm lint` (ESLint + Prettier) | local | `pre-commit` | Matches CI `frontend-lint`. Scoped to `frontend/**`. |
| `uv run invoke validate-graphql` | local | `pre-commit` | Matches CI `graphql-operations-check`. Fast. |
| `helm lint ./helm/agent` and `./helm/styrmin` | local | `pre-commit` | Matches CI `helm-lint`. Only runs when `helm/**` files change. |
| GraphQL schema freshness (`styrmin export graphql-schema` diff) | local | `pre-push` | Slow (loads the whole backend). Fits "ack you can break this" but CI catches it. |
| Generated SDK + frontend types freshness (`ariadne-codegen` + `pnpm codegen` diff) | local | `pre-push` | Same — slow. |
| `trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files` | `pre-commit-hooks` repo | `pre-commit` | Standard hygiene, near-instant. |
| `detect-private-key` | `pre-commit-hooks` repo | `pre-commit` | Cheap secrets-scan baseline. (A future iteration could swap in `gitleaks` if we want broader coverage.) |

**Rationale**: Anything that completes in well under a second on a typical change goes on `pre-commit`. Anything that materialises and diffs generated artefacts goes on `pre-push` so contributors don't pay the cost on every commit. CI still catches the slow checks via the existing per-tool jobs even if a contributor doesn't install the `pre-push` hook.

**Alternatives considered**:
- *All hooks on `pre-commit`*: rejected — would push contributors toward `--no-verify`.
- *All hooks on `pre-push` only*: rejected — defeats the "fast local feedback before commit" goal of the feature.
- *Fancier secret-scanner (gitleaks, trufflehog) at install time*: deferred — `detect-private-key` covers the obvious failure mode (committed SSH/PEM keys). A heavier scanner is a follow-up.

## R3. Pinning hook versions

**Decision**: Pin every external `repo` entry in `.pre-commit-config.yaml` to a specific tag (`rev: v0.7.4` style). Local hooks (`repo: local`) reference the project's existing tooling, which is already pinned via `pyproject.toml` / `frontend/package.json`.

**Rationale**: Floating refs (`HEAD`, branch names) create flake — a contributor who runs `prek install` on Tuesday and `prek run` on Friday could see different behaviour. Pinning makes the hook config reproducible alongside the rest of the lockfile-driven repo.

**Alternatives considered**:
- *No pinning*: rejected — non-reproducible builds.
- *Pin via `pre-commit autoupdate` cron*: deferred to a follow-up. We can add a routine later that bumps the pins via PR.

## R4. CI installation: `pre-commit` via uv vs `prek` binary

**Decision**: CI installs `pre-commit` from `[dependency-groups].dev` via `uv sync` (same path as the existing per-tool jobs use to get `ruff`/`yamllint`/`rumdl`). The CI job runs `uv run pre-commit run --all-files`.

**Rationale**:
- `uv sync` is already on the critical path of every CI job that needs Python tools — adding `pre-commit` to the dev group costs ~zero extra time.
- Using `pre-commit` (not `prek`) on CI means we test the Python runner — the *fallback* path. If `pre-commit` works, `prek` (which is a drop-in clone of the same config grammar) will also work for any contributor who chooses it locally.
- We avoid an extra "fetch GitHub release of prek" step that could fail in restricted runner environments.

**Alternatives considered**:
- *Install `prek` on CI*: rejected — adds a moving piece (binary fetch from GitHub releases) without measurable benefit on a runner that runs once and is throwaway.
- *Use the official `pre-commit/action` GitHub Action*: rejected — we already have `uv sync` running; adding a third-party action is unnecessary surface.

## R5. Caching the pre-commit environment in CI

**Decision**: Cache `~/.cache/pre-commit` keyed on a hash of `.pre-commit-config.yaml` using `actions/cache@v4`. This mirrors the standard pattern documented by `pre-commit.com`.

**Rationale**: Pre-commit's cold start (cloning each hook repo, building venvs) is the slowest part of the runner. Caching makes warm-cache runs feel instant.

**Alternatives considered**:
- *No cache*: rejected — turns a sub-second job into a 30+ second one.
- *Self-hosted cache server*: out of scope for this feature.

## R6. Excluding generated files

**Decision**: Add a top-level `exclude:` regex to `.pre-commit-config.yaml` that covers known generated paths:

- `^python_sdk/src/styrmin_sdk/graphql/_generated/`
- `^frontend/src/.*\.generated\.ts$` (and any matching frontend codegen output paths)
- `^.*/__pycache__/`
- `^.*\.lock$` and `^pnpm-lock\.yaml$` (lockfiles)
- `^schema\.graphql$` (regenerated artefact, not hand-edited)

**Rationale**: Linting generated files creates spurious failures and drives contributors to `--no-verify`. Excluding them at the config level is simpler than per-hook excludes.

**Alternatives considered**:
- *Per-hook `exclude:` patterns only*: rejected — duplicates the same regex across many hooks and is error-prone to keep in sync.

## R7. Invoke task surface

**Decision**: Add two tasks under the new `tasks/pre_commit.py` module:

- `pre-commit-install` — installs git hooks for both the `pre-commit` and `pre-push` stages. Tries `prek install --hook-type pre-commit --hook-type pre-push` first; falls back to `uv run pre-commit install --hook-type pre-commit --hook-type pre-push`.
- `pre-commit-run` — runs all hooks against all files. Tries `prek run --all-files` first; falls back to `uv run pre-commit run --all-files`.

**Rationale**: Mirrors the existing `format` / `lint` task pattern (one verb, one entry point). Auto-detecting `prek` keeps power users on the fast path without forcing it.

**Alternatives considered**:
- *Single `pre-commit` task with subcommands*: invoke doesn't model subcommands as cleanly as separate `@task` entries; reject for consistency with rest of `tasks/`.

## R8. Bypass policy

**Decision**: Document `git commit --no-verify` in `AGENTS.md` and the new `dev/guides/pre-commit-hooks.md`. Acceptable use cases: (a) emergency hotfix when network is down and a hook needs network; (b) WIP commits on a personal branch that will be squashed; (c) intentional commits to `develop`/`stable` from automation that already validated. Not acceptable: routine "skip lint" commits — those should be fixed before commit.

**Rationale**: Bypass is a safety valve. We don't try to block it; we instead document when it's the right tool.

## R9. Drift between hook job and per-tool jobs

**Decision**: Keep both for at least one release cycle. After a month of clean parity (per spec SC-004), we open a follow-up PR to remove the per-tool jobs that the hook job has fully subsumed. The CI job names match the underlying tool ("Pre-Commit Hooks") so it's obvious from the check list when both pass.

**Rationale**: The cost of running the hook job alongside is small; the cost of accidentally deleting CI signal is large.

## R10. Markdown linter

**Decision**: Use the project's existing `rumdl` (already pinned via `pyproject.toml` dependency group) as the markdown lint hook. The original issue mentions "markdownlint" as an example category — `rumdl` is the project's chosen tool.

**Rationale**: Switching markdown linters is out of scope; the goal is to enforce the existing CI behaviour locally, not to change which tool runs.
