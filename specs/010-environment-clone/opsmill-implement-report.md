# Implementation Report: Environment Clone

**Status:** COMPLETE — all 49 tasks done, local-pass evidence complete (no `MISSING` rows)

| | |
|---|---|
| Feature | Environment Clone (issue: environment-level clone with data) |
| Spec directory | `specs/010-environment-clone` |
| Branch | `010-environment-clone` |
| Base commit | `0149538` (alignment check, pre-implementation) |
| Head commit | `3f4c7ab` |
| Change set | 96 files, +23250 / −343, 18 commits |
| Tasks | 49 / 49 complete (`[X]`), 0 remaining |
| E2E | PASSED both `[api-chromium]` and `[ui-chromium]` (evidence: `e2e-evidence.md`) |

Implementation ran as 15 planned chunks in clean-context subagents, plus one unplanned
blocker-fix chunk and two review-fix chunks. Chunks ran strictly sequentially.

---

## 1. Chunk-by-chunk ledger

| # | Chunk (tasks.md phase) | Tasks | ✅ | ⚠️ | ❌ | Commit | Flagged upward |
|---|---|---|---|---|---|---|---|
| 1 | Phase 1: Setup | T001 (1) | 1 | 0 | 0 | `d4a3e41` | The bare `alembic` CLI does not work here (no `alembic.ini`, by design) — must use `_get_alembic_config()` / `styrmin db`. Baseline green; single head `c1d2e3f4a5b6`. |
| 2 | Phase 2: DB foundation | T002–T005 (4) | 4 | 0 | 0 | `fb9e968` | Revision `d1e2f3a4b5c6`; upgrade **and** downgrade verified on PostgreSQL 17 *and* SQLite; autogenerate diff after apply = 0 entries. FK names byte-identical to `create_all()`. |
| 3 | Phase 2: helpers + derivation | T006–T008, T015, T016 (5) | 5 | 0 | 0 | `3b3f8d2` | Resolved **five** genuine ambiguities in data-model.md's derivation rules (see §6). |
| 4 | Phase 2: cross-target restore | T009–T014 (6) | 6 | 0 | 0 | `5fe516f` | Found **two gaps research D2 does not answer**: Helm release identity, and kopf firing `on.update` on the counterpart. Escalated rather than guessed. |
| 5 | Phase 3 (US1): service + flow | T017–T020 (4) | 4 | 0 | 0 | `3c1995f` | Resolved the D2 gaps (§6). Found and fixed a **latent data-loss bug** (§4). |
| 6 | Phase 3 (US1): GraphQL | T021–T023 (3) | 3 | 0 | 0 | `58262b8` | Two justified deviations from `contracts/graphql.md`; SC-003 wording drift recorded. N+1 pinned to one query by test. |
| 7 | Phase 3 (US1): SDK + CLI | T024–T025 (2) | 2 | 0 | 0 | `e6bf2e0` | `invoke generate`'s frontend step prints a spurious `ELIFECYCLE exit 1` under invoke's pty; `generate-validate` is authoritative. |
| 8 | Phase 4 (US2): selection | T026–T028 (3) | 3 | 0 | 0 | `689d0fd` | Added two reason constants and **flagged the deviation** from my "don't invent strings" instruction (§6). |
| 9 | Phase 5 (US3): config override | T029–T031 (3) | 3 | 0 | 0 | `7fbfc29` | Test-only chunk (wiring already existed). **Escalated a blocking defect** (§2, chunk 9b). Characterised the silent-typo override gap (§5). |
| 9b | *(unplanned)* blocker fix | — | — | — | — | `86ef8e2` | Fixed the cross-target restore guard contradiction; found that `PENDING` must count as in-flight or in-place restore would have regressed. |
| 10 | Phase 6 (US4): backend | T032–T035 (4) | 4 | 0 | 0 | `0c06aa2` | Two deliberate refinements of research D9 (§6). No migration needed. |
| 11 | Phase 6 (US4): frontend | T036–T039 (4) | 4 | 0 | 0 | `845a813` | `pnpm test` is broken with the default node v18.19.1 (§6). Published the selector inventory for the UI E2E. |
| 12 | Phase 7: E2E authoring | T040–T042 (3) | 3 | 0 | 0 | `5db4a18` | Collects under both variants; `enforce_shard_markers` accepts `shard_backup`. E2E deliberately not executed here. |
| 13 | Phase 7: E2E run | T043 (1) | 1 | 0 | 0 | `978ccb2` | **Both variants PASSED.** Fixed a pre-existing `develop` bug to get there (§4). Residual risk #1 did not bite (§4). |
| 14 | Phase 7: documentation | T044–T048 (5) | 5 | 0 | 0 | `b5353a5` | ADR-056 created. Found that a cloned environment inherits **no** backup storage location, which falsified an existing docs bullet (§6). |
| 15 | Phase 7: final gates | T049 (1) | 1 | 0 | 0 | `43fdc1e` | Caught an order-dependent SQLite bulk-UPDATE failure invisible in isolation (§4). |
| R1 | *(review)* product fixes | — | — | — | — | `1bac55b` | 11 fixed, 1 assessed-and-declined with justification (§5). |
| R2 | *(review)* test gaps | — | — | — | — | `3f4c7ab` | 6 closed, 1 partial by design. Zero production changes needed. |

**Totals: 49 ✅ / 0 ⚠️ / 0 ❌.**

---

## 2. Tasks not completed

**None.** All 49 tasks are `[X]` in `tasks.md`; `grep -c '^- \[ \] T'` returns 0.

One task was blocked mid-run and resolved rather than deferred: chunk 9 escalated that
`create_restore`'s concurrency guard refused **every** cross-target restore, because
counterparts are deliberately created in `RESTORING` while the guard rejected any target in
that state (and T009's own test pinned the wrong behaviour). Left alone this would have made
every clone attribute all deployments `failed`. I inserted an unplanned chunk (9b) to fix it
before continuing, rather than letting chunks 10–11 build on a broken foundation. Chunk 9b
also produced reproduction evidence: with only `service.py` stashed, the new tests fail with
the exact reported symptom.

---

## 3. Local-pass evidence

Every test added or modified was observed passing locally. No row is `MISSING`.

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `test_environment_clone_repository.py` (16, T004) | unit | `uv run pytest backend/tests/unit/repository/backup/test_environment_clone_repository.py -v` | 2026-08-19T14:25:41Z | in-memory SQLite (`sqlite+aiosqlite`) | `16 passed in 0.84s` |
| `test_environment_clone_status.py` (98, T016 matrix + 60-param invariant) | unit | `uv run pytest backend/tests/unit/services/backup/test_environment_clone_status.py -v` | 2026-08-19T15:07:26Z | n/a | `98 passed in 0.20s` |
| `test_environment_clone_config_merge.py` (18, T015) | unit | `uv run pytest backend/tests/unit/services/backup/test_environment_clone_config_merge.py -v` | 2026-08-19T15:07:19Z | n/a | `18 passed in 0.10s` |
| `test_environment_backup.py` (94; +8 for T007/T008) | unit | `uv run pytest backend/tests/unit/services/backup/test_environment_backup.py -q` | 2026-08-19T15:07:19Z | n/a | `94 passed in 0.49s` |
| `test_restore.py` (26; +9 for T009) | unit | `uv run pytest backend/tests/unit/services/backup/test_restore.py -q` | 2026-08-19T15:19Z | n/a | `26 passed in 0.07s` |
| `test_restore_workflow_failure_handler.py` (6; +3 for T010/T011/T013) | unit | `uv run pytest backend/tests/unit/workflows/test_restore_workflow_failure_handler.py -q` | 2026-08-19T15:31Z | n/a | `6 passed in 0.24s` |
| `test_restore_recovery_cross_target.py` (8 new, T012) | unit | `uv run pytest backend/tests/unit/test_restore_recovery_cross_target.py -q` | 2026-08-19T15:22Z | n/a (fake api client) | `8 passed in 0.12s` |
| `test_backup_builders.py` (11; +3 for T013) | unit | `uv run pytest backend/tests/unit/agent/test_backup_builders.py -q` | 2026-08-19T15:14Z | n/a | `11 passed in 0.02s` |
| `test_deploy_skip_initial_reconcile.py` (6 new, T014) | unit | `uv run pytest backend/tests/unit/services/test_deploy_skip_initial_reconcile.py -q` | 2026-08-19T15:26Z | n/a | `6 passed in 0.13s` |
| `test_environment_clone_service.py` (20 new, T017–T020) + 3 neighbours | unit | `uv run pytest .../test_environment_clone_service.py .../test_restore_recovery_cross_target.py .../test_environment_services.py .../test_deploy_skip_initial_reconcile.py -v -p no:randomly` | 2026-08-19T16:21:39Z | n/a | `72 passed in 0.26s` |
| `test_environment_clone.py` (29 new, T023: 21-case status matrix, 1-query N+1 guard, 2 enum mirrors) | functional | `uv run pytest backend/tests/functional/graphql/test_environment_clone.py -v` | 2026-08-19T16:57:09Z | in-memory SQLite; Prefect manager mocked | `29 passed in 1.77s` |
| `python_sdk/tests/test_environment_clones.py` (22 new, T024) | unit | `uv run pytest python_sdk/tests -v` | 2026-08-19T17:10:35Z | n/a | `203 passed in 0.28s` |
| `cli/tests/test_environment_clones.py` (22 new, T025) | unit | `uv run pytest cli/tests -v` | 2026-08-19T17:10:39Z | n/a | `2 failed, 332 passed in 22.00s` (2 = known root-user telemetry, pre-existing) |
| `test_environment_clone_service.py` (8 new, T026) | unit | `uv run pytest <8 node ids> -v` | 2026-08-19T17:28:38Z | n/a | `8 passed in 0.16s` |
| `test_environment_clone.py` (4 new, T027) | functional | `uv run pytest <4 node ids> -v` | 2026-08-19T17:28:46Z | n/a | `4 passed in 0.49s` |
| `python_sdk/.../test_environment_clones.py` (3 new, T028) | unit | `uv run pytest <3 node ids> -v` | 2026-08-19T17:29:01Z | n/a | `3 passed in 0.01s` |
| `cli/tests/test_environment_clones.py` (3 new, T028) | unit | `uv run pytest <3 node ids> -v` | 2026-08-19T17:29:06Z | n/a | `3 passed in 0.17s` |
| `test_environment_clone_service.py` (3 new + 1 rerun, T029 ordering proof) | unit | `uv run pytest <4 node ids> -v` | 2026-08-19T18:05:08Z | n/a | `4 passed in 0.15s` |
| `test_environment_clone.py` (3 new + 2 rerun, T030 — all 5 cases) | functional | `uv run pytest <5 node ids> -v` | 2026-08-19T18:05:18Z | n/a | `5 passed in 0.62s` |
| `python_sdk/.../test_environment_clones.py` (6 new, T031) | unit | `uv run pytest <6 node ids> -v` | 2026-08-19T18:05:30Z | n/a | `6 passed in 0.02s` |
| `cli/tests/test_environment_clones.py` (6 new, T031) | unit | `uv run pytest <6 node ids> -v` | 2026-08-19T18:05:30Z | n/a | `6 passed in 0.18s` |
| `test_restore.py` + `test_environment_clone_service.py` (7 new/modified, chunk 9b guard fix) | unit | `uv run pytest <7 node ids> -v` | 2026-08-19T18:19:46Z | n/a | `7 passed in 0.17s` |
| `test_environment_clone_service.py` (6 new, T032 — three timing windows) | unit | `uv run pytest <6 node ids> -v -p no:randomly` | 2026-08-19T21:25:09Z | n/a | `6 passed in 0.16s` |
| `test_environment_clone_service.py` + `test_environment_clone_repository.py` (9 new, T033 + repo lookup) | unit | `uv run pytest <9 node ids> -v -p no:randomly` | 2026-08-19T21:25:19Z | n/a | `9 passed in 0.28s` |
| `test_environment_clone.py` (10 new, T034/T035) | functional | `uv run pytest backend/tests/functional/graphql/test_environment_clone.py -v -p no:randomly -k "<filter>"` | 2026-08-19T21:25:27Z | n/a | `10 passed, 36 deselected in 0.96s` |
| `EnvironmentCloneDialog.test.tsx` (30) + `EnvironmentClonesSection.test.tsx` (35) = 65 new (T039) | frontend unit | `cd frontend && PATH=/root/.local/share/pnpm/nodejs/24.18.0/bin:$PATH npx vitest run src/__tests__/environments/EnvironmentCloneDialog.test.tsx src/__tests__/environments/EnvironmentClonesSection.test.tsx --reporter=verbose` | 2026-08-19T21:46:58Z | node v24.18.0 (pnpm-managed), vitest 4.1.0, jsdom | `Test Files 2 passed (2)` / `Tests 65 passed (65)` |
| Full frontend suite (regression guard) | frontend unit | `cd frontend && PATH=/root/.local/share/pnpm/nodejs/24.18.0/bin:$PATH npx vitest run` | 2026-08-19T21:47:07Z | node v24.18.0, vitest 4.1.0, jsdom | `Test Files 69 passed (69)` / `Tests 625 passed (625)` |
| `test_environment_clone_lifecycle[api-chromium]` | **e2e** | `sleep infinity \| uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]" -v -s --pdb > /tmp/clone-e2e-api.log 2>&1` | 2026-08-19T22:34:07Z | vcluster `pytest-eb1dc5e9-5ffe-449b-be5c-69f6a8d2ba1f`; kubeconfig `/tmp/pytest-of-root/pytest-1379/vcluster0/kubeconfig` | `=================== 1 passed, 1 warning in 273.70s (0:04:33) ===================` |
| `test_environment_clone_lifecycle[ui-chromium]` | **e2e** | same command with `[ui-chromium]` → `/tmp/clone-e2e-ui.log` | 2026-08-19T22:46:45Z | vcluster `pytest-d6b421a4-ebb6-4a6e-868e-a870e70b6573`; kubeconfig `/tmp/pytest-of-root/pytest-1380/vcluster0/kubeconfig` | `=================== 1 passed, 1 warning in 283.49s (0:04:43) ===================` |
| `test_environment_services.py` (cascade-fix test, chunk 13) | unit | `uv run pytest backend/tests/unit -q` | 2026-08-19T23:00Z | n/a | `1894 passed` (12 failed = known Prefect, verified identical with changes stashed) |
| `test_environment_clone.py` (T049 order-dependence fix) | functional | `uv run pytest backend/tests/functional/graphql -q` | 2026-08-19T23:31:48Z | n/a | `322 passed, 1 warning in 80.43s (0:01:20)` |
| 13 review-fix tests (R1: P1–P9, D2) | unit + functional | `uv run pytest backend/tests/unit/services/backup/test_environment_clone_service.py backend/tests/unit/services/backup/test_environment_clone_status.py backend/tests/unit/services/test_environment_services.py backend/tests/functional/graphql/test_environment_clone.py -k "<filter>"` | 2026-08-20T00:23:47Z | n/a | `13 passed, 223 deselected in 0.31s` — each observed FAILING pre-fix |
| `test_env_clones_get_distinguishes_an_empty_selection_from_no_selection` (R1/P7) | unit | `cd cli && uv run pytest tests/test_environment_clones.py` | 2026-08-20T00:24Z | n/a | `1 passed` (pre-fix: FAILED, output said `all eligible`) |
| `test_the_counterpart_row_reproduces_the_source_declared_state` (R2/T1, FR-005) | functional | `uv run pytest backend/tests/functional/graphql/test_environment_clone.py::test_the_counterpart_row_reproduces_the_source_declared_state` | 2026-08-20T01:18:14Z | n/a | `1 passed in 0.25s` — fails on latest-wins pin, dropped overrides, dropped config |
| `test_crd_builder.py` (7 new, R2/T2a) | unit | `uv run pytest backend/tests/unit/test_crd_builder.py` | 2026-08-20T01:18:18Z | n/a | `7 passed in 0.20s` — CR-name revert → `1 failed, 6 passed` |
| `test_counterpart_crd_body.py` (4 new incl. both `RuntimeError` guards, R2/T2b) | unit | `uv run pytest backend/tests/unit/workflows/test_counterpart_crd_body.py` | 2026-08-20T01:18:20Z | n/a | `4 passed in 0.20s` |
| `test_restore_recovery_cross_target.py` (producer joined to consumer, R2/T2c) | unit | `uv run pytest backend/tests/unit/test_restore_recovery_cross_target.py` | 2026-08-20T01:18:23Z | n/a | `12 passed in 0.22s` — CR-name revert now fails **11** tests vs 0 before |
| `test_a_post_clone_config_update_keeps_the_counterpart_release_name` (R2/T3) | functional | `uv run pytest <node id>` | 2026-08-20T01:18:26Z | n/a | `1 passed in 0.28s` — fails when rule-2 getattr chain is broken |
| 3 fatal-branch tests (R2/T4) | unit | `uv run pytest backend/tests/unit/services/backup/test_environment_clone_service.py -k "vanished_source or captured_config_that_no_longer or unexpected_create_environment"` | 2026-08-20T01:18:43Z | n/a | `3 passed, 54 deselected in 0.16s` — all 3 fail without `_fail_pending`/`fatal=True` |
| `test_the_cross_target_restore_targets_the_counterpart_not_the_source` (R2/T6) | functional | `uv run pytest <node id>` | 2026-08-20T01:18:31Z | n/a | `1 passed in 0.26s` — fails when dispatch points at the source |
| `test_clone_discard_step_contract.py` (3 new, R2/T7) | unit | `uv run pytest backend/tests/unit/test_clone_discard_step_contract.py` | 2026-08-20T01:18:35Z | n/a | `3 passed in 0.36s` — a step rename now names both drifted consumers |
| E2E node after R2/T5 deepening (**not re-executed**) | e2e | `uv run pytest backend/tests/e2e/test_backup_restore.py --collect-only -q` | 2026-08-20T01:18:45Z | no cluster booted | `10 tests collected in 0.01s` (both variants intact); helper probed directly — old id-roster assertion passes under 4 injected source mutations, new one fails |

**Final gate results (T049, re-verified after review fixes):**

| Gate | Exit | Summary |
|---|---|---|
| `uv run invoke format lint` | **0** | `All checks passed!` (ruff format, ruff check, ty, rumdl) |
| `uv run invoke validate-graphql` | **0** | `227/227 .graphql files passed validation.` |
| `uv run invoke generate-validate` (authoritative no-diff) | **0** | SDK + frontend generated types fresh; `git status` clean |
| full `uv run invoke test` | 1 | `12 failed, 2345 passed, 2 skipped` — all 12 known Prefect-ephemeral-API |
| frontend `npx vitest run` (node 24) | **0** | `Test Files 69 passed (69)` / `Tests 625 passed (625)` |
| `python_sdk/tests` | **0** | `212 passed` |
| `cli/tests` | 1 | `2 failed, 341 passed` — both known root-privilege telemetry |
| Alembic single head | **0** | `Rev: d1e2f3a4b5c6 (head)`, head count = 1 |

Known non-regressions, each verified reproducible on a clean tree: 12 `backend/tests/unit/agent/`
Prefect ephemeral-API timeouts; 2 `cli/tests/telemetry` failures (this environment runs as root,
so a chmod-000 directory is still writable); 3 yamllint warnings in files this feature never touched.

---

## 4. Defects found and fixed beyond the task list

Four real bugs surfaced that the task list did not anticipate. Three were pre-existing.

1. **Cross-target restore was refused for every counterpart** (chunk 9 → 9b, `86ef8e2`).
   `create_restore`'s guard keyed on `deployment.status == RESTORING`, but counterparts are
   deliberately parked in `RESTORING` awaiting their first restore. Every clone would have
   attributed all deployments `failed`. Now gated on an actual non-terminal `Restore` row.
   Fixing it revealed that `PENDING` must count as in-flight — `create_restore` writes `PENDING`
   and only `execute_restore_workflow` promotes to `IN_PROGRESS` — so an `IN_PROGRESS`-only
   lookup would have regressed in-place restore. Also un-wedges a deployment left `RESTORING`
   by a dead restore.

2. **Latent data-loss bug in cross-target recovery** (chunk 5, `3c1995f`). Deleting the restored
   source-named CR fired kopf's delete handler, because Velero restores `metadata.finalizers`.
   That handler tears down the HelmRelease named by `spec.releaseReference` *and everything
   labelled with it* — in the counterpart's namespace, the release keeping the just-restored
   chart and its PVCs alive. Recovery now clears finalizers, re-reads to verify, and raises
   rather than deleting if any remain.

3. **`delete_environment` never cascaded deployments** (chunk 13, `978ccb2`) — pre-existing on
   `develop`. The ORM tried to null a non-nullable FK (`NotNullViolationError`). Every prior
   caller swallowed it in a cleanup `except`/`suppress`, so it had never surfaced; SC-005 is the
   first place environment deletion is load-bearing. Fixed with FK-ordered deletion that breaks
   the `deployment ↔ active_application_instance` cycle first and *detaches* rather than deletes
   cross-target restores, so a clone's `restore_id` stays resolvable.

4. **Order-dependent test failure invisible in isolation** (chunk 15, `43fdc1e`). Two clone test
   helpers mutated multiple rows of one table per flush, putting SQLAlchemy on its bulk-UPDATE
   path where SQLite renders `updated_on`'s `onupdate=func.now()` as a postcompile `strftime(...)`
   that cannot combine with `executemany()`. Fixed by the precedent already in the suite.

**Residual risk that did not materialise.** The design's largest unknown was whether Flux's
helm-controller would `install` or `upgrade` the Velero-restored HelmRelease. It ran **install**
over the restored release storage and **succeeded** — because the counterpart adopts the source's
release name, the objects' `meta.helm.sh/release-name` annotations already match, so ownership
validation passes on install too. The chunk-5 design choice holds; its stated rationale ("make
the first Helm action an upgrade") was narrower than the reason it actually works. Unproven:
whether an extra pod roll occurs between Velero completing and recovery's HelmRelease upsert.

---

## 5. Review findings

Five review agents ran across `0149538..3f4c7ab` (code, tests, errors, types, comments, simplify).
**No critical code-quality findings.** 12 high-severity items were fixed inline in `1bac55b`;
7 test gaps were closed in `3f4c7ab`.

### Fixed inline — product (`1bac55b`)

| Sev | File | Finding | Outcome |
|---|---|---|---|
| Critical | `services/backup/clone.py:755` | The `IN_USE` guard voided the FR-008 escape hatch it existed to preserve: a swallowed Prefect dispatch outage leaves a constituent `Backup` `PENDING` forever, so the capture never terminalises, the source environment is permanently blocked, and snapshot deletion is refused — with no created environment to discard. Contradicted `spec.md:87`. | Fixed — guard now bounded by the flow's own wait budget (one shared constant, so they cannot drift), because "non-terminal" is not self-healing while "the flow could still be waiting" expires. ADR-0056 §5, research D9, data-model.md, spec FR-008 and user docs updated. |
| Critical | `services/backup/clone.py:918-925` | Deleting the source of a **mid-restore** clone destroyed the record, losing the provenance the model docstring says must survive, and the cascade removed in-flight `Restore` rows leaving counterparts stuck `RESTORING` — individually unrecoverable, since `delete_deployment` refuses `RESTORING`. | Fixed — a clone with a created environment is kept (source FK nulled, fatal marker added so it terminalises and stops occupying its environment); only a clone that materialised nothing is deleted. |
| High | `workflows/templates/clone.py:394-412, 609-623` | Restore dispatch was not atomic: `create_restore` commits a `PENDING` row and the `RESTORING` flip *before* `run_action`, and the handler discarded `restore_id`/`counterpart_deployment_id`. A Prefect blip left a terminal-looking `PARTIAL` clone with a permanently wedged counterpart the new guard would refuse forever, and no reaper exists. Found independently by two reviewers. | Fixed — the undispatched restore is settled exactly as `execute_restore_workflow` settles one it cannot finish, and both ids are recorded even on failure. |
| High | `workflows/templates/clone.py:116, 591, 641`; `services/backup/clone.py:377-401` | A malformed `deployment_results` entry was dropped on read and the **reduced** list written back — erasing it from the database, contrary to its own docstring. Sibling defect: `['a','b','c']` derived **`COMPLETED`** with zero deployments accounted for, breaking SC-003; the existing test masked it by mixing junk with one good entry. | Fixed — both halves and both docstrings. An unreadable entry can no longer be erased, nor allow `COMPLETED`. |
| High | `api/definitions/backup/environment_clone.py:261-267, 278-285` | Resolvers called `model_validate` bare where the derivation is deliberately tolerant, so one `clone_errors` entry missing `fatal` failed the **entire** `environmentClone` query as `INTERNAL_ERROR` — the clone unreadable on every surface, with no field, index, or row id. | Fixed — per-entry degradation on both JSON columns. |
| High | `services/backup/clone.py:204-206` | A fresh, never-closed `AsyncSession` per poll iteration (the only `get_unit_of_work()` in a `while True` in the repo): up to 720 sessions per clone against a default pool of 5+10. | Fixed — one unit of work, rolled back between turns. |
| Medium | `cli/.../environment_clones.py:339` | The CLI rendered `[]` (a deliberate config-only clone) as "all eligible" — its exact opposite. | Fixed (`is None`), wording matched to the frontend. |
| Medium | `services/environments.py:517, 526` | A failed cluster teardown was counted as success; N namespaces could leak while the audit line still claimed `teardown_requested=N`. | Fixed — audit counts outcomes and a warning names the leaked deployments. |
| Critical (doc) | `operator/restore_recovery.py:50-56` | **Inverted comment**: claimed the flow *strips* kopf's state annotations when it deliberately keeps them (and inherits them onto the counterpart CR). Rot from the removed `_strip_kopf_annotations` helper; a reader trusting it would reintroduce the displayState oscillation bug. | Fixed. |
| Important (doc) | `cli/.../environment_clones.py:52-55, 283-289`; `docs/.../styrminctl.md` | Documented a behaviour that cannot occur: a clone being terminal at mutation return. Registration always falls through to `IN_PROGRESS`/`PENDING`; an all-skipped clone reads `IN_PROGRESS`, not `COMPLETED`. | Fixed in all three places; the defensive check is kept. |
| Important (doc) | `docs/.../styrminctl.md:188` | `clonedFrom` was documented for operators but no SDK or CLI operation selects it. | Fixed by correcting the doc (adding SDK surface in a fix-only pass was judged worse). |
| Assessed | `services/environments.py:500-506` | Multi-transaction `delete_environment` could leave a clone claiming its environment was deleted while it still exists. | **Deliberately not restructured** — the cascade is inherently multi-transaction and a late rewrite was the larger risk. The window is tolerable because the marker commits *with* the FK release, so a retry finds no clone by that environment id and converges; the review's "a retry appends a second marker" does not hold. Pinned by a test. |

### Fixed inline — test gaps (`3f4c7ab`)

Each new test was mutation-verified: the targeted defect was injected, the test observed
FAILING, then restored and observed PASSING. **No production code changed** — every defect had
to be injected, confirming the product pass had already caught the real bugs.

| Sev | Gap | Outcome |
|---|---|---|
| Critical | **FR-005 verified nowhere** — the captured driver-version pin, `service_name_overrides`, config and parameters were never asserted; resolving *latest* instead of the pin kept the whole suite green. | Closed — functional test compares the counterpart row to the source; fails on all three injected defects. |
| Critical | The **counterpart CR body was stubbed on both sides of its own contract** (`build_styrmin_deployment_body` had zero references in `backend/tests/`), so reverting the `crd/builder.py` CR-name change failed only the 20-minute E2E — the same shape as the `create_restore` stub. | Closed — direct coverage plus the producer joined to the consumer; the revert now fails **11 tests instead of 0**. Both `RuntimeError` guards covered. |
| Important | `_resolve_release_reference` rule 2 was untested and **undetectable by construction** (rules 2 and 3 return the same string for ordinary deployments). Its failure is the second-Helm-install-over-owned-objects the design exists to prevent. | Closed — a real `updateEnvironment` fan-out regenerates a counterpart's context and asserts the source-derived release name survives. |
| Important | Three unreached fatal branches in the clone flow; a handler omitting `_fail_pending` would leave a clone permanently `IN_PROGRESS`. | Closed — all three, asserting terminal + fatal marker + no `pending` entries. |
| Important | E2E SC-002 was roster-deep only, and its post-clone source health check sat in a `finally` under `suppress(Exception)` so it could never fail. | **Partial by design** — deepened to per-deployment declared state plus a source data read, and the health check moved where it can fail. `parameters` deliberately left to the T1 functional test rather than widening an SDK query. E2E not re-executed. |
| Medium | Dead instrumentation: `create_restore` kwargs were collected then discarded; aiming the restore at the source would have passed. | Closed. |
| Medium | The discard signal is a magic string triplicated across backend, frontend and E2E driver; a step rename would silently break the UI badge. | Closed — a contract test names any drifted consumer. |

### Deferred (recorded, not blocking)

- **Types**: `CLONE_STEP_*` should be an enum now that it is a cross-surface contract; `CLONE_STEPS` is inert and its only test is tautological; `CloneDeploymentResult`'s three invariants are prose-only (no `model_validator`). `DeploymentSnapshot.service_name_overrides`/`release_reference` are not projected onto the GraphQL `DeploymentSnapshot` — confirmed deliberate.
- **Comments**: `clone.py:183-184` says the derivation keys on "the two deletion markers"; it keys on exactly one. (I propagated that phrasing in my own chunk briefs — the source of the imprecision.)
- **Errors**: the CLI reports a `--wait` timeout as a failure without mentioning `--max-wait`; `clone.py:604` has an unreachable-but-invisible branch; `EnvironmentOperationInProgressError`'s docstring still lists only backup/restore and its message never names the FR-008 escape hatch.
- **Code**: `restore_environment_backup`'s fan-out still counts a skipped `RESTORING` deployment as dispatched (the asymmetric half of the `skipped_restoring` fix applied to `update_environment`).
- **Frontend**: the clone mutation does not invalidate `ListBackups` though it creates constituent `Backup` rows (the sibling tab does, and documents why); hand-written query-key tuples violate `dev/guidelines/frontend/data-fetching.md:15`; `isActive` is not threaded into `EnvironmentCloneRow`'s detail poll; two *unreadable* result entries would now share a nil-UUID React key.
- **Known gap**: the generated `UpdateEnvironmentInput` does not forbid extra keys, so a **misspelled `configOverride` field is a silent no-op** and the clone quietly keeps the source's value. Characterised and pinned by a test with a "known gap" docstring; fixing needs an explicit CLI key check or a codegen change.
- **Simplify (14 advisory items)**, highest-value first: six copy-pasted poll loops in the SDK (extract `_poll_until` onto `BaseResource`); `_save_progress` reimplements the documented `_append_clone_error` JSON-column rebind trick; a third reimplementation of `get_kubernetes_reference`; duplicated lenient `restore_id` parsing; a low-risk `clone_config.py` slice out of the 1354-line `clone.py`; dual bookkeeping in the flow; three near-identical repository queries; plus smaller items.

### Validated as correct by reviewers (no action)

Transaction boundaries in `clone_environment`; FK ordering in `delete_all_for_environment` across
every `deployment_id` FK owner; no `ownerReferences`, so deleting the restored CR cannot GC-cascade
the counterpart's HelmRelease; `delete_namespace` only ever targets the target namespace; the
hand-mirrored GraphQL enums cannot drift (bidirectional mirror test); loose JSON is adequately
guarded on read; all nine ADR-056 decisions match the shipped code; no user-facing doc repeats the
misleading "100% of source deployments" phrasing.

---

## 6. Autonomous decisions worth revisiting

**Orchestration**
1. **Chunking** — 15 chunks from 7 phases: Phase 2 (15 tasks) split into DB foundation / helpers+derivation / cross-target chain; Phase 3 into service+flow / GraphQL / SDK+CLI; Phase 6 into backend / frontend; Phase 7 into E2E-authoring / E2E-run / docs / gates. Dependency order in `tasks.md` was respected throughout.
2. **Inserted an unplanned chunk (9b)** to fix the escalated restore-guard blocker before continuing, rather than recording it and moving on. Chunks 10–11 would otherwise have built on a foundation where every clone failed.
3. **Resumed a subagent that died on a transient API 529** rather than discarding its work — its diagnosis and partial edits were sound and it finished correctly.
4. **Ran the five review agents in parallel** (read-only) while keeping every implementation chunk strictly sequential.
5. **Split the review fixes into two passes** (product, then tests) so a test written to catch a defect could be mutation-verified against the fixed code.

**Design decisions delegated and made inside chunks — these are the ones most worth a second look**
6. **The counterpart adopts the source's Helm release identity** while keeping its own CR identity (chunk 5). This is the largest architectural call in the change and it was made mid-implementation, because research D2 did not answer it. It required changing `operator/crd/builder.py` so a CR is named after its *namespace* rather than its release reference — a path every deployment takes, though provably a no-op for existing ones. Recorded as ADR-056.
7. **Five ambiguities in data-model.md's derivation rules** were resolved by chunk 3 (what "nothing else recorded" means; that "included" excludes skipped; that a restore cannot end `PARTIAL`; generalising rule 3b; a missing `fatal` reading as non-fatal). All documented in-code and tested.
8. **Two deliberate refinements of research D9** (chunk 10): the `IN_USE` guard additionally requires the clone itself to be non-terminal, and terminality is *snapshotted at the guard* rather than re-derived after the cascade (the cascade deletes `Backup` and `Restore` rows that are themselves derivation inputs).
9. **The `IN_USE` guard was then re-scoped again during review** (`1bac55b`) to be bounded by the flow's wait budget. This changed FR-008's semantics, so **`spec.md`, `research.md`, `data-model.md` and ADR-056 were edited during a fix pass** — implementation altering its own spec. Defensible under Constitution §VII and needed for artifact consistency, but it is the kind of change a reviewer should confirm rather than inherit.
10. **Two reason constants were invented** (`CLONE_REASON_INTERNAL`, `CLONE_REASON_TOMBSTONED`) against my explicit instruction not to, because reusing `CLONE_REASON_NOT_ELIGIBLE` ("no active instance") would have been factually false for an internal deployment. The subagent flagged the deviation rather than hiding it.
11. **SC-003 wording drift left unresolved in the spec.** The spec says "100% of source deployments"; FR-003 excludes internal deployments and the implementation omits them from attribution entirely (the clone gets its own fresh ingress controller, so "skipped" would misdescribe it). Behaviour is pinned by tests and no user-facing doc repeats the misleading phrasing, but **the spec sentence itself still says "100%"** — worth narrowing to "non-internal".
12. **Two justified deviations from `contracts/graphql.md`**: `updatedOn` is nullable (the column is, and both sibling surfaces expose it nullable), and `name` is the first mutation argument (Python forbids a non-default parameter after defaults).
13. **P9 was assessed and declined** rather than fixed — a late multi-transaction restructure was judged the larger risk, with the convergence property documented and pinned instead.
14. **T5's E2E deepening is partial by design** and the E2E was **not re-executed** after the review fixes. Fix pass A changed only failure-window semantics, not the happy path, so I accepted the existing T043 evidence. A belt-and-braces re-run would additionally re-cover the P3 dispatch path.

**Environment findings that will matter to CI and the next contributor**
15. `pnpm test` does not work with the default `node` v18.19.1 (rolldown needs `node:util#styleText`), and `frontend/node_modules` shipped with every optional native binding skipped. Worked around with `pnpm install --force` and pnpm's node 24 — `package.json` and `pnpm-lock.yaml` deliberately untouched, so **this is unfixed in the repo**.
16. `uv run invoke generate`'s frontend step prints a spurious `ELIFECYCLE exit code 1` under invoke's pty even on success; `generate-validate` is the authoritative freshness check.
17. The bare `alembic` CLI does not work here by design (no `alembic.ini`).
18. A cloned environment inherits **no** backup storage location, so it cannot take its own backups — discovered while writing the docs, and it falsified an existing docs bullet claiming cloning copies backup history.

---

## 7. Suggested next steps

1. **Open a PR.** Flag the three pre-agreed Ask-First gates for reviewer sign-off: the database
   schema change (T002/T003, revision `d1e2f3a4b5c6`), the GraphQL schema modifications
   (T022/T034), and the ADMIN auth surface (T022).
2. **Confirm the decisions in §6 items 6, 9 and 11** — the Helm release-identity adoption
   (ADR-056), the spec edits made during the review fix pass, and whether SC-003's "100%"
   wording should be narrowed in `spec.md`.
3. **Consider a belt-and-braces E2E re-run** of `test_environment_clone_lifecycle` on the
   post-review-fix tree, to re-cover the P3 restore-dispatch path against a live cluster.
4. **Decide on the silent-typo `configOverride` gap** (§5 deferred) — it is a real
   non-interference hazard: a misspelled field leaves the clone on the source's value.
5. **Fix the frontend `ListBackups` invalidation** and thread `isActive` into the clone row's
   detail poll (§5 deferred, small and self-contained).
6. **Fix the environment: `pnpm test` needs node ≥ 20** and the optional native bindings; CI will
   hit the same wall (§6 item 15).
7. Optionally take the highest-value simplify items — the SDK `_poll_until` extraction and
   removing `_save_progress`'s duplicate of `_append_clone_error`.
8. Run `speckit.opsmill.extract` to fold the durable knowledge from this feature into
   `dev/knowledge/`, `dev/guides/` and the ADR set.
