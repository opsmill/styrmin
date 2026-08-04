# Implementation Report: Configurable Backup Retention TTL

**Status**: DONE

| | |
|---|---|
| Feature | 016-backup-retention-ttl — Configurable Backup Retention TTL |
| Spec directory | `specs/016-backup-retention-ttl/` |
| Base commit | `9a12085` (alignment: verify spec against source PRD) |
| Head commit | `985afae` (fix: make BACKUP_TTL_PATTERN self-anchoring) |
| Commits produced | 10 |
| Diff | 55 files changed, 3019 insertions(+), 140 deletions(-) |
| Tasks | 33 of 33 complete (`[X]`), 0 remaining |
| Wall clock | 2026-08-03T11:00:40+00:00 → 2026-08-03T14:36:10+00:00 (~3h 35m) |

---

## 1. Chunk-by-chunk ledger

Chunks were derived from the phase headings in `tasks.md`. Phase 3 was split at the
E2E seam (see §6, decision D1). Each chunk ran in a clean-context subagent; chunks
ran strictly one at a time because they share files.

### Chunk 1 — Phase 1: Setup

- **Tasks**: 1 (T001) — ✅ 1 / ⚠️ 0 / ❌ 0
- **Commit**: `8077a3a`
- **Flagged upward**: `plan.md` records Alembic in use (17 revisions), contradicting
  `CLAUDE.md`'s `metadata.create_all()` claim. Immaterial here — `config` is an
  existing JSON column, so no migration was needed. Left unfixed as out of scope;
  see §5 deferred item R-13.

### Chunk 2 — Phase 2: Foundational

- **Tasks**: 7 (T002–T008) — ✅ 7 / ⚠️ 0 / ❌ 0
- **Commit**: `039159c` (17 files)
- **Flagged upward**:
  - The schema delta is **5** SDL additions, not the 4 listed in
    `contracts/graphql-delta.md`. The extra is `UpdateDeploymentInput.backupTtl` —
    Strawberry flattens inheritance into SDL, so the `DeploymentConfigInput` field
    materialises twice. The contract does state the field flows to `updateDeployment`
    via inheritance, so this is contract-consistent, not new surface. Accepted.
  - **Tooling trap propagated to all later chunks**: `uv run invoke lint` includes
    `generate-validate`, which runs `git checkout -- python_sdk/.../_generated/`
    whenever it sees a diff — so running lint with *uncommitted* regenerated
    artifacts silently reverts them. Cost this agent two cycles.
  - Frontend requires Node 22 (`/root/.local/node22/bin`); default `node` is v18 and
    cannot start Vitest.

### Chunk 3 — Phase 3a: US1 implementation + non-E2E tests

- **Tasks**: 8 (T009–T016) — ✅ 8 / ⚠️ 0 / ❌ 0
- **Commit**: `09b51d0` (12 files)
- **Flagged upward**:
  - **`expires_at` is recorded on both terminal branches**, not only `Completed`.
    T014's parenthetical implied Completed-only, but a PartiallyFailed backup *is*
    stored and *does* expire, and this workflow folds PartiallyFailed into the FAILED
    branch — Completed-only would drop a real expiry. Accepted as a widening in the
    direction of correctness.
  - `test_velero_bsl_resources.py` (not named in T015) also constructs `VeleroBackup`
    directly and needed an explicit `ttl=`. Constructor argument only, no assertion
    touched, so SC-004 holds.
  - T009/T010 passed on first execution rather than failing first, because their
    subjects landed in the already-committed Phase 2. An artifact of the chunk
    boundary (decision D1), not a TDD violation.

### Chunk 4 — Phase 3b: US1 E2E

- **Tasks**: 1 (T017) — ✅ 1 / ⚠️ 0 / ❌ 0
- **Commit**: `fd05182`
- **Flagged upward**:
  - **The command T017 prescribes cannot pass as written**, nor can the identical
    recipe in `quickstart.md` §4. Running the bare node id in one pytest session
    passes `[api-chromium]` then errors `[ui-chromium]` in fixture setup on a
    duplicate `create_cluster('test-cluster')`, because `styrmin_resources`
    re-creates the cluster per `driver_mode`. CI sidesteps this by giving each
    entrypoint its own job. Worked around with two `-k`-split sessions; both passed.
    Doc corrected under T033 (§6, decision D3).
  - `assert_velero_backup_uses_bsl` was split rather than extended (extracted
    `read_velero_backup` + a sibling `assert_velero_backup_ttl`) so the existing name
    stays honest for its two callers in `test_infrahub_backup_restore.py`.
  - No product bug surfaced: `spec.ttl` reads back byte-identical to `"2160h"` (the
    API server stores CRD strings verbatim — no Go normalisation to `2160h0m0s`).

### Chunk 5 — Phase 4: US2 (deployment-scope override)

- **Tasks**: 3 (T018–T020) — ✅ 3 / ⚠️ 0 / ❌ 0
- **Commit**: `79f8582`
- **Flagged upward**:
  - T019's conditional resolved to **no change**:
    `test_update_deployment_input_introspection.py` derives its expected field set
    from `DeploymentConfig.model_fields` rather than enumerating literals, so
    `backup_ttl` was already covered by the schema walk.
  - `backupTtl` registered in the **`storageRuntime`** config-diff section — there is
    no dedicated backup section in `SectionId`; it sits alongside
    `dbSize`/`standardStorage`.
  - **Pre-existing gap spotted and correctly left alone**: `config-diff.ts` never
    diffs `fastStorage`, and `deployment-input.test.ts`'s exhaustive field list omits
    it — a `fastStorage` change is currently invisible in config diffs. See §5, R-10.
  - The `rtk` shell hook mangles ESLint resolution on plain `pnpm lint` (bogus
    "ESLint 6.4.0 couldn't find a configuration file"); `rtk proxy pnpm lint` gives
    the real result.

### Chunk 6 — Phase 5: US4 (expiry visible in UI and CLI)

- **Tasks**: 5 (T021–T025) — ✅ 5 / ⚠️ 0 / ❌ 0
- **Commit**: `a921cd7` (7 files) — **committed by the orchestrator**, see §6 D2
- **Flagged upward**:
  - The chunk subagent was killed by a transient **API 529** twice: once mid-run
    after writing all five task targets but before verifying any of them, then again
    immediately on resume. Nothing was ticked or committed and **no test had been
    run** at that point. The orchestrator verified all the written work
    independently, then ticked and committed it. Full evidence in §4.
  - Critique P2's accessibility requirement was verified in source rather than taken
    on report: `title={retentionHint}` **plus** `<span className="sr-only">`, so the
    applied TTL reaches keyboard and screen-reader users instead of being hover-only.
  - `NOT_RECORDED = "—"` confirmed as the em-dash fallback on both CLI paths.

### Chunk 7 — Phase 6: US3 (invalid value rejected loudly)

- **Tasks**: 2 (T026–T027) — ✅ 2 / ⚠️ 0 / ❌ 0
- **Commit**: `8d087e6`
- **Flagged upward**:
  - **A real product bug, found and fixed.** Writing T027 exposed that four of the
    five config surfaces discarded Pydantic's message when wrapping it into the
    `Invalid*ContextError` family — clients saw only
    `"The context configuration is invalid"`, with no field name and no syntax hint.
    FR-004 requires that hint *"at every input surface"*; only the deployment-update
    path honoured it. Fixed with five one-line `str(e)` pass-throughs in
    `context/validators.py`, `services/clusters.py`, `services/environments.py` (×2),
    `services/deployment.py`. The subagent explicitly flagged this for veto; the
    orchestrator reviewed the diff and accepted it (§6, decision D4).
  - `extensions.code` for this rejection is `VALIDATION_ERROR`.

### Chunk 8 — Phase 7: Polish & Cross-Cutting Concerns

- **Tasks**: 6 (T028–T032, plus T033 added by the orchestrator) — ✅ 6 / ⚠️ 0 / ❌ 0
- **Commit**: `5d7a5ae` (5 files)
- **Flagged upward**:
  - The agent caught two of its own draft doc errors before shipping: deployment
    manifests key `spec.config` by **camelCase** (`backupTtl`), and
    `environment(environmentName:)` cannot resolve without cluster context
    (`resolve_cluster` raises `AmbiguousIdentifierError`), so the example passes
    `clusterName`.
  - **A second broken quickstart recipe**, beyond the one assigned as T033: §3's
    `pnpm test -- BackupExpiry` silently drops the filter and runs all 58 files / 408
    tests. Correct form is `pnpm test BackupExpiry`. Fixed in the same change.
  - **Cosmetic spec-vs-code drift, deliberately not fixed**: FR-010/T024 say an
    "`Expires`" column, but `cli/.../backups.py` uses `expires_at` to match the
    file's existing `started_at`/`completed_at` convention. Changing it would break
    landed tests for no user benefit; the docs never name the column. See §5, R-08.
  - SC-004 confirmed: the only assertions removed from pre-existing tests were the
    two `spec.ttl == "720h"` builder pins, relocated to
    `test_backup_ttl_resolution.py`. Everything else additive.

### Review fix pass (Phase 6 of the workflow)

- **Findings addressed**: 11 grouped items (5 high, 4 medium, 2 batches of low)
- **Commits**: `83e86e3`, `985afae`
- Full detail in §5.

### E2E re-validation (post-fix)

- **Commit**: none — no source change was required.
- The review fixes changed `backend/tests/e2e/test_backup_restore.py` (+129/−87) and
  `drivers/api_driver.py` (+6) *after* T017's recorded pass, so that evidence was
  stale. Both variants were re-run against current HEAD and passed. Evidence in §4.

---

## 2. Tasks not completed

**None.** All 33 tasks in `tasks.md` are `[X]`.

---

## 3. Local-pass evidence

Every test added or modified by this run, with an observed pass. No `MISSING` rows.

Environment shorthand used below:

- **BE** — repo worktree, Python 3.14.3 via `uv`, pytest 9.0.2, uid 0. No cluster,
  docker, or DB required (functional tests use in-memory SQLite via the `session`
  fixture).
- **FE** — as BE plus `export PATH=/root/.local/node22/bin:$PATH` (Node v22.16.0;
  default v18 cannot start Vitest), Vitest 4.1.0.
- **E2E** — self-bootstrapping session `vcluster` fixture; vcluster 0.33.0, docker
  server 29.2.1. Per-run cluster id and kubeconfig given inline.

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/unit/services/test_backup_ttl_resolution.py` (7 tests, T009) | unit | `uv run pytest backend/tests/unit/services/test_backup_ttl_resolution.py -v` | 2026-08-03T11:48:44+00:00 | BE | `7 passed in 0.02s` |
| `test_environment_update_propagation.py::test_update_environment_input_backup_ttl_round_trip`, `::…_preserved_when_resubmitted`, `::test_update_environment_omitting_backup_ttl_clears_it`, `::test_update_environment_input_covers_every_environment_config_field` (T010) | functional | `uv run pytest backend/tests/functional/graphql/test_environment_update_propagation.py -v -k "backup_ttl or covers_every"` | 2026-08-03T11:48:52+00:00 | BE | `4 passed, 23 deselected in 0.22s` |
| `test_velero_resources.py::TestVeleroBackup::test_render_basic` / `::test_render_with_hooks`; `test_backup_builders.py::TestBuildVeleroBackup::test_basic_backup` / `::test_backup_with_hooks`; `test_velero_bsl_resources.py::test_velero_backup_without_storage_location` / `::…with_storage_location` (T015) | unit | `uv run pytest backend/tests/unit/agent/test_velero_resources.py backend/tests/unit/agent/test_backup_builders.py backend/tests/unit/agent/test_velero_bsl_resources.py -v` | 2026-08-03T11:49:00+00:00 | BE | `27 passed in 0.03s` |
| `src/__tests__/EnvironmentConfigurationTab.test.tsx` (24 tests, incl. 2 new, T016) | component | `pnpm test --run src/__tests__/EnvironmentConfigurationTab.test.tsx` | 2026-08-03T11:49:07+00:00 | FE | `Test Files  1 passed (1)` / `Tests  24 passed (24)` |
| `test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]` (T017, **superseded** by the re-validation row below) | e2e | `sleep infinity \| uv run pytest "…::test_backup_and_restore_lifecycle" -k api-chromium -v -s --pdb` | 2026-08-03T12:20:32+00:00 | E2E; vcluster `pytest-f7bd2cd8-…`, `/tmp/pytest-of-root/pytest-1108/vcluster0/kubeconfig` | `1 passed, 1 deselected, 1 warning in 438.78s (0:07:18)` |
| `test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]` (T017, **superseded**) | e2e | same, `-k ui-chromium` | 2026-08-03T12:12:34+00:00 | E2E; vcluster `pytest-6d156b52-…`, `/tmp/pytest-of-root/pytest-1107/vcluster0/kubeconfig` | `1 passed, 1 deselected, 1 warning in 322.81s (0:05:22)` |
| `test_backup_ttl_resolution.py::test_deployment_scope_wins_over_environment_and_cluster`, `::test_cluster_scope_applies_when_deployment_and_environment_unset`, `::test_null_at_deployment_scope_skips_to_the_environment_hop`, `::test_null_at_deployment_and_environment_skips_to_the_cluster_hop`, `::test_null_at_every_scope_falls_back_to_the_built_in_default` (T018) | unit | `uv run pytest backend/tests/unit/services/test_backup_ttl_resolution.py -v` | 2026-08-03T12:26:31+00:00 | BE | `12 passed in 0.02s` |
| `test_deploy_input_propagation.py::test_deploy_backup_ttl_propagates_to_config`; `test_update_deployment_input_propagation.py::test_update_deployment_input_field_propagates[backup_ttl]` / `::…_preserved_when_resubmitted` / `::test_update_deployment_omitting_backup_ttl_clears_it`; `test_update_deployment_input_introspection.py::test_update_deployment_input_field_coverage` (T019) | functional | `uv run pytest backend/tests/functional/graphql/test_deploy_input_propagation.py …test_update_deployment_input_introspection.py …test_update_deployment_input_propagation.py -v` | 2026-08-03T12:27:25+00:00 | BE | `39 passed in 2.71s` |
| `src/lib/deployment-input.test.ts > … > carries backup_ttl through to backupTtl`; `… > converts an empty config into an input with every field undefined`; `src/lib/config-diff.test.ts > … > attributes backupTtl changes to the storageRuntime section`; `… > emits an add entry when backupTtl goes from unset to set` (T020) | unit | `pnpm test --run --reporter=verbose src/lib/config-diff.test.ts src/lib/deployment-input.test.ts` | 2026-08-03T12:28:20+00:00 | FE | `✓ src/lib/deployment-input.test.ts > deploymentConfigToInput > carries backup_ttl through to backupTtl 0ms` |
| `backend/tests/functional/graphql/test_backup_fields.py` (3 tests, T021) | functional | `uv run pytest backend/tests/functional/graphql/test_backup_fields.py -v` | 2026-08-03T12:47:—+00:00 | BE; **verified by the orchestrator** after the chunk agent died pre-verification | `3 passed in 0.21s` |
| `cli/tests/test_backups.py` (30 tests, incl. `::test_backups_get_without_retention_metadata`, T022) | unit | `uv run pytest cli/tests/test_backups.py -v` | 2026-08-03T12:47:—+00:00 | BE; **verified by the orchestrator** | `30 passed in 0.23s` |
| `frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx` (5 tests, T023) | component | `pnpm test --run src/__tests__/deployment-detail/BackupExpiry.test.tsx` | 2026-08-03T12:53:31+00:00 | FE; **verified by the orchestrator** | `Test Files  1 passed (1)` / `Tests  5 passed (5)` |
| `test_backup_fields.py` re-run after `ruff format` | functional | `uv run pytest backend/tests/functional/graphql/test_backup_fields.py -q` | 2026-08-03T12:55:—+00:00 | BE | `3 passed in 0.20s` |
| `test_base_config_section.py` — 61 tests incl. `::test_validate_backup_ttl_accepts_positive_go_duration[8 params]`, `::test_validate_backup_ttl_rejects_invalid_value[6 params]`, `::test_config_models_{accept,reject}_*` (T026) | unit | `uv run pytest backend/tests/unit/context/test_base_config_section.py -v` | 2026-08-03T13:19:19+00:00 | BE | `61 passed in 0.06s` |
| `test_environment_update_propagation.py::test_update_environment_rejects_malformed_backup_ttl` (T027) | functional | `uv run pytest "backend/tests/functional/graphql/test_environment_update_propagation.py::test_update_environment_rejects_malformed_backup_ttl" -v` | 2026-08-03T13:19:28+00:00 | BE | `1 passed in 0.09s` |
| `backend/tests/unit/workflows/test_backup_workflow_ttl.py` (12 tests, review fix F10a) | unit | `uv run pytest backend/tests/unit/workflows/test_backup_workflow_ttl.py -q` | 2026-08-03T14:04:28+00:00 | BE; reaches `execute_backup_workflow` via `Flow.fn`, bypassing the Prefect engine | `12 passed in 0.26s` |
| `test_backup_service.py::TestUpdateBackupStatus::test_metadata_updates_merge_and_preserve_existing_keys` / `::…_reassign_the_attribute_not_mutate_it` / `::…_on_a_row_with_no_metadata` (F10b) | unit | `uv run pytest backend/tests/unit/services/backup/test_backup_service.py -q` | 2026-08-03T14:01:49+00:00 | BE | `33 passed in 0.06s` (was 30) |
| `test_base_config_section.py` +21 (F4 rejects `"720h\n"`, `"٧٢٠h"`, `" 720h"`; F5 Go-overflow boundary) | unit | `uv run pytest backend/tests/unit/context/test_base_config_section.py -q` | 2026-08-03T14:00:35+00:00 | BE | `86 passed in 0.07s` (was 65) |
| `test_backup_ttl_resolution.py` +5 (F7 non-string / invalid / overflowing scope values fall through loudly) | unit | `uv run pytest backend/tests/unit/services/test_backup_ttl_resolution.py -q` | 2026-08-03T14:01:17+00:00 | BE | `17 passed in 0.03s` (was 12) |
| `BackupExpiry.test.tsx` +1 (F9d — em-dash rather than "Invalid Date") | component | `pnpm vitest run src/__tests__/deployment-detail/BackupExpiry.test.tsx` | 2026-08-03T14:05:17+00:00 | FE | `PASS (6) FAIL (0)` (was 5) |
| All touched backend test files, re-run after the F4 anchor change | unit + functional | `uv run pytest …test_base_config_section.py …test_backup_ttl_resolution.py backend/tests/unit/workflows backend/tests/unit/services/backup …test_backup_fields.py -q` | 2026-08-03T14:19:29+00:00 | BE | `293 passed in 0.45s` |
| `test_backup_restore.py::test_backup_and_restore_lifecycle[api-chromium]` — **re-validated on current HEAD** | e2e | `sleep infinity \| uv run pytest "…::test_backup_and_restore_lifecycle" -k api-chromium -v -s --pdb 2>&1 \| tee /tmp/ttl-e2e-api-revalidate.log` | 2026-08-03T14:28:17+00:00 | E2E; vcluster `pytest-a32655ab-aac9-4092-acf1-01c7fc308b23`, `/tmp/pytest-of-root/pytest-1121/vcluster0/kubeconfig` | `1 passed, 1 deselected, 1 warning in 350.35s (0:05:50)` |
| `test_backup_restore.py::test_backup_and_restore_lifecycle[ui-chromium]` — **re-validated on current HEAD** | e2e | same, `-k ui-chromium`, `\| tee /tmp/ttl-e2e-ui-revalidate.log` | 2026-08-03T14:34:48+00:00 | E2E; vcluster `pytest-3e407c69-3228-43dd-8202-8bd2a61e8b44`, `/tmp/pytest-of-root/pytest-1122/vcluster0/kubeconfig` | `1 passed, 1 deselected, 1 warning in 354.45s (0:05:54)` |

### Mutation testing of the review fixes

The fix agent did not merely observe passes — it reverted three fixes simultaneously
and confirmed exactly the corresponding three tests failed, proving the new tests
catch the regressions rather than passing alongside them:

```
2026-08-03T14:04:15+00:00 → "3 failed, 9 passed in 0.30s"; failures =
  test_expiration_is_recorded_on_both_terminal_branches[partially-failed-branch]
  test_partial_config_read_does_not_claim_the_default_was_applied
  test_cluster_read_failure_keeps_the_environment_bsl
```

The frontend `isNaN` guard was mutation-checked the same way
(2026-08-03T14:05:27+00:00 → `Tests 1 failed | 5 passed (6)`).

### Cluster-side confirmation (E2E re-validation, `api-chromium`)

Captured live from the vcluster while the backup was in progress:

```
NAME                                           PHASE        TTL     EXPIRATION             BSL
styrmin-4c825cd4-f6a8-4e9e-88ae-054f20d5ea81   InProgress   2160h   2026-11-01T14:26:29Z   styrmin-bsl-test-bsl

14:26:26.193 | INFO | Flow run 'proficient-caterpillar' - resolved backup TTL 2160h from environment scope for backup 4c825cd4-f6a8-4e9e-88ae-054f20d5ea81
```

`spec.ttl == 2160h`, expiry exactly 90 days (2160h) after creation, the environment's
BSL preserved, and the workflow log naming the `environment` scope — the full US1
chain proven on real infrastructure.

For the `ui-chromium` variant the out-of-band collector resolved a stale kubeconfig
path (the torn-down `pytest-1121`) and captured nothing. This is a gap in the
side-channel script only, not in coverage: `assert_velero_backup_ttl`,
`assert_velero_backup_uses_bsl`, `recorded_backup.ttl == "2160h"` and
`recorded_backup.expires_at is not None` all execute inside the test body against the
live CRD, so the reported PASS is itself the proof.

### Suite baselines (final, at `985afae`)

| Suite | Command | Result | Notes |
|---|---|---|---|
| Backend unit + functional | `uv run pytest backend/tests/unit backend/tests/functional -q` | `12 failed, 1847 passed, 2 skipped, 1 warning in 326.72s` | +45 tests over the 1802 baseline, **zero new failures** |
| Frontend | `pnpm test` | `Test Files 58 passed (58)` / `Tests 409 passed (409)` | +1 test; stable over 4 further consecutive runs |
| CLI | `uv run pytest cli/tests -q` | `2 failed, 271 passed in 21.75s` | no new failures |
| E2E collection | `uv run pytest backend/tests/e2e --collect-only -q` | `155 tests collected` | count held |
| Gate | `uv run invoke lint` | exit `0` | ruff format + check, `ty`, rumdl (74 files), 197/197 GraphQL operations, generated-types validation |
| Codegen drift | `uv run invoke generate` then `git diff --exit-code` | exit `0` | clean; re-verified after lint |

**Pre-existing failures, reproduced unchanged and not caused by this work** (both
independently confirmed on a stashed pristine tree during chunk 2):

- 12 backend tests — `RuntimeError: Timed out while attempting to connect to
  ephemeral Prefect API server` in `test_render_value_template_env_vars.py` (5),
  `test_render_value_template_container_overrides.py` (5),
  `agent/tasks/test_apply_state_flow.py` (2). A sandbox limitation.
- 2 CLI tests — `telemetry/test_store.py::test_unwritable_dir_falls_back_to_ephemeral_id`
  and `telemetry/test_telemetry_command.py::test_commands_succeed_under_unwritable_dir`
  chmod a directory unwritable, which uid 0 bypasses.

---

## 4. Review findings

Six specialist agents reviewed `9a12085..HEAD` in parallel: code quality, tests,
error handling, comments/docs, type design, and simplification. **No critical
findings.** Every agent was required to substantiate findings with a concrete failure
path and to downgrade anything it could not.

### Fixed inline (commits `83e86e3`, `985afae`)

| Sev | Area | File | Finding | Fix |
|---|---|---|---|---|
| high | errors | `workflows/templates/backup.py` | **Regression in pre-existing behaviour**: the new `uow.clusters.get()` was inserted inside the swallow-all `try` *before* the `storage_location` assignment, so a cluster-read failure skipped it and sent the backup to the cluster-default BSL instead of the environment's configured one | `storage_location` now assigned from `env` before the cluster read |
| high | comments | `api/definitions/backup/backup.py` | The `expiresAt` description claimed failed backups "never receive an expiration" — false, since PartiallyFailed folds into FAILED *and* records expiry. Shipped verbatim into `schema.graphql`, the SDK, and frontend types | Description rewritten; artifacts regenerated |
| high | comments | `workflows/templates/backup.py` | Two comments in one file contradicted each other about PartiallyFailed expiry, inviting a maintainer to delete the live FAILED-branch write as dead code | Both comments reconciled with the code and `dev/knowledge` |
| high | code, simplify | `services/backup/ttl.py` | **Validation bypass, verified by execution**: `$` permits a trailing newline and `\d` is Unicode-aware, so `"720h\n"` and `"٧٢٠h"` were both accepted and reached Velero as an undecodable `spec.ttl` — violating SC-003 | `fullmatch` + `\A…\Z` + `[0-9]` in both regexes; 3 reject cases added |
| high | tests | — | `execute_backup_workflow` — the only place resolution, `ttl_source` recording and `expires_at` capture happen — had **no test at all** | New `test_backup_workflow_ttl.py` (12 tests), mutation-verified |
| high | tests | `services/backup/service.py` | `metadata_updates` was untested, so the in-place-mutation trap the code comment warns about was unguarded; `test_backup_fields.py`'s docstring wrongly claimed to cover it | 3 merge tests added; docstring corrected |
| medium | errors | `services/backup/ttl.py` | `8760000h` accepted but overflows Go's int64 nanoseconds (~`2562047h`), so Velero cannot decode it; the module docstring's "subset Velero parses" claim was false above that bound | Ceiling `MAX_BACKUP_TTL_HOURS = 2562047` (inclusive) enforced on the summed total; docstring corrected |
| medium | errors, code | `workflows/templates/backup.py` | The `config_read_failed` warning unconditionally claimed the built-in default was applied — false on a partial read, and contradicted by the INFO line after it | Claim gated on `ttl_source == "default"`; partial-read branch names the contributing scope |
| medium | types, errors | `services/backup/ttl.py` | `str(value)` laundered any JSON type into a plausible TTL that never passed validation (reachable via a hand-edited row or restored dump) | A scope contributes only when its value is a `str` that validates; otherwise falls through with a WARNING. Never raises |
| medium | simplify | `tests/e2e/drivers/api_driver.py` | **api/ui parity break**: `update_environment_via_form` did not carry `backupTtl` while the UI path did, so a TTL would be silently cleared under `[api-chromium]` but preserved under `[ui-chromium]` | `backupTtl` carried through |
| medium | comments | `docs/…/backups-and-restores.md` | Three inaccuracies: an overstated "no CLI flag" claim self-contradicted 50 lines later; a promise that each backup answers "why" when `ttl_source` is on no surface; and a cross-reference to issue #304, which is about a different bug | All three corrected; a per-surface casing table added (see §6 D5) |
| low | errors, code | `services/applications.py` | The one config-validation site still raising bare `InvalidContextError()`, losing the new hint | `InvalidContextError(str(e)) from e` |
| low | errors, types | `api/definitions/backup/backup.py` | The non-string `expires_at` branch returned `None` with no log while the adjacent `ValueError` branch warned | Non-string case now logged with backup id and value |
| low | errors | `workflows/templates/backup.py` | A **Completed** backup reporting no expiration silently lost FR-006's record | Warns for that case; the Failed case stays quiet |
| low | errors | `pages/deployments/DeploymentDetailPage.tsx` | `new Date(...)` rendered the literal "Invalid Date" instead of "—" | `isNaN(date.getTime())` guard; mutation-verified |
| low | tests | `tests/e2e/test_backup_restore.py` | The test wrote `backup_ttl` to the **session-scoped** environment without reverting, leaking a 2160h policy to any future `shard_backup` test | Reverted in a `finally`; confirmed executing in both re-validation runs |
| low | comments | `cli/…/backups.py` | The `NOT_RECORDED` comment repeated the failed-backup inaccuracy | Corrected |

### Deferred (recorded, not fixed)

| Ref | Sev | Finding | Why deferred |
|---|---|---|---|
| R-01 | medium | A `BackupMetadata(TypedDict, total=False)` would type the `metadata_` key contract. Real risk: the Prefect Variable spells the concept `"expiration"` while `metadata_` uses `"expires_at"`, so a writer carrying the upstream spelling through would type-check and silently break `expiresAt` forever | Touches a shared signature used well beyond this feature; deserves its own change. F10a/F10b now cover the specific live paths |
| R-02 | medium | Pydantic's full repr reaches API clients: model class name, `input_value=`, an `errors.pydantic.dev` URL, and multi-line text unlike every other typed error | Pre-existing pattern this feature extended to four more surfaces, not introduced by it. Both reviewers confirmed it is **not** a secret leak — env-var rules raise before Pydantic wraps them, and `input_value` only echoes the caller's own input. Redesigning it is out of scope |
| R-03 | low | ~Half of `test_base_config_section.py`'s cases are combinatorial padding — all three config models share one inherited validator with no override, so 8×3 and 6×3 add nothing over 1×N + N×1 | Removing passing tests is pure churn with zero coverage delta. Noted so the count is not mistaken for coverage |
| R-04 | low | `config_read_failed` covers exceptions but not `None` returns, so a deleted row is indistinguishable from "no policy set" in both log and audit record | Narrow race; the resulting TTL is the safe default either way |
| R-05 | low | Two `update_backup_status(IN_PROGRESS)` round-trips 70 lines apart; resolving before the first would collapse them | Trade-off: it delays IN_PROGRESS marking by the config read. Current shape may be deliberate |
| R-06 | low | `backupTtl` has no `impact-rules.ts` entry, so no consequence line explains "future backups only" | Same gap `runtimeClass` already has; a UI-copy task |
| R-07 | low | No mutation-level test that `createCluster` accepts/rejects `backup_ttl` through its untyped `config: JSON` arg | The shared validator is proven; only the cluster surface's wiring is unproven |
| R-08 | low | FR-010 says an "`Expires`" column; the CLI uses `expires_at` to match the file's `started_at`/`completed_at` convention | Cosmetic spec-vs-code drift. Changing it breaks landed tests for no user benefit |
| R-09 | low | `BackupExpiry.test.tsx` never renders the real failed-backup shape (`ttl` set, `expiresAt` null), so nothing proves the sr-only hint survives a missing expiry | No concrete bug named |
| R-10 | low | **Pre-existing**: `config-diff.ts` never diffs `fastStorage`, so a `fastStorage` change is invisible in config diffs | Out of scope; predates this feature |
| R-11 | low | **Pre-existing**: `styrminctl deployments create --config` raises `AttributeError` for **any** `--config` value (a plain dict is passed where the SDK calls `.model_dump()`) | Found while fixing docs; unrelated to this feature. **Worth its own ticket** |
| R-12 | low | **Pre-existing flake**: `config-diff.test.ts:387` asserts `elapsedAverage < 5` ms — a wall-clock performance assertion that failed 2 of 8 runs under load | Unrelated to this change. **Worth its own ticket** |
| R-13 | low | **Pre-existing doc inconsistency**: `plan.md` records Alembic in use (17 revisions) while `CLAUDE.md` claims `metadata.create_all()` | Immaterial here (no migration needed); a repo-hygiene fix |

---

## 5. Autonomous decisions

**D1 — Split Phase 3 into two chunks at the E2E seam.** T017 boots a vcluster and
takes ~6 min per variant; isolating it meant a vcluster failure could not take the
eight-task US1 implementation chunk down with it. Cost: T009/T010 could not go red
first, because their subjects landed in the already-committed Phase 2. Reversible by
merging the chunks on a re-run.

**D2 — The orchestrator verified and committed chunk 6's work itself.** The subagent
was killed by a transient API 529 twice, the second time immediately on resume,
having written all five task targets but verified none. Rather than hammer an
overloaded API or re-dispatch fresh onto files that already held uncommitted work
(conflicting-write risk), the orchestrator ran every test, checked the two
substantive requirements in source (critique P2 accessibility, the `—` fallback),
formatted, ticked, and committed. **This deviates from the skill's protocol**, which
says the subagent commits its own work. Recorded here because it is the one place the
normal chain of custody was broken; the commit message records it too.

**D3 — Added T033, a task not in `tasks.md`.** T017's own prescribed command and
`quickstart.md` §4 both specify a recipe that demonstrably cannot pass. Constitution
§VII makes in-change doc accuracy non-negotiable, and leaving a failing recipe would
strand the next person. Chunk 8 then found a second broken recipe (§3's vitest
filter) and fixed that too.

**D4 — Accepted a production change from a test-only chunk.** Chunk 7 fixed four
config surfaces that discarded Pydantic's validation message, and flagged it for
veto. Not vetoed: FR-004 requires the hint "at every input surface", so without it
the phase goal is unmet by definition and T027 cannot assert what it specifies. The
change is five one-line `str(e)` pass-throughs matching an existing in-codebase
pattern. It also improves every config validation error, not only this feature's.

**D5 — Accepted the fix agent's correction of two of my own briefing claims.** I told
it `styrminctl deployments create --config` sets `backupTtl` and that the help text
accepts camelCase generally. It verified both are wrong (see R-11; and raw-JSON
surfaces need snake_case because `BaseConfigSection` sets `extra="forbid"` with no
alias generator) and documented a per-surface casing table instead. Better than what
was asked for.

**D6 — Re-ran the E2E after the review fixes.** Those fixes changed the E2E file by
+129/−87 — a substantial restructure, not the small `finally` addition assumed. The
T017 evidence therefore predated the code under test. Both variants were re-run on
current HEAD and passed with no source change; the superseded rows are retained in §3
and marked.

**D7 — Left the `.gitignore` modification uncommitted throughout.** The user chose
this at preflight. Every chunk agent was instructed to stage explicitly by path and
never blanket-commit; verified absent from all 10 commits.

**D8 — Accepted the 5th SDL addition as contract-consistent.**
`contracts/graphql-delta.md` lists four; Strawberry's inheritance flattening produces
`UpdateDeploymentInput.backupTtl` as a fifth. The contract text does say the field
flows there via inheritance, so this was treated as expected, not drift.

---

## 6. Suggested next steps

1. **Open a PR.** The branch is `fac/fix-backup-ttl-npf7g`; base is `develop`. All 33
   tasks complete, all gates green, E2E proven on both entrypoints against current
   HEAD.
2. **Decide on the `.gitignore` change** still uncommitted in the working tree —
   include it in the PR or drop it.
3. **File follow-up tickets for the three pre-existing bugs found in passing**, none
   of which this feature caused: R-11 (`styrminctl deployments create --config` is
   broken for any value), R-12 (the `config-diff.test.ts` wall-clock flake), and R-10
   (`fastStorage` invisible in config diffs).
4. **Consider R-01** (a `BackupMetadata` TypedDict) as a small standalone change — it
   closes the `"expiration"` vs `"expires_at"` typo class at compile time.
5. **Consider R-02** (trimming Pydantic's repr out of client-facing errors) as a
   cross-cutting error-surface improvement.
6. Run `speckit.opsmill.extract` to fold this feature's knowledge into `dev/knowledge`
   and ADRs.

---

*Generated by `speckit.opsmill.implement`. Base `9a12085` → head `985afae`.*
