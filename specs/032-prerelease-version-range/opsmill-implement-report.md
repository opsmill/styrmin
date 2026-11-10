# Implementation report: accept prerelease application versions that fit a driver version's range

**Status**: COMPLETE. All 33 tasks of [tasks.md](tasks.md) are ticked. Every new or modified test has local-pass evidence (section 4).

- **Spec directory**: `specs/032-prerelease-version-range`
- **Branch**: `sas-591-prerelease-spec`
- **Base commit** (HEAD when the implementation started): `43cab082`
- **Head commit** (after the review fixes): `467f5ec3`
- **Wall-clock time**: not recorded.
- **Source**: [issue #591](https://github.com/opsmill/styrmin/issues/591), [PRD comment](https://github.com/opsmill/styrmin/issues/591#issuecomment-6762618486).

## 1. Chunk ledger

Each chunk ran in its own subagent with a clean context. The subagents were told not to commit, because the user approves every commit message. The orchestrating session checked each chunk (read the production diff, re-ran the affected tests) and committed after the user approved the message and file list.

| Chunk | Tasks | Outcome | Commit | Flagged by the subagent or the orchestrator |
|---|---|---|---|---|
| 1. Setup | T001, T002 | 2 done | `22acc12c` | The cherry-pick of `fd90f8db` (PR #594) applied without a conflict. Baseline on the cherry-picked branch: 1 failed, 2337 passed. The failure, `test_send_report_returns_false_when_the_connection_is_refused`, also fails on `develop` (7.92 s against a limit of 2 s). |
| 2. Foundational | T003 to T007 | 5 done | `a48097aa` | For `latest`, both helpers raise `packaging.version.InvalidVersion` before any range is read. The API masks it as `INTERNAL_ERROR` (read from `api/errors.py`, not run through a request). This behaviour is kept (FR-006) and recorded by tests. |
| 3. User story 1, unit tests and wiring | T008 to T013 | 6 done | `c0a5c880` | The picker and the driver-load check use the shared check. The cases from #594 that asserted the old rule were deleted. |
| 4 and 5. E2E node, then user story 2 | T014 to T019 | 6 done | `ff4de066` | The Deploy form accepts the typed prerelease and pins the selected driver version. The UI variant failed on the first run only because the pin check still used the old rule; it passed once the pin check was changed. The two variants cannot run in one pytest session (the shared Styrmin instance blocks "New Cluster" after the API variant), so they ran separately, as CI does. These two chunks are one commit because the node needs the pin change to pass in the UI variant. |
| 6. User story 3 | T020 to T022 | 3 done | `7b3bef02` | The pin refusal now lists every range of the application driver (contract message 2). One helper builds the list for both messages. |
| 7. User story 4 | T023 to T026 | 4 done | `2bd88b47` | Docs, glossary and changelog rewritten for the new rule. T027 (docs build) ran in chunk 8 after the user allowed `pnpm install`. |
| 8. Polish | T027 to T033 | 7 done | `957d24e0` | Docs build exit 0 with the anchor present. Lint exit 0. Full suite: 1 failed (the known timing test), 5902 passed, 8 skipped. The obsolete E2E file and helper from #594 were deleted. |
| Review fixes | none (review findings) | see section 5 | `467f5ec3` | Comments only in production code. |

The planning commits before the implementation are `ea1e3c98` (specify), `13be57cd` (plan), `2e73711a` (critique), `daf068f8` (tasks) and `43cab082` (alignment check).

## 2. Tasks not completed

None. All 33 tasks are `[X]` in `tasks.md`.

One task criterion is met in substance and not to the letter: T030 asks that the search for the old-rule wording returns nothing. It returns 3 hits in `version_range.py` and its tests. All 3 read as true under the new rule ("fits the range", "names a prerelease" in a test of a range that does name one), so nothing was changed.

## 3. Production change in one paragraph

A new function `version_fits_range` (`backend/styrmin_backend/services/version_range.py`) returns `SpecifierSet(range).contains(version, prereleases=True)`. The driver version picker and the pin check (`backend/styrmin_backend/services/deployment.py`) and the default-version check at driver load (`backend/styrmin_backend/services/driver/models/resources/driver.py`) use it. A refused create, upgrade or pin request names the version and lists every supported range of the driver. The stored application version is the text the person typed. No database, GraphQL schema, dependency, CI or driver change.

## 4. Local-pass evidence

### Unit tests (no environment context needed)

The affected files, run together by the orchestrating session after the review fixes:

`uv run pytest backend/tests/unit/services/test_driver_version_resolution.py backend/tests/unit/services/test_unsupported_version_message.py backend/tests/unit/services/test_version_verdict_parity.py backend/tests/unit/services/test_deploy_prerelease_version.py backend/tests/unit/services/test_update_deployment_noop.py backend/tests/unit/services/test_version_range.py backend/tests/unit/services/driver/test_default_version.py -q --no-header -p no:cacheprovider`

Verbatim result line: `425 passed in 0.55s`. The time of that run was not recorded; it followed the commit `957d24e0` and preceded `467f5ec3`.

| Test file | Type | Added or modified | Passed at (ISO 8601) | Verbatim pass line |
|---|---|---|---|---|
| `backend/tests/unit/services/test_version_range.py` | unit | added (chunk 2), extended (review fixes) | 2026-11-10T08:47:11Z (chunk 2, 22 tests); final run in the combined command above | `22 passed in 0.04s` (chunk 2); `425 passed in 0.55s` (combined) |
| `backend/tests/unit/services/test_driver_version_resolution.py` | unit | modified (chunks 2, 3, 5, review fixes) | 2026-11-10T08:53:55Z (chunk 3, 27 tests) | `============================== 27 passed in 0.16s ==============================` (chunk 3 command); combined run above |
| `backend/tests/unit/services/driver/test_default_version.py` | unit | added (chunk 3) | 2026-11-10T08:53:55Z | included in the `27 passed` line above, and in `363 passed in 3.10s` (orchestrator, `.../driver` directory) |
| `backend/tests/unit/services/test_deploy_prerelease_version.py` | unit | added (chunk 3), extended (review fixes) | 2026-11-10T08:53:55Z | included in the `27 passed` line above; combined run above |
| `backend/tests/unit/services/test_unsupported_version_message.py` | unit | rewritten (chunk 2), extended (chunk 6, review fixes) | 2026-11-10T08:47:38Z (chunk 2, 10 tests) | `10 passed in 0.17s` (chunk 2); combined run above |
| `backend/tests/unit/services/test_version_verdict_parity.py` | unit | added (chunk 5), modified (chunk 6, review fixes) | chunk 5: after the pin change; 2026-11-10T09:55:50Z (chunk 6, with other files) | `449 passed in 2.63s` (chunk 6, several files); combined run above |
| `backend/tests/unit/services/test_update_deployment_noop.py` | unit | extended (chunk 5, review fixes) | chunk 5 run; review-fix run 2026-11-10T10:57:18Z | `421 passed in 0.64s` (review-fix subagent's command over six files); combined run above |

Fails-first runs (seen before the code change, quoted by the subagents): the picker cases failed with `AssertionError: assert None is ApplicationDriverVersion(...)`; the deploy tests failed with `InvalidVersionError: Version 1.12.0-beta.1 is not supported by the application driver infrahub (supported ranges: >=1.5,<2.0).`; the default-version test failed with `Value error, default_version '1.12.0b0' does not satisfy supported_versions '>=1.5,<2.0'`; the pin tests failed on 2 cases and the parity test on 7 rows; the message-2 test failed with `5 failed, 13 passed`.

Full backend suites: `uv run invoke test` gave `1 failed, 5902 passed, 8 skipped, 41 warnings in 314.15s`. The unit suite after the review fixes gave `1 failed, 5316 passed, 6 skipped in 157.90s` (the review-fix subagent's run). In both, the one failure is the timing test that also fails on `develop`.

### E2E tests

Node: `backend/tests/e2e/test_deploy_app.py::test_deploy_prerelease_simple_app`, one row per variant. The full record, including the history of earlier runs and what the logs do not show, is in [e2e-evidence.md](e2e-evidence.md).

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `...::test_deploy_prerelease_simple_app[api-chromium]` | e2e | `sleep infinity \| uv run pytest backend/tests/e2e/test_deploy_app.py -k "prerelease and api-chromium" -v -s --pdb` (reported by the subagent; the log does not contain the command) | 2026-11-10T10:02:13Z (derived from the log's clock time `11:02:13` and the recorded start `2026-11-10T09:57:02Z`) | vCluster `pytest-74c59121-a85a-4dab-8265-b9f0e800d6c2`; kubeconfig `/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1384/vcluster0/kubeconfig` (reported by the subagent; the directory no longer exists, so not verified) | `=========== 1 passed, 11 deselected, 4 warnings in 313.40s (0:05:13) ===========` |
| `...::test_deploy_prerelease_simple_app[ui-chromium]` | e2e | same, with `-k "prerelease and ui-chromium"` | 2026-11-10T10:07:31Z (derived the same way) | vCluster `pytest-bd2fd0ad-c909-4b21-92ab-941e5462d72a`; kubeconfig `/var/folders/h8/b5b4gccj4h5c0sjlqjymm1y40000gq/T/pytest-of-Simon/pytest-1387/vcluster0/kubeconfig` (file found on disk, names the cluster) | `=========== 1 passed, 11 deselected, 4 warnings in 307.14s (0:05:07) ===========` |

Both E2E runs were made on the code of `7b3bef02`, before it was committed. `git diff 7b3bef02 HEAD` for `backend/tests/e2e/test_deploy_app.py` and `backend/styrmin_backend` is empty except comments in `deployment.py` (review fixes, comments only). No E2E test was re-run after the deletion of `test_prerelease_version.py` (a different file); the collection of all 225 E2E tests gave no error.

## 5. Review findings

The `speckit-review-run` workflow ran three read-only reviewers in parallel (code, tests, comments and errors) on `43cab082..957d24e0`. The type-design review was skipped because the change adds no type. The simplify review was skipped because it edits code and the run was report-only.

| Severity | File | Finding | Handling |
|---|---|---|---|
| Critical | none | none found | none |
| Important | `test_driver_version_resolution.py` | the overlapping-ranges test also passed on the old code | fixed: older build names the prerelease, newer build does not; the newer must win. Shown to fail on the old rule. |
| Important | `test_unsupported_version_message.py` | the last test of `TestPrereleaseAcceptedWhenARangeNamesOne` passed before and after | fixed: renamed to what it shows, and a new test that fails on the old rule was added |
| Important | tests | no test for a driver without driver versions | fixed |
| Important | tests | no test for a create with a pin and a prerelease through `deploy_application` | fixed |
| Important | tests | `latest` only tested on the helpers | fixed: through `deploy_application` and `update_deployment_version`, pinned and unpinned |
| Important | `CONTEXT.md:138`, `creating-a-driver.md:263` | "A driver cannot forbid prereleases" is false (`==` and `!=` clauses refuse some) | fixed in both places, and a table row added |
| Minor | `test_version_range.py` | the check that stable versions keep their verdict had two rows | fixed: 273-case matrix compared with the default matching; shown to fail for a mutated check |
| Minor | tests | pin setup built inside `pytest.raises` blocks | fixed |
| Minor | `test_unsupported_version_message.py` | misleading comment on text order | fixed (reworded more widely, see section 6) |
| Minor | `creating-a-driver.md` | line 200 could be read as excluding prereleases; "binds those deployments" holds for creates and upgrades only | fixed |
| Minor | `loading-drivers.md` | dangling clause after the inserted link | fixed |
| Minor | `deployment.py` | docstring and comment said "specifier matches" | fixed, comments only |
| Minor, left as it is | `test_deploy_app.py` | `contextlib.suppress(Exception)` hides a failed cleanup in the E2E node; the delete is not awaited to completion (not verified) | kept: changing it needs a new E2E run, and the docstring states "best effort". A warning log in that handler would be a follow-up. |
| Minor, left as it is | `deployment.py` `_supported_ranges` | an empty stored range (`""`) would show as an empty entry | kept: not verified against a loaded driver, and unlikely |
| Minor, left as it is | `deployment.py` | the pin refusal for a driver without versions would end "...: ." | kept: a pin always belongs to a driver with at least one version (checked by a reviewer) |
| Minor, left as it is | refusal text | ranges are joined with ", " although a range contains commas | kept: the contract specifies it |
| Minor, left as it is | `docs/docs/reference/driver-api.md`, `driver/DRIVERS.md`, `core-concepts.md`, `what-is-a-driver.md` | still call the range a "semver specifier" | kept: wording was already inexact before this change |
| Minor, left as it is | test design | the shared boundary table has no oracle independent of `packaging` | kept: that is the library the rule relies on |

Counts: 0 critical, 6 important (all fixed), 12 minor (6 fixed, 6 left as they are, listed above).

## 6. Autonomous decisions

- The user's rule requires approval of every commit message and file list, so the subagents did not commit and the orchestrating session asked before each of the 8 implementation commits. The chunks 4 and 5 were committed together so that no commit leaves the UI variant of the E2E node failing.
- The E2E node reuses the session `simple-app` driver (range `>=0.1,<1.0`, unchanged) and extends `test_deploy_app.py`, instead of the separate E2E file and driver build of PR #594. The old file and its helper were deleted.
- The cherry-pick of #594 was used as the base. What happens to pull request #594 itself is still a decision for the maintainers.
- The review-fix subagent reworded the comment in the "newest driver version first" test more widely than asked, because ascending text order gives the same result as the driver version order in that case. It also added the row `<2.0,!=1.12.*` to the docs table, which it checked with `packaging` 25.0.
- `pnpm install --frozen-lockfile` was run in `docs/` and `frontend/` after the user allowed it. It wrote only to the git-ignored `node_modules`.

## 7. Not verified

- The new refusal message with the list of ranges was not displayed by `styrminctl` or the UI against a real server. The CLI was checked with a mocked SDK error. The UI was checked from the earlier failing run, which showed the old pin message in the Deploy form's alert ([quickstart-results.md](quickstart-results.md), step 6).
- A deployment of the real `infrahub` driver at `1.12.0b0` (quickstart step 4): not run.
- The kubeconfig path of the `[api-chromium]` run, and the exact pytest command line of both runs (no log contains it).
- The GraphQL layer's report for `latest` (read, not run through a request).

## 8. Suggested next steps

1. Decide what happens to pull request #594 (close it, or replace it with this branch). The first commit of this branch carries its content.
2. Before a pull request is opened, run the two gates that the user's rules require and that this run did not replace: a separate agent runs the `code-review` skill at level `high`, and another runs the `security-review` skill. This implementation run reviewed the diff with three reviewers, which is not the same gate. No dependency is added, so no dependency scan is needed.
3. Optional: a deployment of the real `infrahub` driver at `1.12.0b0` on a cluster with the standard drivers (quickstart step 4), and a look at the refusal message in the UI and the CLI against a running stack.
4. Optional follow-up: log a warning instead of suppressing the cleanup error in the E2E node.
