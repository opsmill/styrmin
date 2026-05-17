# Implementation Plan: `styrminctl` Authentication — `login` / `logout` / `whoami` + Persistent Token Store

**Branch**: `011-styrminctl-auth` | **Date**: 2026-05-17 | **Spec**: [spec.md](./spec.md)
**Input**: [`spec.md`](./spec.md)

## Summary

Add three CLI commands (`login`, `logout`, `whoami`) and a per-user token-store file under XDG so `styrminctl` can authenticate against any post-#179 backend. Credentials are resolved through a four-rung precedence ladder (`STYRMIN_TOKEN` → token store → `STYRMIN_USERNAME`+`PASSWORD` auto-login → unauthenticated). Two new deep modules — `TokenStore` and `CredentialResolver` — own their unit-test suites; everything else is covered through one `api_only`-marked E2E scenario. No GraphQL schema change, no new dependency, no backend change.

## Technical Context

**Language/Version**: Python 3.14+
**Primary Dependencies**: Cyclopts 3.x (CLI framework, already in `cli/`), pydantic-settings (already in `cli/`), styrmin-sdk (local workspace, already in `cli/`), stdlib (`getpass`, `json`, `pathlib`, `os`, `stat`, `urllib.parse`)
**Storage**: Single per-user JSON file at `${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token` (file `0600`, directory `0700`). No database changes.
**Testing**: pytest (CLI unit tests under `cli/tests/`; E2E under `backend/tests/e2e/` driving `styrminctl` as a subprocess against a real vcluster-backed backend per AGENTS.md)
**Target Platform**: POSIX (Linux, macOS). Windows out of scope for v1.
**Project Type**: CLI extension in a Python monorepo. Touches `cli/` and `backend/tests/e2e/` only.
**Performance Goals**: First-time `styrminctl login` → first authenticated command in under 30 seconds (SC-006). Login round-trip cost ≈ one GraphQL `login` request.
**Constraints**: No backend / GraphQL schema change. No new dependencies. No CI workflow change. Password material never written to disk. File permissions strictly `0600`/`0700`.
**Scale/Scope**: 3 new CLI commands, 2 new helper modules (deep), 1 extended client, 1 documentation section, 1 E2E scenario. Single-user, single-machine credential cache; one entry per backend URL.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| §I Declarative reconciliation | ✅ N/A | Feature does not touch desired-vs-current diff logic. `login` is idempotent (overwrites same per-server entry). |
| §II Driver-based deployment | ✅ N/A | No driver, component, or deployment-path change. |
| §III Layered architecture | ✅ PASS | CLI → SDK only; SDK → GraphQL only. `TokenStore` / `CredentialResolver` are CLI-internal helpers, no cross-layer shortcuts. |
| §IV Type safety & typed errors | ✅ PASS | Reuses existing `StyrminAuthenticationError` from SDK; CLI-side ergonomic failures (asymmetric env vars, corrupt JSON, chmod failure) surface as `sys.exit(<msg>)`, not domain errors — appropriate per §IV (CLI control-flow signals, not service-layer errors). |
| §V Test-first / E2E required | ✅ PASS | One named E2E scenario (see `quickstart.md`), runs as `[api-chromium]` marked `@pytest.mark.api_only` (CLI exercised via subprocess; no UI flow). Local PASS evidence to be recorded at implementation time per §V mandate. |
| §V GraphQL ↔ DB propagation tests | ✅ N/A | No GraphQL field / argument / input / mutation added or modified. `login`, `logout`, `currentUser` already exist (#179) and are already covered by propagation tests. Explicitly confirmed against `schema.graphql`. |
| §VI Format and lint before commit | ✅ PASS | Standard `uv run invoke format lint` at implementation time. |
| Governance gate: auth / authz | ⚠️ Acknowledged | Authentication UX change. Auth *model* unchanged (still session tokens from #179, ADR-024). The PRD on #234 is the asked-and-answered authorisation. |
| Governance gate: GraphQL schema | ✅ Not crossed | No schema change. |
| Governance gate: DB schema | ✅ Not crossed | No DB change. |
| Governance gate: new dependency | ✅ Not crossed | All libraries already in `cli/`. |
| Governance gate: CI/CD | ✅ Not crossed | E2E runs in the existing pytest matrix. |

**Verdict**: No violations. Proceed.

## Project Structure

### Documentation (this feature)

```text
specs/011-styrminctl-auth/
├── plan.md              # This file
├── research.md          # Phase 0 — resolved unknowns + design rationale
├── data-model.md        # Phase 1 — TokenStore JSON shape, canonical-URL rule
├── contracts/           # Phase 1 — CLI command contracts (login/logout/whoami)
│   ├── login.md
│   ├── logout.md
│   ├── whoami.md
│   └── credential-precedence.md
├── quickstart.md        # Phase 1 — local-dev steps + E2E scenario blueprint
├── checklists/
│   └── requirements.md  # produced by /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
cli/
├── src/styrminctl/
│   ├── auth/                      # NEW package
│   │   ├── __init__.py
│   │   ├── token_store.py         # NEW — deep module: load/save/delete, XDG path, perms, canonical key
│   │   └── resolver.py            # NEW — deep module: 4-rung credential resolver, returns (token, source)
│   ├── commands/
│   │   └── auth.py                # NEW — Cyclopts subapp: login / logout / whoami
│   ├── client.py                  # MODIFIED — get_client() delegates to CredentialResolver; returns (client, source)
│   ├── cli_commands.py            # MODIFIED — register auth subapp; install top-level error boundary
│   └── errors.py                  # NEW (small) — CLI-side error rendering for StyrminAuthenticationError + TokenStoreError
└── tests/
    ├── auth/
    │   ├── test_token_store.py    # NEW — unit suite for TokenStore
    │   └── test_resolver.py       # NEW — unit suite for CredentialResolver
    └── commands/
        └── test_auth_commands.py  # NEW — light CLI tests with mocked SDK

backend/tests/e2e/
└── test_cli_auth.py               # NEW — single api_only scenario: login → permissions → authenticated command → logout

cli/README.md                       # MODIFIED — new "Authentication" section
```

**Structure Decision**: The CLI is the only component touched. Two new helper modules under a new `cli/src/styrminctl/auth/` package keep `TokenStore` and `CredentialResolver` deep and independently testable. The CLI commands live under the existing `commands/` package alongside `clusters`, `environments`, etc. The E2E test lives under `backend/tests/e2e/` to share the project's vcluster fixtures and follow the existing dual-entrypoint convention (`api_only` marker).

## Phase 0: Outline & Research

See [`research.md`](./research.md). Resolves the three spec-level `[NEEDS CLARIFICATION]` markers, captures the deep-module rationale, and locks the canonical-URL canonicaliser, file-permission algorithm, hidden-prompt helper, and `whoami` source-attribution scheme.

## Phase 1: Design & Contracts

Outputs:

- [`data-model.md`](./data-model.md) — token-store JSON schema (`schema_version: 1`, `{<canonical_url>: <token>}`), canonical-URL rule, file/directory permission invariants.
- [`contracts/`](./contracts/) — per-command CLI contracts:
  - [`login.md`](./contracts/login.md) — argument shape, hidden-prompt behaviour, exit codes, error wording.
  - [`logout.md`](./contracts/logout.md) — best-effort backend call, store mutation semantics, exit codes.
  - [`whoami.md`](./contracts/whoami.md) — output shape, source-attribution string, exit codes.
  - [`credential-precedence.md`](./contracts/credential-precedence.md) — the four-rung ladder, expressed as a decision table testable by `CredentialResolver` unit tests.
- [`quickstart.md`](./quickstart.md) — local-dev walkthrough + the E2E scenario blueprint.

**Agent context**: per the Styrmin constitution's Never list, `update-agent-context.sh` is not executed. The `<!-- SPECKIT START --> ... <!-- SPECKIT END -->` block in `CLAUDE.md` is updated manually by this plan: it points at `specs/011-styrminctl-auth/plan.md` for the active plan reference.

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1 artefacts were written:

- §III layering preserved — no helper crosses out of CLI; auto-login still goes through `client.auth.login(...)`.
- §IV typed errors — no new domain error classes needed; CLI-side `TokenStoreError` (corrupt JSON, chmod failure) is a CLI-only `Exception` subtype that renders as `sys.exit(<msg>)`, never propagating into service / repository layers.
- §V E2E — single scenario named in `quickstart.md`; will be marked `@pytest.mark.api_only` with a `reason=` string explaining the dual-entrypoint decision per AGENTS.md.
- §V propagation tests — N/A confirmed by direct inspection of `schema.graphql` (LoginResult / Logout / CurrentUser unchanged).

No new violations. Proceed to Phase 2 (tasks).

## Complexity Tracking

(No violations to justify.)
