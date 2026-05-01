# ADR-014: Pre-Commit Hooks via prek

**Status**: Accepted
**Date**: 2026-05-01
**Source**: specs/006-prek-pre-commit-hooks/, GitHub issue [#154](https://github.com/opsmill/styrmin/issues/154)

## Context

The project's mandatory checks (ruff format/check, ty, yamllint, rumdl, frontend ESLint/Prettier, GraphQL operation validation, schema and generated-type freshness, helm chart lint) were enforced only in CI. Contributors regularly pushed commits that failed one of these checks, then waited several minutes for the CI round-trip. This was slow, wasted CI minutes on issues a 2-second local check would have caught, and produced "fix lint" follow-up commits cluttering the history.

A standard local-enforcement layer was needed. The pre-commit ecosystem (config format, hook ecosystem, language-aware envs) is the obvious choice and is already a community standard. The remaining decision was which runner to use: `prek` (Rust reimplementation) or upstream `pre-commit` (Python).

## Decision

Adopt a single `.pre-commit-config.yaml` at the repo root and use `prek` as the **only supported runner**, both locally and in CI:

1. `prek` is installed by contributors out-of-band (`brew install j178/prek/prek`, `curl` from releases, or distro package). It is required — there is no Python fallback.
2. CI installs prek by piping the upstream `prek-installer.sh` (pinned to a tagged release) into `sh` and runs the hooks with `prek run --all-files` for both the `pre-commit` and `pre-push` stages.
3. Slow checks (GraphQL schema freshness, generated-type freshness) are gated to the `pre-push` stage so per-commit latency stays under the 10-second target. CI runs both stages.
4. The existing per-tool CI jobs (`python-lint`, `yaml-lint`, `markdown-lint`, `frontend-lint`, `graphql-schema-check`, `graphql-operations-check`, `helm-lint`) are kept in place during a parity-validation period before any deduplication, so signal cannot regress.
5. The hook config uses no prek-only YAML extensions — the `.pre-commit-config.yaml` format is the public, documented superset that prek consumes. This keeps the door open if we ever revisit using `pre-commit` directly.
6. An invoke task wrapper (`uv run invoke pre-commit-install` / `pre-commit-run`) keeps the onboarding command consistent with the rest of the project's invoke-driven workflow.

### Why prek-only

The original draft of this ADR supported both `prek` and `pre-commit` (Python) as interchangeable runners, motivated by inclusion concerns for contributors who might be unable to install Rust binaries (corporate-restricted shells, locked-down CI runners). After implementation that requirement was reconsidered: for this team the inclusion concern is theoretical, and the cost of dual-runner support — an extra dev dependency, runner-detection logic in the invoke wrapper, divergent local-vs-CI runtime — is real. Going prek-only removes those costs without sacrificing the ability to revert (the config format is unchanged).

## Consequences

**Easier:**

- Lint and format failures surface in seconds locally instead of minutes in CI.
- A single declarative config (`.pre-commit-config.yaml`) is the source of truth for what "clean" means; CI and local agree by construction.
- Onboarding is one command (`uv run invoke pre-commit-install`) plus a one-time prek install.
- One runner everywhere — no `_resolve_runner` branching, no version-skew between prek and pre-commit, no extra dev dependency.
- prek's parallel hook execution makes CI's `Pre-Commit Hooks` job fast even on a cold cache.

**Harder:**

- Contributors who cannot install prek on their machine are blocked from running the hooks. The fallback is `git commit --no-verify`, which delays the failure to CI but does not block contribution outright.
- The hook config and the per-tool CI jobs run the same checks during the parity-validation period — this is intentional duplication, but it does cost a small amount of CI time. After a parity period, the per-tool jobs the hook job fully subsumes can be removed.
- Contributors must run `uv sync` and `pnpm install` before the hooks fire; otherwise hooks that shell out to `uv run …` or `pnpm` produce confusing "command not found" errors. Mitigated by the dev guide.
- Hook-version pins (`rev:` in `.pre-commit-config.yaml`) need periodic bumping; floating refs are forbidden, so this is a manual maintenance task (a future routine could automate it).

## Alternatives Considered

- **`pre-commit` (Python) as a fallback runner alongside prek**: Initially adopted, then reverted. The flexibility was outweighed by the maintenance and complexity cost (extra dev dep, runner-detection logic, divergent CI behaviour). Documented in the section "Why prek-only" above.
- **`pre-commit` (Python) only**: Rejected — too slow per-commit on a project with many hooks; would push contributors toward `git commit --no-verify`.
- **A custom invoke task that wraps each check**: Rejected — duplicates the declarative config that pre-commit / prek already provide and forfeits the published-hook ecosystem (e.g., the `pre-commit-hooks` repo for hygiene checks).
- **All hooks on `pre-commit` stage (no `pre-push` gating)**: Rejected — the GraphQL schema regen and generated-type regen each take several seconds and would push contributors toward bypass.
- **Drop the per-tool CI jobs immediately when the hook job lands**: Rejected — silent CI signal loss is a much larger risk than the small cost of running both jobs during the parity-validation period.
