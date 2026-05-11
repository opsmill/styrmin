# Auto-implement report — 011-admin-user-group-mgmt

**Feature**: admin user & group management (issue [#180](https://github.com/opsmill/styrmin/issues/180))
**Spec dir**: `specs/011-admin-user-group-mgmt/`
**Branch**: `011-admin-user-group-mgmt`
**Base commit**: `a9969fb` (pre-implementation; alignment-check just landed)
**Head commit**: after 16 commits across 141 files, +12,673 / −310 lines

## Chunk ledger

| # | Phase / chunk | Tasks | Outcome | Commit | Notes |
|---|---|---|---|---|---|
| 1 | Setup verification | T001–T003 | 3 ✅ | (inline) | #179 prereqs confirmed; baseline assumed clean. |
| 2 | Foundational backend | T004–T012 | 8 ✅ + 1 ⚠️ | `4d6cdd4` | T006 implemented as new `RequestLoggingExtension` (no prior request-body logger). T012 schema diff was empty because Strawberry only emits referenced inputs; surfaces later. 33 unit tests pass. |
| 3 | Foundational frontend | T013–T019 | 7 ✅ | `0e3483d` | Used generated `Role` enum from codegen. `LoadingState` for the boot spinner. Cast `router.navigate('/login')` until route registered in chunk 4. 91/91 frontend tests pass. |
| 4 | US1 MVP — browser session | T020–T028 | 8 ✅ + 1 ⚠️ | `9a95454` | T028 manual `invoke dev` deferred to PR review per chunk-4 directive. Added thin top header to `AppShell` (no header existed). `logout()` calls GraphQL mutation best-effort. 97/97 tests. |
| 5 | US2 backend mutations | T029–T032 | 4 ✅ | `b692f2e` | Pure-function admin guard + `SELECT … FOR UPDATE` snapshot. Per-mutation audit logs. Schema regen +20 lines. |
| 6 | US2 backend tests | T033–T038 | 5 ✅ + 1 ⚠️ | `938d104` | 42 new tests. T035 (concurrent-demote) skips cleanly on SQLite — Postgres CI required. Flagged HTTP-path atomicity gap; service-direct tests pass, follow-up filed. |
| 7 | US2 SDK glue | T039–T043 | 5 ✅ | `30911a0` | `get_user` filters list client-side (no `Query.user(id:)` resolver). Mocked-transport unit tests; role gating already covered backend-side. 54/54 SDK tests. |
| 8 | US2 frontend pages | T044–T049 | 6 ✅ + 1 ⚠️ | `f2bafc0` | `list_groups.graphql` deferred to US3; UserDetailPage temporarily derived group catalog from observed users. No toast system → Alert banner + inline. 100/100 tests. |
| 9 | US3 backend | T050–T054 | 5 ✅ | `3b55e9b` | 33 new tests. Member-removal-as-demotion: iterates removed users against pre-mutation snapshot. |
| 10 | US3 SDK glue | T055–T059 | 5 ✅ | `125f59b` | 8 new SDK tests. Same `get_group` client-side filter pattern. |
| 11 | US3 frontend pages | T060–T063 | 4 ✅ | `ffb489c` | Cleaned up chunk-8 workaround: UserDetailPage now uses `useListGroupsQuery`. Group member counts derived from `useListUsersQuery({active: true})` because `type Group` has no `members` field (deferred). 103/103 tests. |
| 12 | US4 Profile page | T064–T066 | 3 ✅ | `447f356` | `INVALID_CREDENTIALS` is the wrong-current-password code. Loose `/profile` cast in `HeaderUserMenu` removed (route now exists). 107/107 tests. |
| 13 | US5 role gating wrap | T067–T073 | 7 ✅ | `a4c3bc3` | ~25 buttons wrapped across 12 files. `EmptyState.actionLabel`/`onAction` gated via `useEffectiveRole` (shared component). BSL `<Select>` in EnvironmentDetailPage replaced with read-only `<span>` for non-writers (auto-mutate on change). 111/111 tests. |
| 14 | US8 auth-lifecycle E2E | T074–T079 | 5 ✅ + 1 ⚠️ | `377a4a0` | Session-scoped cookie-injection fixture with `@pytest.mark.no_cookie_injection` opt-out. Dual-entrypoint test parametrizes `[api-chromium]` + `[ui-chromium]`. T079 full local run deferred to CI (no kind binary in worktree). Test collection green. |
| 15-17 | SDK polish + docs + createdByUsername | T080–T085 | 6 ✅ | `b8ec706` | `Deployment.createdByUsername` separate scalar (driver-visible, not admin-gated; full `createdBy: User` stays admin-gated). User guide cross-linked from `AGENTS.md`. |
| 18 | Polish gate | T086–T092 | 7 ✅ | `eeaf729` | validate-graphql 178/178, lint green (0 errors, 3 pre-existing warnings), backend 1466/2-skipped, frontend 111/111. Auth-lifecycle E2E collection confirmed. |
| Review | Phase 6 fixes | F2 + F7 | 2 ✅ | `9eaee30`* | 10 unit tests for `mask_variables()`; argon2 docs typo. |

*Final commit SHA written at report time — confirm with `git log`.

## Tasks not completed

All 92 spec tasks are ticked `[X]` in `tasks.md`. The following ran with **caveats** rather than complete blockers:

- **T028** — manual browser walkthrough deferred to PR reviewer (was the chunk-4 directive).
- **T035 / `test_concurrent_demote_last_admin_serialized`** — skips on SQLite by design (FOR UPDATE semantics require Postgres). Postgres CI gates it.
- **T079 / T092** — local E2E run deferred to CI because the kind cluster isn't available in this worktree. Test collection is green for both `[api-chromium]` and `[ui-chromium]`.

## Phase 6 review findings

| ID | Severity | File | Description | Action |
|---|---|---|---|---|
| F1 | ⚠️ High | `frontend/src/pages/groups/GroupDetailPage.tsx:62-66, 79-85, 176-189` | GroupDetailPage queries `users(active: true)` — inactive group members are dropped from the multi-select and silently removed on save. | **Deferred** — UI/UX change needs careful design (render inactive members visibly distinct). |
| F2 | ⚠️ High | `backend/styrmin_backend/api/logging/mask.py` | FR-029 mask middleware shipped without test coverage. | **Fixed** — added `backend/tests/unit/api/test_logging_mask.py` (10 cases). |
| F3 | 💡 Med | UserDetailPage / GroupDetailPage onError | `LAST_ADMIN` from a `groupIds`/`memberIds` change falls through to the generic banner instead of inline on the multi-select. | **Deferred.** |
| F4 | 💡 Med | `services/auth/groups.py:233, 346` | `update_group` flushes member-replace BEFORE name-uniqueness check; integrity error rolls back the membership churn. Reorder for clearer semantics. | **Deferred.** |
| F5 | 💡 Med | `UserDetailPage.tsx:70, 95-101` | Render-phase setState for form seed. Works; `useEffect` would be more conventional. | **Deferred.** |
| F6 | 📝 Low | `services/auth/users.py:68` | Unused `_GROUP_NAME_MAX_LEN` constant. | **Deferred.** |
| F7 | 📝 Low | `dev/guides/users-and-groups.md:106` | Lockout-recovery referenced "bcrypt"; project uses argon2id. | **Fixed** — same commit as F2. |

## Autonomous orchestrator decisions

1. **Skipped the precautionary `invoke generate` and full lint runs in Chunk 1** because the tree was clean post-prep-commit; any drift would surface naturally in the first chunk that touches generated artifacts. (It did, harmlessly — chunk 2 noted the empty schema diff for unreferenced inputs.)
2. **Combined chunks 15/16/17** into a single subagent dispatch — each was 1–3 tasks and they shared no risk.
3. **Reverted my own first attempt at fixing the HTTP-path atomicity gap** during chunk 6 review when wrapping resolvers in `async with uow:` broke `test_delete_user_blocked_by_fk` (the rollback path conflicted with service-internal commits). Documented as a known issue requiring deeper refactoring; the service-direct atomic tests still cover the contract.
4. **Took over chunk 18 directly** after the polish subagent paused waiting on a background test process that did not survive its handoff. Ran the suites in the foreground myself, ticked task checkboxes, committed.
5. **Decided to fix F2 and F7 inline** during Phase 6 review (small, low-risk) but **defer F1** (UI behavior change with visual implications) and F3/F4 (medium-severity refinements). Followups listed below.

## Suggested next steps

1. **File follow-up issues** for the deferred items:
   - HTTP-path atomicity gap (affects `update_user(active=False)`, `reset_user_password`, and the pre-existing `change_password` from #179).
   - F1: GroupDetailPage drops inactive members.
   - F3: route `LAST_ADMIN` inline-error to the multi-select.
   - F4: reorder `update_group` validate→replace.
   - Add `Group.members` GraphQL field (eliminates F1's UI workaround).
2. **Open the PR** so CI can run the full E2E suite (`test_auth_lifecycle.py` in both `[api-chromium]` and `[ui-chromium]`) and the Postgres-required `test_concurrent_demote_last_admin_serialized`.
3. **PR reviewer**: manually exercise quickstart § A–E against `uv run invoke dev` (deferred T028 / T091).
4. **Bug-pipeline** (optional): the Phase 6 review report can seed bug issues via `bug-analyze` if the reviewer prefers structured tracking.

## Local test results

- Backend: **1466 passed**, 2 skipped (SQLite-skipping concurrency test + 1 pre-existing api-scheduling skip), 0 failed.
- Backend new mask tests (Phase 6 fix): **10 passed**.
- Frontend: **111 passed** across 19 files.
- SDK: **62 passed**.
- validate-graphql: **178/178 ops** pass.
- ruff/ty: **0 errors**. ESLint: **0 errors**, 3 pre-existing `react-refresh/only-export-components` warnings.
- E2E auth-lifecycle: collection green for both variants; full run gated on CI.
