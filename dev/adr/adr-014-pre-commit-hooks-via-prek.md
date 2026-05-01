# ADR-014: Pre-Commit Hooks via prek

**Status**: Accepted
**Date**: 2026-05-01
**Source**: specs/006-prek-pre-commit-hooks/, GitHub issue [#154](https://github.com/opsmill/styrmin/issues/154)

## Context

The project's mandatory checks (ruff format/check, ty, yamllint, rumdl, frontend ESLint/Prettier, GraphQL operation validation, schema and generated-type freshness, helm chart lint) were enforced only in CI. Contributors regularly pushed commits that failed one of these checks, then waited several minutes for the CI round-trip. This was slow, wasted CI minutes on issues a 2-second local check would have caught, and produced "fix lint" follow-up commits cluttering the history.

A standard local-enforcement layer was needed. The pre-commit ecosystem (config format, hook ecosystem, language-aware envs) is the obvious choice and is already a community standard. The remaining decision was whether to use `prek` (Rust reimplementation) or upstream `pre-commit` (Python).

## Decision

Adopt a single `.pre-commit-config.yaml` at the repo root that works with **both** runners:

1. **`prek` is the recommended local runner.** It is faster (parallel execution, no per-hook Python virtualenv bootstrap), so a clean commit fits comfortably under the 10-second target on a warm cache. The config is a strict subset that uses no prek-only extensions.
2. **`pre-commit` is the supported fallback.** It is added to `[dependency-groups].dev` in `pyproject.toml`, so contributors who can't install `prek` (or don't want to) get the same enforcement via `uv run pre-commit`.
3. **CI uses `pre-commit` (the fallback) explicitly** in a new `pre-commit-hooks` job. CI is not latency-sensitive, and using the fallback runner means we test that path on every PR. The existing per-tool CI jobs are kept in place during a parity-validation period before any deduplication.
4. **Slow checks (GraphQL schema freshness, generated-type freshness) are gated to the `pre-push` stage** so per-commit latency stays under budget. CI still runs the equivalent per-tool jobs even if a contributor never installs the pre-push hook.
5. **An invoke task wrapper (`uv run invoke pre-commit-install` / `pre-commit-run`)** auto-detects the best available runner, keeping the onboarding command consistent with the rest of the project's invoke-driven workflow.

## Consequences

**Easier:**

- Lint and format failures surface in seconds locally instead of minutes in CI.
- A single declarative config (`.pre-commit-config.yaml`) is the source of truth for what "clean" means; CI and local agree by construction.
- Onboarding is one command (`uv run invoke pre-commit-install`).
- Contributors choose their runner without lock-in (prek for speed, pre-commit for portability).
- Reduces "fix lint" follow-up commits and the CI minutes they consume.

**Harder:**

- The hook config and the per-tool CI jobs run the same checks during the parity-validation period — this is intentional duplication, but it does cost a small amount of CI time. After a parity period, the per-tool jobs the hook job fully subsumes can be removed.
- Contributors must run `uv sync` and `pnpm install` before the hooks fire; otherwise hooks that shell out to `uv run …` or `pnpm` produce confusing "command not found" errors. Mitigated by the dev guide.
- Hook-version pins (`rev:` in `.pre-commit-config.yaml`) need periodic bumping; floating refs are forbidden, so this is a manual maintenance task (a future routine could automate it).

## Alternatives Considered

- **`prek` only**: Rejected — locks out contributors who can't install Rust binaries (corporate machines, restricted shells).
- **`pre-commit` only**: Rejected — too slow per-commit on a project with many hooks; would push contributors toward `git commit --no-verify`.
- **A custom invoke task that wraps each check**: Rejected — duplicates the declarative config that pre-commit / prek already provide and forfeits the published-hook ecosystem (e.g., the `pre-commit-hooks` repo for hygiene checks).
- **All hooks on `pre-commit` stage (no `pre-push` gating)**: Rejected — the GraphQL schema regen and generated-type regen each take several seconds and would push contributors toward bypass.
- **Drop the per-tool CI jobs immediately when the hook job lands**: Rejected — silent CI signal loss is a much larger risk than the small cost of running both jobs during the parity-validation period.
