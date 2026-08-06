# Implementation Report: Environment-Level Backup and Restore

**Status:** COMPLETE

| | |
|---|---|
| Feature | Environment-level backup and restore (issue #7) |
| Spec directory | `specs/001-env-backup-restore/` |
| Base commit | `609e45a` (alignment check) |
| Head commit | `a17d973` |
| Commits | 14 (11 implementation + 3 review-fix) |
| Diff | 95 files, +16,198 / −342 |
| Tasks | 41 / 41 complete |
| Branch | `fac/env-backup-restore-6jtfn` |

Implementation ran as nine sequential clean-context subagent chunks, followed by a
six-agent review pass and three consolidated fix passes.

---

## 1. Chunk ledger

| # | Chunk | Tasks | ✅ | ⚠️ | ❌ | Commit(s) |
|---|-------|-------|----|----|----|-----------|
| 1 | Phase 1 — Foundational | T001–T008 | 8 | 0 | 0 | `1d4422e` |
| 2 | Phase 2a — US1 backend | T009–T014 | 6 | 0 | 0 | `a0eba69` |
| 3 | Phase 2b — US1 SDK + CLI | T015–T018 | 4 | 0 | 0 | `52b6a11` |
| 4 | Phase 2c — US1 frontend | T019–T021 | 3 | 0 | 0 | `60ab5cf` |
| 5 | Phase 3a — US2 backend | T022–T025 | 4 | 0 | 0 | `dbbcb0b` |
| 6 | Phase 3b — US2 SDK/CLI/frontend | T026–T028 | 3 | 0 | 0 | `5dfbae5` |
| 7 | Phase 4 — US3 lifecycle | T029–T032 | 4 | 0 | 0 | `b1b5561` |
| 8 | Phase 5 — E2E + CI matrix | T033–T036 | 4 | 0 | 0 | `2072a16`, `cca8106`, `b3bca53` |
| 9 | Phase 6 — Docs + final gates | T037–T041 | 5 | 0 | 0 | `c9a0bc6` |
| — | Review fixes (Phase 6 of this workflow) | — | — | — | — | `d209ce7`, `0fc0716`, `a17d973` |

**Chunking rationale.** Phase 2 (13 tasks, four surfaces) and Phase 3 (7 tasks, four
surfaces) both exceeded the ~10-task / ~15-file threshold and were split along surface
seams. All other phases mapped 1:1 to a chunk. No two implementation subagents ran
concurrently.

### Decisions flagged upward by chunk

**Chunk 1.** Verified the Alembic revision beyond the test suite — applied the full chain
on SQLite *and* a throwaway PostgreSQL 16 (upgrade → downgrade → re-upgrade), with an
autogenerate diff returning 0 entries. Correct diligence: tests bypass migrations, so a
green suite is not evidence. Added `EnvironmentOperationStatus`, `TERMINAL_…`/
`RESTORABLE_…` frozensets and a `SkipReason` enum beyond the literal task text; documented
that all-`PENDING`-with-errors derives `IN_PROGRESS`, not `PENDING`.

**Chunk 2.** Extracted `resolve_backup_target(instance_id, uow) -> BackupTarget` into
`services/backup/service.py`, replacing `createBackup`'s inline block (and fixing a
`uow.session.get` layering violation). Established that `create_environment_backup` must be
`@inject`-decorated with `Depends(get_manager)` — a direct `get_manager()` call escapes the
test mock and reaches real Prefect. Discovered that `strawberry.enum` binds one GraphQL name
per class, so `EnvironmentRestoreStatus` needs a separate mirror. Added `_eager_load_options`
+ a `get` override to avoid `MissingGreenlet` in the async derived-status resolver.

**Chunk 3.** `--wait` exits non-zero on `PARTIAL` as well as `FAILED` — the exit code is the
only machine-readable signal that not every deployment was covered. Discovered that
`invoke generate-validate` diffs against the git *index* and runs `git checkout --` on
generated files when it fails, silently reverting fresh codegen.

**Chunk 4.** Split the UI into `EnvironmentBackupsTab` + `EnvironmentBackupRow` so the later
restore/delete chunks could extend cleanly. Added `partial` to `StatusBadge`. Established the
`data-testid` contract consumed by the Playwright driver in chunk 8.

**Chunk 5.** Restore reverts `Environment.config` by direct assignment, never via
`update_environment` (whose `None` no-op guard would break a captured-`None` revert). Added
`EnvironmentBackup.restores`, which `contracts/graphql.md` specified but no task claimed.

**Chunk 7.** `delete_environment` now guards existence *before* cascading, so a mistyped id
cannot delete another environment's snapshots. An already-absent constituent is a no-op in
the cascade, not an error.

**Chunk 8.** The UI entrypoint earned its keep: it caught a real bug no unit or propagation
test surfaced — the tab read snapshot rows before `ListEnvironmentBackups` had settled
(`cca8106`). Also found that every scenario environment owns an internal ingress-controller
deployment with an active instance, making SC-001 assertable as equality and doubling as the
FR-001 internal-exclusion check.

**Chunk 9.** ADR number 0055 confirmed free before use; found the ADR index lives in
`dev/README.md`, not `dev/adr/README.md`. `CONTEXT.md` already had both glossary entries but
they had drifted (lowercase statuses, missing `PENDING`/`IN_PROGRESS`, no ADMIN asymmetry) —
corrected, and added canonical *constituent backup* / *constituent restore* entries.

---

## 2. Tasks not completed

None. All 41 tasks are `[X]` in `tasks.md`.

---

## 3. Local-pass evidence

All tests were observed passing locally. **Rows are grouped per test module with counts and
the runner's verbatim aggregate line** — per-test rows would run to 300+ lines. The two E2E
entrypoint variants are listed individually, as Constitution §V requires. Every row's
command, timestamp, environment and verbatim pass line is reproduced from the executing
subagent's report.

### Unit and integration

| Test module | Type | Count | Run command | Passed at (UTC) | Environment | Verbatim pass line |
|---|---|---|---|---|---|---|
| `backend/tests/unit/services/backup/test_environment_backup.py` (derivation matrix, T007) | unit | 26 | `uv run pytest backend/tests/unit/services/backup/test_environment_backup.py backend/tests/unit/repository/backup/test_environment_backup_repository.py -v -p no:randomly` | 2026-08-06T12:15:55Z | in-memory SQLite; no cluster/Prefect | `44 passed in 0.99s` |
| `backend/tests/unit/repository/backup/test_environment_backup_repository.py` (T008) | unit | 18 | (same command as above) | 2026-08-06T12:15:55Z | in-memory SQLite | `44 passed in 0.99s` |
| `…/test_environment_backup.py` (create fan-out, T010) | unit | 16 | `uv run pytest backend/tests/unit/services/backup/test_environment_backup.py backend/tests/functional/graphql/test_environment_backup.py -p no:randomly -v` | 2026-08-06T12:36:08Z | in-memory SQLite; `prefect_manager_mock` | `55 passed in 1.06s` |
| `backend/tests/functional/graphql/test_environment_backup.py` (propagation, T014) | integration | 13 | (same command as above) | 2026-08-06T12:36:08Z | reads back via `fresh_client` second session | `55 passed in 1.06s` |
| `python_sdk/tests/test_environment_backups.py` (T015–T016) | unit | 13 | `uv run pytest python_sdk/tests/test_environment_backups.py -v` | 2026-08-06T12:54:21Z | mocked `Transport`; no network | `13 passed in 0.03s` |
| `cli/tests/test_environment_backups.py` (T018) | unit | 21 | `cd cli && uv run pytest tests/test_environment_backups.py -v` | 2026-08-06T12:54:26Z | cwd `cli/`; `mock_client` patches `get_client`; one test sets `COLUMNS=200` | `21 passed in 0.21s` |
| `frontend/src/__tests__/environments/EnvironmentBackupsTab.test.tsx` (T021) | unit (component) | 11 | `pnpm vitest run src/__tests__/environments/EnvironmentBackupsTab.test.tsx src/components/StatusBadge.test.tsx --reporter=verbose` | 2026-08-06T13:04:49Z | `PATH=/root/.local/node22/bin:$PATH` (node v22.16.0) | `Tests  19 passed (19)` |
| `frontend/src/components/StatusBadge.test.tsx` (modified, T020) | unit | 1 | (same command as above) | 2026-08-06T13:04:49Z | node 22 | `Tests  19 passed (19)` |
| `…/test_environment_backup.py` (restore path, T023) | unit | 26 | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/services/backup/test_environment_backup.py backend/tests/functional/graphql/test_environment_backup.py -v -p no:randomly` | 2026-08-06T13:37:33Z | fresh `PREFECT_HOME`; no cluster | `97 passed in 2.15s` |
| `…/functional/graphql/test_environment_backup.py` (restore propagation, T025) | integration | 16 | (same command as above) | 2026-08-06T13:37:33Z | second-session read-back | `97 passed in 2.15s` |
| `python_sdk/tests/test_environment_backups.py::TestEnvironmentRestore` (T026) | unit | 12 | `uv run pytest python_sdk/tests/test_environment_backups.py -q` | 2026-08-06T13:44:59Z | mocked transport | `26 passed in 0.05s` |
| `cli/tests/test_environment_backups.py` (restore, T027) | unit | 12 new + 1 modified | `cd cli && uv run pytest tests/test_environment_backups.py -q` | 2026-08-06T13:47:36Z | cwd `cli/` | `33 passed in 0.25s` |
| `frontend/src/__tests__/environments/EnvironmentBackupRestore.test.tsx` (T028) | unit (component) | 17 | `npx vitest run src/__tests__/environments/EnvironmentBackupRestore.test.tsx --reporter=verbose` | 2026-08-06T13:52:43Z | node 22 | `Tests  17 passed (17)` |
| `…/test_environment_backup.py` (delete cascades, T029) | unit | 12 | `uv run pytest backend/tests/unit/services/backup/test_environment_backup.py -v -k "delet"` | 2026-08-06T14:18:23Z | repo root | `13 passed, 67 deselected in 0.25s` |
| `…/functional/graphql/test_environment_backup.py` (cascade propagation, T030) | integration | 8 | `uv run pytest backend/tests/functional/graphql/test_environment_backup.py -v -k "delete or gap"` | 2026-08-06T14:18:31Z | SQLite; asserts after `expire_all()` | `8 passed, 29 deselected in 0.57s` |
| `python_sdk/tests/test_environment_backups.py` (delete, T031) | unit | 2 | `uv run pytest python_sdk/tests/test_environment_backups.py -v -k "delete"` | 2026-08-06T14:18:39Z | run separately from `backend/tests` (pre-existing conftest path clash) | `2 passed, 26 deselected in 0.01s` |
| `cli/tests/test_environment_backups.py` (delete, T031) | unit | 3 new + 1 modified | `cd cli && uv run pytest tests/test_environment_backups.py -v -k "delete or help"` | 2026-08-06T14:18:40Z | cwd `cli/` | `4 passed, 32 deselected in 0.16s` |
| `frontend/src/__tests__/environments/EnvironmentBackupLifecycle.test.tsx` (T032) | unit (component) | 23 | `pnpm vitest run src/__tests__/environments/EnvironmentBackupLifecycle.test.tsx --reporter=verbose` | 2026-08-06T14:18:45Z | node 22 | `Tests  23 passed (23)` |
| `backend/tests/e2e/drivers/test_conformance.py` (T033; relocated by `0fc0716`) | unit | 15 | `uv run pytest backend/tests/e2e/drivers/test_conformance.py -v` | 2026-08-06T15:29Z | no cluster; imports playwright only | `15 passed, 1 warning in 20.92s` |
| `backend/tests/unit/services/backup/test_environment_backup.py` (review fixes, `d209ce7`) | unit | 8 (7 new + 1 rewritten) | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/services/backup/test_environment_backup.py -v -k "committed_once or survive_a_cancellation or rejected_from_the_moment or durable_before_any_dispatch or deleted_mid_fan_out or constituents_were_all_deleted"` | 2026-08-06T16:25:13Z | Python 3.14.3; fresh `PREFECT_HOME` | `8 passed, 79 deselected in 0.26s` |
| `cli/tests/test_environment_backups.py` (review fixes, `d209ce7`) | unit | 3 new + 1 modified | `cd cli && uv run pytest tests/test_environment_backups.py -v -k "already_failed or already_partial or wait_partial"` | 2026-08-06T16:25:20Z | cwd `cli/` | `5 passed, 34 deselected in 0.15s` |
| `backend/tests/unit/test_e2e_driver_conformance.py` (relocated + 1 new, `0fc0716`) | unit | 16 | `PREFECT_HOME=$(mktemp -d) uv run pytest tests --ignore=tests/e2e -q -k <sel>` from `backend/` | 2026-08-06 | fresh `PREFECT_HOME` | `16 passed, 2061 deselected in 1.45s` |
| `backend/tests/unit/test_e2e_ui_driver_navigation.py` (new, `0fc0716`) | unit | 12 | (same command, different `-k`) | 2026-08-06 | fresh `PREFECT_HOME` | `12 passed, 2077 deselected in 1.45s` |
| `frontend/src/__tests__/environments/*` (invalidation + auto-refresh, `0fc0716`) | unit (component) | 5 new + 1 modified | `pnpm vitest run src/__tests__/environments` | 2026-08-06 | node 22 | `Tests 62 passed (62)` |

### E2E — dual entrypoint (Constitution §V)

Both variants were run twice: once on the implementation tree (chunk 8) and **again after
`d209ce7` changed the transaction boundary of both create and restore**, since the original
evidence no longer described the shipped code. The re-run is the authoritative evidence.

| Test id | Type | Run command | Passed at (UTC) | Environment | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle[api-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb --durations=0` | 2026-08-06T16:46:16Z | vcluster `pytest-62d35003-15dd-413f-9325-096f6735e0a7`; kubeconfig `/tmp/pytest-of-root/pytest-1265/vcluster0/kubeconfig` | `1 passed, 1 warning in 463.18s (0:07:43)` |
| `…::test_environment_backup_and_restore_lifecycle[ui-chromium]` | e2e | `sleep infinity \| uv run pytest "<node>" -v -s --pdb --durations=0` | 2026-08-06T16:54:28Z | vcluster `pytest-dfd4f68d-58be-4858-b3e0-be47a24a4df5`; kubeconfig `/tmp/pytest-of-root/pytest-1266/vcluster0/kubeconfig` | `1 passed, 1 warning in 340.90s (0:05:40)` |
| `backend/tests/e2e/test_backup_restore.py -k "ui-chromium"` (full UI shard) | e2e | `sleep infinity \| uv run pytest backend/tests/e2e/test_backup_restore.py -k "ui-chromium" -v -s --pdb --durations=0` | 2026-08-06T17:01:35Z | vcluster `pytest-dd27b272-0f0b-4fb9-9173-113387542344` | `3 passed, 1 skipped, 4 deselected, 1 warning in 683.95s (0:11:23)` |
| *(superseded)* `…[api-chromium]` on the pre-`d209ce7` tree | e2e | as above | 2026-08-06T15:15:34Z | vcluster `pytest-63d1f2df-f3db-4dc1-8101-cdc78aa578a5` | `1 passed, 1 warning in 757.29s (0:12:37)` |
| *(superseded)* `…[ui-chromium]` on the pre-`d209ce7` tree | e2e | as above | 2026-08-06T15:09:47Z | vcluster `pytest-5408e339-bea8-45b8-91f9-aac5d599d155` | `1 passed, 1 warning in 321.82s (0:05:21)` |

No `MISSING` rows. No rows deferred for lack of local E2E support — `vcluster` and docker
29.2.1 were present and the self-bootstrapping fixture was used as designed.

### Final gate results (T041, re-verified after every fix pass)

| Gate | Command | Result |
|---|---|---|
| Format + lint | `uv run invoke format lint` | exit 0 — ruff format, ruff check, ty, rumdl, yamllint, `validate-graphql`, `generate-validate` all clean |
| Backend suite | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests --ignore=backend/tests/e2e -q` | `2087 passed, 2 skipped, 11 warnings in 59.57s` |
| Frontend suite | `cd frontend && pnpm test` | `Test Files 67 passed (67)` / `Tests 560 passed (560)` |
| SDK suite | `uv run pytest python_sdk/tests -q` | `181 passed in 0.24s` |
| CLI suite | `cd cli && uv run pytest` | `2 failed, 310 passed` — see below |

**The 2 CLI failures are pre-existing and not caused by this change.**
`tests/telemetry/test_store.py::test_unwritable_dir_falls_back_to_ephemeral_id` and
`tests/telemetry/test_telemetry_command.py::test_commands_succeed_under_unwritable_dir`
`chmod` a directory unwritable and assert the write fails; the process runs as uid 0, which
bypasses permission bits, so the tests' premise cannot hold in this environment. Proven twice
independently: by `git stash push -u` + re-run on a clean tree (identical failures), and by a
docs-only chunk observing them while `git status --porcelain | grep -vE '\.md$'` returned 0.

Also pre-existing, and avoided by using a fresh `PREFECT_HOME`: ~12 tests under
`backend/tests/unit/agent/` fail when `~/.prefect/prefect.db` is stamped at a Prefect
revision absent from the installed version.

---

## 4. Review findings

Six review agents ran in parallel over `609e45a..HEAD` (code, errors, tests, types,
comments, simplify). Findings below are as verified; `Fixed` means addressed in
`d209ce7`, `0fc0716`, or `a17d973`.

### Fixed

| Severity | File | Finding | Fix |
|---|---|---|---|
| **critical** | `services/backup/environment.py` | Parent committed alone before its children. (a) `except Exception` doesn't catch `CancelledError`, so a disconnect mid-fan-out discarded all recorded `ConstituentError`s, leaving a committed parent with missing children and zero errors → derives `COMPLETED`, `--wait` exits 0 (FR-007 violated). (b) The D6 guard is an `EXISTS` over non-terminal *children*, so in that window a second `createEnvironmentBackup` **passed the guard** → two overlapping environment backups (FR-009 violated). | `d209ce7` — parent + all constituent rows + all errors now commit in **one transaction**, dispatch follows. Required a `_SharedTransaction` no-op-commit UoW view so constituent `create_backup` calls join the caller's transaction while keeping FR-005 isolation. |
| **critical** | `backend/tests/e2e/drivers/test_conformance.py` | No `ci`/shard marker: the unit job runs `--ignore=tests/e2e` and the CI e2e cells filter `-m "ci and shard_X"`, so all 15 conformance tests executed in **no** CI job — a driver could silently omit a protocol method. | `0fc0716` — relocated to `backend/tests/unit/test_e2e_driver_conformance.py` (a new e2e step would have booted a vcluster via an `autouse` fixture on collection). Stub detection also switched from text-grep to AST. |
| **critical** | `api/definitions/backup/environment_restore.py` | The shipped GraphQL description told clients skip reasons "come from a fixed vocabulary" and listed six, while the service emits a seventh unbounded `restore could not be created: <exc>`. This reached `schema.graphql` and the generated frontend types — the one place a client author reads the contract. | `a17d973` — description now states the six values are conventional and `reason` is open text; `SkipReason` docstring corrected; schema + codegen regenerated. |
| **critical** | `dev/adr/0055-…md` | Four false claims about ADR-0012: a **fabricated quotation** ("the convention to replicate for any future environment-scope change" is not in ADR-0012); "everything else replicated verbatim" concealed a **second deviation** (the D6 guard is exactly the per-environment serialisation primitive ADR-0012 rejected); "no existing backup/restore code changed" was false; a misattributed quote at `:62`. | `a17d973` — quotation removed and the argument made on its merits; second deviation disclosed and justified; headline corrected while keeping the accurate qualifiers. |
| **high** | `services/backup/environment.py`, `services/backup/service.py` | `name="placeholder"` was INSERTed into a `unique=True` column (`BaseSQLModelRepository.create` flushes), so concurrently auto-named snapshots serialised on the index then failed. Confirmed by re-inserting the sentinel and getting `UNIQUE constraint failed: backup.name`. | `d209ce7` — name computed before `create()` using the client-side `default_factory` id, in `create_environment_backup` **and** `create_backup`/`create_restore` (mandatory once two constituents share one transaction). |
| important | `services/backup/environment.py` | `assert persisted is not None` ("cannot vanish here") is reachable: deleting an in-flight snapshot is the documented FR-010 escape hatch. Produced an opaque `INTERNAL_ERROR`, or an `AttributeError` under `python -O`. | `d209ce7` — logs at warning and raises `EnvironmentBackupNotFoundError` / `EnvironmentRestoreNotFoundError`. |
| important | `cli/…/environment_backups.py` | `create` printed `Success: … status: FAILED` and exited 0 when every constituent failed at creation (status is derived synchronously). New behaviour, not inherited — `backups create` is always `PENDING`. | `d209ce7` — reports and exits 1 on an already-`FAILED`/`PARTIAL` status, matching the `--wait` convention. |
| important | `cli/…/environment_backups.py`, `cli/README.md` | README promised `--wait` prints every non-completing constituent's reason, but the backup path never printed `errorMessage` despite the query selecting it; and `ok/failed/total` counted "row exists" as ok, so a `PARTIAL` snapshot printed `2/0/2`, contradicting itself. | `d209ce7` — `errorMessage` added to the protocol and printed; `ok` counts only `COMPLETED`. |
| important | `.github/workflows/ci.yml` | The rewritten matrix comment claimed the `backup` shard was excluded because every test carried `api_only` — false; **no** `shard_backup` test did. Removing the exclusion newly activated never-UI-exercised tests under Playwright. | `0fc0716` — comment rewritten accurately; **one** genuine `api_only` candidate marked with a reason. (The reviewer's claim of 4 candidates was wrong: the other four call dual-entrypoint driver methods and per `e2e-testing.md` must run under both.) |
| important | `backend/tests/e2e/test_backup_restore.py`, `ci.yml` | Worst-case waits summed to ~83 min against `timeout-minutes: 40`, so a slow run was killed by the runner instead of failing with the test's own diagnostic. | `0fc0716` — concurrent fanouts `asyncio.gather`ed, cleanup waits bounded, budgets pinned to named repo-calibrated constants: ~48 min worst case; `timeout-minutes` raised to 60 (a ceiling ~9× observed). |
| important | `frontend/src/components/environment/*` | Three mutations invalidated the wrong key set (delete cascades constituent backups **and** restores but only invalidated `ListEnvironmentBackups`; restore rewrote `Environment.config` without invalidating `GetEnvironment`; create didn't invalidate `ListBackups`) and all sat in the handler rather than `onSuccess`, violating `dev/guidelines/frontend/data-fetching.md`. | `0fc0716` — moved to `onSuccess` with the missing keys; 4 new tests, each verified to fail when its invalidation is dropped. |
| important | `EnvironmentDetailPage.tsx`, `EnvironmentBackupsTab.tsx` | The visible auto-refresh toggle did nothing on the Backups tab — it polled at a hardcoded 10s regardless, so the UI lied to the operator. | `0fc0716` — flag threaded to tab and row. |
| important | `EnvironmentBackupRow.tsx` | Told the operator `"backup no longer exists (deleted or expired)"`, but expiry never removes the row (no reaper); an expired constituent still reads `COMPLETED`. Contradicted the backend classifier and its own GraphQL description. | `0fc0716` — wording corrected in component and tests. |
| important | `services/backup/environment.py` | Two broad catches used `logger.warning` with `str(exc)`, laundering a `TypeError`/`AttributeError` regression into `constituent_errors` as a stackless one-liner indistinguishable from a legitimate per-instance conflict. | `d209ce7` — both use `logger.exception`. |
| important | docs (5 files) | `d209ce7` made the "premature-`COMPLETED` window" documentation stale in `backups-and-restores.md`, `dev/knowledge/backend/backup-restore.md`, ADR-0055 §2, `research.md`/`data-model.md`, the SDK docstring and the E2E helper docstring. ADR-0055's convergence check was also wrong (a constituent that fails at creation never gets a row). | `a17d973` — replaced with what is now true (see §5); invariant corrected to `len(backups) + len(constituent_errors) == len(deployment_snapshots)`; atomic capture and `_SharedTransaction` documented as design decisions. |
| important | `docs/…/styrminctl.md` | A "stub page … placeholder" banner disclaimed ~80 lines of accurate reference; the group list named six groups wrongly (`restore`/`upgrade` are not top-level); the `--cluster`/`--cluster-id` conflict claim was wrong (the guard is `cluster_id is not None and cluster != "default"`); the `--wait` timeout exit-1 path was undocumented. | `a17d973` |
| important | `docs/changelog.md`, `CHANGELOG.md` | No changelog entry for a major user-visible feature (new CLI group, new UI tab, 3 mutations, 4 queries) — sharpened by the removal of the `alpha-status.md` "coming before beta" bullet, which left the docs implying the feature exists without announcing it. | `a17d973` |
| important | `python_sdk/…/environment_backups.py` | The 900s `wait_for_restore` justification was the **inverse** of the code: it cited a reconciliation the service deliberately excludes restoring deployments from. A maintainer could have "fixed" an ordering that doesn't exist. | `a17d973` |
| important | `dev/knowledge/…`, `services/backup/environment.py` | Knowledge page omitted `EnvironmentRestoreNotFoundError` and `resolve_backup_target`/`BackupTarget`; docs claimed a stale fan-out ordering; a comment said driver fields degrade to empty strings but `driver_fingerprint` degrades to `None`. | `a17d973` |
| important | tests | A fully-decayed snapshot (all constituent rows individually deleted) was untested — the FR-014 case. | `d209ce7` — `test_a_snapshot_whose_constituents_were_all_deleted_stays_completed`. |
| suggestion | `backend/tests/e2e/*` | UI driver never verified *which* deployment page was open (order-dependent); page object hardcoded `error=None` while the API driver returned the real string (would pass `[api-chromium]`, fail `[ui-chromium]`); a leaked second deployment; a missing "button absent → not permitted" guard. | `0fc0716` |

### Deferred — recorded, not blocking

Ranked by the reviewers' severity. None affects correctness of the shipped behaviour.

| Severity | File | Finding |
|---|---|---|
| important | `api/definitions/backup/environment_backup.py:102`, `EnvironmentBackupRow.tsx:94`, `api_driver.py:90`, `cli/…:143` | Constituent status ships as `String!`, so the `ConstituentOutcome` vocabulary is re-derived in three languages, held together only by a conformance test. Resolving `outcome` server-side as a strawberry enum would give one closed value. This is the single place a parent and its children can visibly contradict. |
| important | `services/backup/environment.py:101`, `repository/environment_backup.py:28` | The non-terminal status set is encoded three times (bare string constants, enum tuples, prose). Changing a `BackupStatus` *value* would make every parent derive `FAILED` with no type error and no failing test. |
| important | `services/backup/service.py:58` | `BackupTarget` encodes total failure in-band as `(None, "", None)`, so `(None, "styrmin-x", None)` is representable. The two callers disagree on how they read it. `BackupTarget \| None` would make "unresolved" one check. |
| important | `services/backup/environment.py` | A Prefect dispatch failure is logged and counted but never recorded on the record. The `Backup` stays `PENDING` with nothing to advance it, so the guard reads `IN_PROGRESS` **forever** and blocks all further environment operations. Recoverable via the documented delete hatch, but the reason should be durable, not log-only. |
| important | `services/backup/environment.py:698` | The restore config fan-out wraps the whole loop in one `async with uow` and commits once, so a caught per-deployment failure still commits that deployment's pending `DEPLOYING`/`set_active_instance` mutations. A per-iteration savepoint would make the isolation claim true. Mirrors the pre-existing `services/environments.py` fan-out, so it is house convention rather than a regression. |
| important | `services/backup/environment.py:700` | No no-op suppression: restoring one application's data triggers a rolling redeploy of every *other* deployment in the environment even when the reverted config is byte-identical. `_deployment_already_at_config` exists for this but needs a `None`-config path. |
| important | `python_sdk/tests/test_environment_backups.py` | Only `delete` asserts which GraphQL document is sent; the mocked transport returns its canned payload regardless, so `create()` loading the *get* query would pass every test. |
| important | `python_sdk/…/environment_backups.py:148` | Polling timeout path unexercised (`max_wait=0` skips the loop); `elapsed += interval` never advances when `interval=0`, a latent infinite loop for direct SDK callers (the CLI is protected by `validate_positive`). |
| important | tests | ADMIN gating of restore is proven only at the GraphQL layer, not on SDK or CLI. |
| important | `cli/tests/test_environment_backups.py:588` | `restore-list` test asserts nothing about the counts it seeds — deleting those columns would fail nothing. Separately, `restore-list` prints no skip reasons at all, so an operator must run `restore-get` per row. |
| important | `EnvironmentBackupRestore.test.tsx:191` | The restore confirmation body is never content-asserted (the sibling *delete* dialog is), so the destructive warning could be emptied silently — on the more destructive action. |
| important | `backend/tests/unit/services/fakes.py:461` | `FakeDeploymentRepository.create()` returns without appending, making the unit-level FR-008 "count unchanged" assertion vacuous for the *creates* half. Verified by mutation. Real coverage lives in the propagation test. |
| important | `backend/tests/e2e/test_backup_restore.py` | The post-create status assertion accepts 3 of 5 enum values, so it cannot distinguish correct from broken. Now also stale: post-`d209ce7` a fresh non-empty snapshot can no longer read `COMPLETED`. |
| — | spec | **SC-006** (20 deployments enqueued within 60s) has zero coverage and no task in `tasks.md`. Never claimed as covered. |
| suggestion | `services/backup/environment.py:677` | `environment.config = environment_backup.environment_config` aliases one dict across two ORM rows; an in-place mutation of either silently edits the other in-session. `dict(...)`/`deepcopy` on assignment. |
| suggestion | `services/backup/environment.py:564` | N+1: `uow.deployments.find()` per snapshot while `find_all_by_environment` is called 18 lines later. Hoist and index by id. |
| suggestion | migration `c1d2e3f4a5b6` | No index on the four new FK columns; the `EXISTS` guard and every `selectinload` scan an unboundedly growing `backup` table. Project convention is no FK index (`Backup.schedule_id` has none), so this is a considered departure. |
| suggestion | `CONTEXT.md` vs frontend | Terminology drift: the UI says "Applications" / "application backup(s)" where `CONTEXT.md` lists "application" as a term to avoid for *deployment*. Partly pre-existing in `alpha-status.md`. |
| suggestion | `EnvironmentBackupRow.tsx:465` | A11y: per-row Restore button has no `aria-label` so every row exposes the name "Restore" (Delete does it right); the disabled reason lives only in `title` on a disabled button; `aria-expanded` with no `aria-controls`. |
| suggestion | various | Remaining type-design items (7–12), error-handling items (7–9), test hygiene (5–9, 15–16), and the marginal simplification items. Full detail in the agent reports; each is small and independent. |

---

## 5. What changed about the derived-status semantics

Worth calling out because the docs now say something different from when they were written.

**Before `d209ce7`:** the parent committed alone, so a fresh snapshot had zero children and
zero errors and therefore derived `COMPLETED` — reading terminal before any constituent
existed. This was documented as an accepted cost. It also opened the FR-009 guard hole.

**After `d209ce7`:** the capture is one transaction, so after it commits either the snapshot
does not exist or its children exist with it. A first read is now honest — `PENDING`,
`IN_PROGRESS` (children plus at least one creation error), or `FAILED` (all constituents
blocked at creation → zero children, `error_count > 0`). `COMPLETED` on a fresh snapshot now
means only the FR-011 config-only case, so `derive([], 0) == COMPLETED` remains correct and
load-bearing. FR-014 still holds: deleted constituents vanish and the snapshot stays
`COMPLETED` and restorable. The surviving caveat is about *coverage*, not a status window,
and its invariant is `len(backups) + len(constituent_errors) == len(deployment_snapshots)`.

---

## 6. Autonomous decisions

1. **Chunking.** Split Phase 2 three ways and Phase 3 two ways along surface seams (both
   exceeded the ~10-task / ~15-file threshold); kept all other phases whole. Never ran two
   implementation subagents concurrently.
2. **Fixed five "important" findings, not just the criticals.** The workflow prescribes
   fixing high-severity findings inline and recording the rest. I also fixed importants that
   were *outright factual errors in shipped artifacts* (the CLI exiting 0 on `FAILED`, the
   `README`/`ci.yml`/`styrminctl.md` inaccuracies) or CI-cost regressions this change
   introduced. Everything design-level or pre-existing was recorded instead. **Worth
   revisiting:** the deferred list's first six "important" rows, especially the dispatch
   failure that wedges an environment `IN_PROGRESS` with the reason only in logs.
3. **Re-ran both E2E variants after `d209ce7`.** The recorded pass predated a change to the
   transaction boundary of both create and restore, so the original evidence no longer
   described the shipped code. Constitution §V evidence in §3 is the re-run.
4. **Raised the e2e job `timeout-minutes` 40 → 60** rather than cutting individual waits
   below repo-calibrated sibling values. Justified by measured data (~48 min worst case,
   ~9× observed), but it is a CI-budget change worth a second opinion.
5. **Accepted three subagent overrides of my own briefs**, each backed by evidence: the
   `"placeholder"` fix had to extend to `create_backup`/`create_restore` (proven by a real
   `UNIQUE constraint failed`); only one test was a genuine `api_only` candidate, not the
   four reported; and `api_driver.py:725`'s `except ResourceNotFoundError` is reachable, not
   unreachable — the reviewer was wrong.
6. **Grouped the local-pass evidence table per test module** with counts and verbatim
   aggregate lines rather than one row per test; ~330 tests would otherwise produce a
   300-line table. E2E rows are individual as required.
7. **Left `research.md` / `data-model.md` amended rather than rewritten.** `d209ce7` changed
   the design those documents describe; the amendments follow their existing style. A full
   `speckit.reconcile.run` pass was not performed.
8. **Did not fix the two pre-existing CLI telemetry failures** (they assume a non-root uid)
   or the ~12 stale-`prefect.db` agent tests. Both are outside this feature.

---

## 7. Suggested next steps

1. **Open a PR** — the branch is clean, all 41 tasks complete, all gates green, both E2E
   entrypoints verified on the shipped tree.
2. **Triage the deferred "important" findings** (§4). The dispatch-failure wedge and the
   `String!` constituent status are the two with real operational consequences; the rest are
   type-design and test-hardening.
3. **Decide on SC-006.** It has no coverage and no task. Either add a task or strike it
   from the spec — right now it is an unmet success criterion.
4. **Consider `speckit.opsmill.extract`** to fold the durable lessons into
   `dev/knowledge/` — chiefly the `@inject`/`Depends(get_manager)` requirement, the
   `_SharedTransaction` pattern for fan-outs that must be atomic yet per-item isolated, and
   the `generate-validate`-reverts-unstaged-codegen trap.
5. **Optional:** run `speckit.reconcile.run` so `research.md` / `data-model.md` fully reflect
   the atomic-capture design rather than carrying amendments.
