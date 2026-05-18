# Phase 0 — Research

## R1. Hook runner: prek (only)

**Decision**: Use `prek` as the sole runner, both locally and in CI. The config uses standard `.pre-commit-config.yaml` syntax with no prek-only extensions, so the format remains portable.

**Rationale**:
- `prek` is a Rust reimplementation of pre-commit with parallel hook execution and no per-hook Python virtualenv bootstrap, so the per-commit latency target (≤10 s) is realistic.
- One runner everywhere means no `_resolve_runner` branching, no version-skew between two implementations, and one fewer dev dependency.
- For this team the inclusion concern (contributors who can't install Rust binaries) is theoretical; the cost of dual-runner support is real.

**Initial draft and reversal**: An earlier version of this research supported `pre-commit` (Python) as an interchangeable fallback. The reversal is documented in ADR-007; the spec's FR-006/FR-009 reflect the final decision.

**Alternatives considered**:
- *Dual-runner support (prek + pre-commit)*: rejected on simplicity grounds. Documented in ADR-007.
- *pre-commit only*: rejected — too slow per-commit; defeats the "fast feedback" motivation of the feature.
- *Custom invoke script that wraps the same checks*: rejected — duplicates the declarative config that prek already provides; we'd lose the published-hook ecosystem (e.g., `pre-commit-hooks` for hygiene checks).

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

## R4. CI installation: `prek` via the upstream installer script

**Decision**: CI installs `prek` by piping the upstream `prek-installer.sh` (pinned to a tagged release) into `sh`, then prepends `$HOME/.local/bin` to `GITHUB_PATH`. The job runs `prek run --all-files` for both stages.

**Rationale**:
- Using the same runner in CI as locally means CI exercises the exact path contributors hit, and parity is by construction.
- The installer script is the upstream-blessed, platform-aware install path. It auto-detects the runner's OS/arch and installs the appropriate binary. Pinning to a tagged release keeps the install reproducible.
- A third-party "setup-prek" GitHub Action would be cleaner cosmetically, but no such action is published (`j178/setup-prek` does not exist as of 2026-05-01). Inline `curl | sh` is the next-best option and keeps the supply-chain surface small.

**Alternatives considered**:
- *Hypothetical `j178/setup-prek` action*: would have been preferred for ergonomics; rejected on the simple basis that it does not exist. If it ships in the future, switching is a one-line change.
- *Manual `curl` of the architecture-specific tarball + `tar -xzf`*: more YAML and brittle (we'd hardcode the runner architecture); rejected.
- *Use `pre-commit` (Python) on CI as a fallback*: rejected — see R1.

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

- `pre-commit-install` — installs git hooks for both the `pre-commit` and `pre-push` stages. Shells out to `prek install` (which honours `default_install_hook_types: [pre-commit, pre-push]` from the YAML).
- `pre-commit-run` — runs all hooks against all files. Shells out to `prek run --all-files`.

**Rationale**: Mirrors the existing `format` / `lint` task pattern (one verb, one entry point). The wrapper short-circuits with a clear install hint if `prek` is missing, keeping the failure mode obvious instead of cryptic.

**Alternatives considered**:
- *Single `pre-commit` task with subcommands*: invoke doesn't model subcommands as cleanly as separate `@task` entries; reject for consistency with rest of `tasks/`.

## R8. Bypass policy

**Decision**: Document `git commit --no-verify` in `AGENTS.md` and the new `dev/guides/pre-commit-hooks.md`. Acceptable use cases: (a) emergency hotfix when network is down and a hook needs network; (b) WIP commits on a personal branch that will be squashed; (c) intentional commits to `develop`/`stable` from automation that already validated. Not acceptable: routine "skip lint" commits — those should be fixed before commit.

**Rationale**: Bypass is a safety valve. We don't try to block it; we instead document when it's the right tool.

## R9. Dedupe vs parity-validation period

**Decision**: Run both layers (per-tool jobs + hook job) for one CI cycle on this PR to validate parity, then remove the per-tool jobs that the hook job fully subsumes in the same PR. The single observed parity run is judged sufficient — the hook job invokes the same underlying tools (`ruff`, `ty`, `yamllint`, `rumdl`, `pnpm lint`, `helm lint`, `validate-graphql`, `ariadne-codegen`, `pnpm codegen`) that the per-tool jobs invoked, so any divergence would be a CLI-flag-level bug, not a semantic one.

**Rationale**: A multi-week parity-validation period was initially planned (see ADR-007's "Alternatives Considered"). On reflection: the duplicate-CI cost (multiple Python+uv+pnpm setups, repeated lints) outweighs the marginal insurance, and reverting the dedupe is a single-revert operation if a regression surfaces.

## R10. Markdown linter

**Decision**: Use the project's existing `rumdl` (already pinned via `pyproject.toml` dependency group) as the markdown lint hook. The original issue mentions "markdownlint" as an example category — `rumdl` is the project's chosen tool.

**Rationale**: Switching markdown linters is out of scope; the goal is to enforce the existing CI behaviour locally, not to change which tool runs.
