---

description: "Task list for 011-styrminctl-auth — CLI login/logout/whoami + persistent token store"
---

# Tasks: `styrminctl` Authentication — `login` / `logout` / `whoami` + Persistent Token Store

**Input**: Design documents from `/specs/011-styrminctl-auth/`
**Prerequisites**: `plan.md` (required), `spec.md` (required for user stories), `research.md`, `data-model.md`, `contracts/`

**Tests**: Required (per Styrmin Constitution §V). Unit tests for `TokenStore` and `CredentialResolver` (the two deep modules), light CLI tests for the three new commands, and one `api_only`-marked E2E scenario.

**Organization**: Tasks are grouped by user story so each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3)
- Paths shown are repo-relative.

## Path Conventions

- **CLI code**: `cli/src/styrminctl/`
- **CLI tests**: `cli/tests/`
- **E2E tests**: `backend/tests/e2e/` (per AGENTS.md — uses shared vcluster fixtures)
- **Docs**: `cli/README.md`, `AGENTS.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Skeleton for the new `auth/` package and test directories.

- [ ] T001 Create the new package directory `cli/src/styrminctl/auth/` and add an empty `__init__.py` so it is importable
- [ ] T002 Create the new test directory `cli/tests/auth/` and add an empty `__init__.py`
- [ ] T003 [P] Create the new test directory `cli/tests/commands/` if absent and add `__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Deep modules and shared types that every user story depends on. These ship before any command code lands.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T004 [P] Define CLI-only error types in `cli/src/styrminctl/errors.py`: `TokenStoreError(Exception)` (carries `path: Path` and `reason: str`) and `AsymmetricEnvCredentialsError(Exception)` (carries the missing variable name). Each `__str__` produces a single-line human message.
- [ ] T005 [P] Define `TokenSource` literal type (`Literal["env", "file", "auto-login", "none"]`) and `AuthContext` dataclass (`client: StyrminClient`, `source: TokenSource`) in `cli/src/styrminctl/auth/types.py`
- [ ] T006 Implement `TokenStore` in `cli/src/styrminctl/auth/token_store.py`. Public surface: `canonicalise(server_address: str) -> str`, `path() -> Path`, `get(canonical_url: str) -> str | None`, `set(canonical_url: str, token: str) -> None`, `delete(canonical_url: str) -> None`. Internals: load `{schema_version: 1, tokens: {...}}`; raise `TokenStoreError` on corrupt JSON or unknown `schema_version`; empty token treated as absent; **atomic save** via `<target>.tmp.<pid>.<random>` + `os.rename()`; ensure parent dir mode `0700` and file mode `0600` after every save.
- [ ] T007 Implement `CredentialResolver` in `cli/src/styrminctl/auth/resolver.py`. Public surface: `async def resolve(settings, env, token_store) -> tuple[str | None, TokenSource]`. Implements the four-rung ladder from `contracts/credential-precedence.md` exactly; raises `AsymmetricEnvCredentialsError` on rung 4; performs the in-process `auth.login` for rung 3 (using a short-lived `StyrminClient` constructed from `settings.server_address` and `timeout`); never persists.
- [ ] T008 [P] Unit suite for `TokenStore` in `cli/tests/auth/test_token_store.py` covering: round-trip set/get/delete; `canonicalise` collision matrix (mixed case, trailing slash, distinct ports); missing-file is not an error; corrupt JSON raises `TokenStoreError`; unknown `schema_version` raises `TokenStoreError`; file mode `0600` after save; parent dir mode `0700` after save; two distinct canonical URLs coexist (FR-013); concurrent saves preserve both entries via the atomic-rename invariant (critique E2); empty string in JSON treated as absent.
- [ ] T009 [P] Unit suite for `CredentialResolver` in `cli/tests/auth/test_resolver.py` covering all 9 rows of the decision table in `contracts/credential-precedence.md`, including: `STYRMIN_TOKEN` wins; disk token wins when env-var token absent; env-var auto-login wins over disk token (row 5); empty `STYRMIN_TOKEN` treated as unset; asymmetric env-vars raise `AsymmetricEnvCredentialsError` (rows 7 and 8); `none` source when nothing present. Use a stubbed `TokenStore` and a `monkeypatch`-managed env dict; mock the SDK `auth.login` for the auto-login rung.

**Checkpoint**: Foundation ready — user-story work can now proceed.

---

## Phase 3: User Story 1 - Interactive `login` persists a token; subsequent commands just work (Priority: P1) 🎯 MVP

**Goal**: Operator runs `login` once and every subsequent `styrminctl` command (including `whoami` and `logout`) authenticates without ceremony.

**Independent Test**: Run `styrminctl login --username <seeded>` against the e2e backend with the password on stdin; assert exit 0 and the token file at `0600`. Open a fresh subprocess with only `STYRMIN_ADDRESS` set, run `styrminctl clusters list`, assert exit 0. Run `styrminctl whoami`, assert exit 0 and the `Authenticated via: token file (...)` line. Run `styrminctl logout`, assert exit 0 and the entry is removed.

### Implementation for User Story 1

- [ ] T010 [US1] Extend `cli/src/styrminctl/client.py`: keep `get_client() -> StyrminClient` signature unchanged (so the seven existing command modules continue to compile). Add a new `async def get_auth_context() -> AuthContext` that runs `CredentialResolver.resolve(...)` and wraps the resulting token into a configured `StyrminClient`. Refactor `get_client()` to share the resolver path (returning only the `.client`). Source rung `"none"` produces a client with no `Authorization` header — used only by `login` itself.
- [ ] T011 [US1] Implement the `auth_app` Cyclopts subapp in `cli/src/styrminctl/commands/auth.py`. Three subcommands: `login` (`--username` optional; hidden `getpass` password prompt; prints "Authenticating against …" then "Logged in to … as …"; persists via `TokenStore`), `logout` (best-effort `client.auth.logout()` swallowing errors; `TokenStore.delete`; prints "Logged out of …"), `whoami` (calls `get_auth_context()`; prints identity + source line; non-zero exit + friendly message on `source == "none"` or `current_user == None`). All output paths match the wording in `contracts/login.md`, `contracts/logout.md`, `contracts/whoami.md`.
- [ ] T012 [US1] Wire the new subapp in `cli/src/styrminctl/cli_commands.py`: `app.command("styrminctl.commands.auth:auth_app", name="auth", help="Authentication commands (login, logout, whoami).")`. Also register the three subcommands at the top level for shorthand: `styrminctl login` → `styrminctl auth login`, etc., following the project's existing flat-command convention by reviewing how other command modules are registered.
- [ ] T013 [US1] Install the top-level CLI error boundary in `cli/src/styrminctl/cli_commands.py` (or a new `cli/src/styrminctl/cli.py` wrapper around `app`): catch `StyrminAuthenticationError`, `TokenStoreError`, and `AsymmetricEnvCredentialsError` and render each as a single-line stderr message + non-zero exit code per the contracts. NEVER print a Python traceback for these three.
- [ ] T014 [P] [US1] CLI tests for `login` and `logout` in `cli/tests/commands/test_auth_commands.py` using a mocked `StyrminClient`: `test_login_prints_resolved_address`, `test_login_persists_token_with_correct_permissions` (asserts file mode after the call), `test_login_handles_non_tty_stdin_with_friendly_error` (critique E5; simulates `EOFError` from `getpass`), `test_logout_is_noop_without_prior_token`, `test_logout_swallows_backend_errors`, `test_password_never_logged_or_echoed` (captures `caplog` and asserts the password substring is absent).
- [ ] T015 [P] [US1] CLI tests for `whoami` in `cli/tests/commands/test_auth_commands.py` (same file, separate tests): `test_whoami_source_line_env`, `test_whoami_source_line_file`, `test_whoami_source_line_auto_login`, `test_whoami_friendly_error_when_unauthenticated`, `test_whoami_friendly_error_on_stale_token` (injects `StyrminAuthenticationError`; asserts the `Run \`styrminctl login\` to refresh.` line and that the disk token is NOT auto-deleted).

**Checkpoint**: US1 is fully functional and testable through CLI unit tests. The E2E scenario in Phase 6 confirms end-to-end.

---

## Phase 4: User Story 2 - Non-interactive auto-login via `STYRMIN_USERNAME` + `STYRMIN_PASSWORD` (Priority: P2)

**Goal**: CI jobs authenticate transparently through env vars without persisting to disk.

**Independent Test**: In a subprocess with `STYRMIN_USERNAME`+`STYRMIN_PASSWORD` set and no `STYRMIN_TOKEN`/token file, run an authenticated command; assert exit 0 and the token file is not created.

### Implementation for User Story 2

- [ ] T016 [US2] Confirm `CredentialResolver` (T007) handles the auto-login rung end-to-end: the rung-3 path inside `cli/src/styrminctl/auth/resolver.py` MUST create a `StyrminClient` configured with `server_address` and `timeout` from `Settings`, call `auth.login(username, password)`, return `(token, "auto-login")`, and ensure the in-process client is closed so the per-invocation lifetime is bounded. Add the missing wiring if T007 deferred any of this.
- [ ] T017 [P] [US2] Extend `cli/tests/auth/test_resolver.py` with `test_auto_login_does_not_persist_to_disk` (asserts `TokenStore.set` is never called for source `"auto-login"`) and `test_auto_login_wins_over_disk_token` (row 5 of the decision table — included in T009 if scheduled together; otherwise add here).
- [ ] T018 [P] [US2] Add a CLI-level test in `cli/tests/commands/test_auth_commands.py`: `test_authenticated_command_uses_auto_login_when_env_vars_set` — runs a mocked-SDK invocation of any authenticated command (e.g. `clusters list`) with the env-var rung active and asserts: (a) `client.auth.login` was called exactly once, (b) the command call succeeded, (c) `TokenStore.set` was never called.

**Checkpoint**: US2 functional. CI path verified end-to-end through CLI tests.

---

## Phase 5: User Story 3 - Friendly failure mode when not logged in or token is invalid (Priority: P3)

**Goal**: Authentication failures render as a single human line, never a Python traceback; stale tokens are preserved for debugging.

**Independent Test**: Run any authenticated command with no credentials; assert stderr is exactly the friendly line and exit code is non-zero. Write a junk token, run again, assert same kind of message AND the file still exists.

### Implementation for User Story 3

- [ ] T019 [US3] Verify the top-level error boundary from T013 covers every failure path enumerated in the three contracts. Add any missing branches: `getpass` `EOFError` (`Cannot prompt for password: stdin is not a terminal. Use STYRMIN_USERNAME + STYRMIN_PASSWORD for non-interactive auth.`), network errors (`Could not reach <address>: <error class>.`), and `TokenStoreError` rendering with the file path.
- [ ] T020 [P] [US3] CLI tests in `cli/tests/commands/test_auth_commands.py`: `test_no_credentials_prints_friendly_line_and_exits_non_zero`, `test_stale_token_does_not_delete_local_entry` (asserts the file's `tokens[<key>]` is unchanged after an `UNAUTHENTICATED` failure), `test_corrupt_token_store_prints_friendly_line` (writes invalid JSON, asserts the message names the file and the parse error class).

**Checkpoint**: US3 functional. All three friendly-error paths are covered.

---

## Phase 6: E2E + Polish & Cross-Cutting Concerns

**Purpose**: One mandatory E2E scenario (Constitution §V), documentation, and lint/format. Tasks T021–T024 are mandatory; T025–T026 land alongside.

### E2E (NON-NEGOTIABLE per Constitution §V)

- [ ] T021 Author the E2E scenario in `backend/tests/e2e/test_cli_auth.py` per the blueprint in `quickstart.md`. Marked `@pytest.mark.ci` and `@pytest.mark.api_only(reason="Drives the styrminctl subprocess; no UI flow. The [ui-chromium] variant would re-execute the same subprocess and the same SDK login path with no incremental coverage.")`. Test name: `test_cli_login_persists_token_and_subsequent_command_succeeds`. Uses an isolated `XDG_DATA_HOME=<tmp_path>` per test. Steps 1–8 from `quickstart.md` (seed user; `login` subprocess with password on stdin; assert exit 0, stdout, file mode `0600`, parent dir `0700`, JSON schema_version, canonical-URL key; fresh-subprocess `clusters list` succeeds; `whoami` shows source line; `logout` removes entry; second `whoami` fails friendly).
- [ ] T022 Run the E2E to a local PASS per Constitution §V "Local PASS evidence required". Record in this `tasks.md` (under "PASS evidence" below) for the test: (a) pytest node ID, (b) exact pytest command, (c) ISO 8601 timestamp of the PASS, (d) cluster identifier (vcluster fixture id + kubeconfig path under `/tmp/pytest-of-*/pytest-*/`), (e) the verbatim `PASSED …` line from pytest output. Do NOT mark this spec complete without this evidence.

### Documentation

- [ ] T023 [P] Add the new "Authentication" section to `cli/README.md` covering: (1) the three flows (`login`, `STYRMIN_TOKEN`, `STYRMIN_USERNAME`+`PASSWORD`), (2) the precedence ladder verbatim from `contracts/credential-precedence.md`, (3) file path and permissions, (4) a paragraph on the auto-login network cost ("every invocation hits the backend", critique E3) recommending job-level retry/timeout rather than expecting a built-in cache, (5) a paragraph on `STYRMIN_PASSWORD` env-var trade-offs (process-list visibility, leak risk; recommend `STYRMIN_TOKEN` with a short-lived token when the CI platform supports it — critique E4).
- [ ] T024 [P] Add a one-line pointer in `AGENTS.md` Navigation table for the CLI Authentication section (critique P1): `| How do I authenticate the CLI? | cli/README.md#authentication |` (or matching column shape of the existing table).

### Lint and format

- [ ] T025 Run `uv run invoke format lint` and resolve any findings on the new files.

### Spec hygiene

- [ ] T026 [P] After local PASS evidence is recorded in T022, update the spec's `Status:` from `Draft` to `Implemented` and update the `checklists/requirements.md` `[NEEDS CLARIFICATION]` row to `[x]` (3 retained markers resolved by R1/R2/R3 in research.md).

---

## Dependencies

Story completion order:

- **Phase 1 (Setup)** → **Phase 2 (Foundational)** → **Phase 3 (US1)** → **Phases 4 & 5 (US2, US3) in parallel** → **Phase 6 (E2E + Polish)**.
- Phase 2 blocks every user story. T004 (errors), T005 (types), T006 (TokenStore), T007 (CredentialResolver) must land before T010+.
- US2 (Phase 4) and US3 (Phase 5) are independent of each other once Phase 3 is done.
- T021–T022 (E2E + PASS evidence) is the gating "definition of done" — no merge without it.

Task-level dependencies inside phases:

- T006 depends on T004 (raises `TokenStoreError`).
- T007 depends on T004 + T005 + T006.
- T008 depends on T006.
- T009 depends on T007.
- T010 depends on T005 + T007.
- T011 depends on T006 + T010.
- T012 depends on T011.
- T013 depends on T004 + T011.
- T014 / T015 depend on T011 + T012 + T013.
- T021 depends on the entire CLI build (T010–T013).

## Parallel Execution Examples

- After Phase 1 lands: T004 + T005 in parallel (different files, no deps).
- After T006 + T007 land: T008 + T009 in parallel (different test files).
- Within Phase 3: T014 + T015 in parallel (same file but separate test functions; can be co-authored or split).
- Phase 6 docs: T023 + T024 in parallel; T025 sequential after all code lands.

## Implementation Strategy

1. Land Phase 1 + Phase 2 in one PR cycle ("foundation"). The CLI surface does not change yet; reviewers focus on the two deep modules + their unit suites. This is also the cheapest moment to catch design issues — both modules are pure logic.
2. Land Phase 3 (US1) in the next PR. This is the MVP — interactive `login` + `logout` + `whoami` all work, the unit suites are extended to cover the command modules, and the docs in T023/T024 land alongside (Phase 6 partial). At this point the CLI is usable interactively against any post-#179 backend.
3. Phases 4 + 5 + Phase 6 (E2E + PASS evidence) land together as the closing PR. Resolves CI auto-login + friendly errors and produces the PASS-evidence record that the spec requires.

If schedule pressure forces a smaller v1 still:

- The MVP cut is "Phases 1 + 2 + 3 only" — operators can `login` interactively and use the CLI from a workstation. US2 (CI auto-login) and US3 (friendly errors) ship as fast follow-ups under the same spec. This is documented as a fallback only; the default plan is to ship all three.

## PASS evidence (filled at T022)

> Per Constitution §V — record the local PASS run for each new/modified E2E test before declaring this spec implemented. Until this section is filled in by a real run, the spec is NOT done.

- **Test**: `backend/tests/e2e/test_cli_auth.py::test_cli_login_persists_token_and_subsequent_command_succeeds[api-chromium]`
- **Command**: _(fill at T022)_
- **Timestamp (ISO 8601)**: _(fill at T022)_
- **Cluster**: _(vcluster fixture id + kubeconfig path)_
- **PASSED line**: _(verbatim from pytest output)_
