---
description: "Task list for accepting prerelease application versions that fit a driver version's range"
---

# Tasks: Accept prerelease application versions that fit a driver version's range

**Input**: Design documents from `specs/032-prerelease-version-range/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/refusal-messages.md](contracts/refusal-messages.md), [quickstart.md](quickstart.md)

**Tests**: Required. The constitution (principle V) requires unit tests for new behaviour and an E2E test that is run to a pass. Each test task comes before the code task that makes it pass, and the test must fail first for the reason named in the task.

**Organization**: Tasks are grouped by user story so that each story can be built and checked on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story of [spec.md](spec.md) (US1 to US4)
- Paths are relative to the repository root `/Users/Simon/styrmin-591-spec`

## Notes for the implementer

- No database change, no GraphQL schema change, no new dependency, no CI change ([plan.md](plan.md), "Constitution Check"). So there is no Alembic revision, no `schema.graphql` regeneration, no SDK regeneration and no propagation test.
- Do not commit, push or open a pull request without the approval that the user's rules require. Do not add `Co-Authored-By` lines.
- Run Python tools with `uv run`. Do not read Python code for syntax errors: `uv run invoke format lint` is the authority (`AGENTS.md`).
- Run every E2E test with `--pdb`, and in a non-interactive shell prefix the command with `sleep infinity |` (`AGENTS.md`, "Debugging E2E Tests").

---

## Phase 1: Setup

**Purpose**: bring in the prior work of pull request #594 and record the starting state.

- [X] T001 Bring commit `fd90f8db` of pull request #594 onto this branch with `git cherry-pick fd90f8db` (fetch `origin/fix/591-prerelease-refusal-message` first). Expected: no conflict (a `git merge-tree` check on 2026-11-10 found none). If `develop` has changed `backend/styrmin_backend/services/deployment.py` or `CONTEXT.md` since and a conflict appears, resolve it by keeping both sides' intent. Afterwards confirm that `backend/styrmin_backend/services/deployment.py` contains `_unsupported_version_error` and `_prerelease_explanation`. This task changes the repository but is not committed until the user approves the message.
- [X] T002 Record the baseline by running `uv run pytest backend/tests/unit/services -q -x --no-header` on the cherry-picked branch and noting the pass and fail counts in the final report. PR #594 states that `test_send_report_returns_false_when_the_connection_is_refused` fails on untouched `develop`; confirm that on `develop` before treating it as caused by this change.

---

## Phase 2: Foundational (blocks all user stories)

**Purpose**: the shared check, the characterization of today's behaviour for an invalid version, and the refusal text without the old explanation.

**⚠️ CRITICAL**: no user story work begins until this phase is complete.

- [X] T003 Write the characterization test for FR-006 in `backend/tests/unit/services/test_driver_version_resolution.py`: call `_resolve_latest_matching_version` and `_ensure_pin_supports_version` with `latest` and `develop`, and assert the outcome that the current code gives (research D4: today `Version("latest")` raises `packaging.version.InvalidVersion` from the service function). First run the call on the unchanged code to learn the real outcome, then assert exactly that. The test must pass on the code before T006, and must still pass after the last task. Also check, with a short read of `backend/styrmin_backend/api/schema/`, how the GraphQL layer reports it, and write the answer in the docstring of the test.
- [X] T004 [P] Write the unit tests of the shared check in `backend/tests/unit/services/test_version_range.py` (new file). Parametrize every row of the boundary table in [data-model.md](data-model.md) (including the spellings `1.12.0-beta.1`, `1.12.0.b0`, `1.12.0_rc1`), add stable-version rows that must keep their old verdict (`1.9.0` and `2.0.0` against `>=1.5,<2.0`, FR-007), and a row showing that an invalid range text raises `packaging.specifiers.InvalidSpecifier`. The tests fail until T005 because the module does not exist.
- [X] T005 Create `backend/styrmin_backend/services/version_range.py` with `def version_fits_range(version: Version, supported_versions: str) -> bool`, which returns `SpecifierSet(supported_versions).contains(version, prereleases=True)`. Give it type hints and a docstring that states the rule and cites [PEP 440](https://peps.python.org/pep-0440/#handling-of-pre-releases). Import only from `packaging`. Run `uv run pytest backend/tests/unit/services/test_version_range.py -v` until it passes.
- [X] T006 Rework the refusal helper in `backend/styrmin_backend/services/deployment.py`: delete `_prerelease_explanation` and its two uses (in `_unsupported_version_error` and in `_ensure_pin_supports_version`). Keep the range list of `_unsupported_version_error` as message 1 of [contracts/refusal-messages.md](contracts/refusal-messages.md). Do not change the pin helper's signature yet (T021).
- [X] T007 Rewrite `backend/tests/unit/services/test_unsupported_version_message.py` (265 lines from #594, written for the old rule) for the new design: remove every assertion about the explanation, keep the assertions about the range list, its order (newest driver version first) and its absence of duplicates, and add a test that the message of a refused prerelease request does not contain the word "prerelease" (FR-005). Keep or drop each existing case by asking whether it still describes behaviour after T006; delete the others. Run the file until it passes.

**Checkpoint**: the shared check exists and is tested, the message no longer explains the old rule, and the behaviour for `latest` is recorded.

---

## Phase 3: User Story 1 - Deploy a prerelease with a standard driver (Priority: P1) 🎯 MVP

**Goal**: with the unchanged standard range `>=1.5,<2.0`, a request for `1.12.0b0` or `1.12.0-beta.1` creates a deployment, the stored version is the typed string, and a driver whose default version is a prerelease that fits its range loads.

**Independent test**: the new E2E node (T014) creates a deployment of `0.2.0-beta.1` with the session `simple-app` driver (range `>=0.1,<1.0`) and reads the stored version.

### Tests for User Story 1

> Write these first. Each must fail before its code task, for the reason given.

- [ ] T008 [US1] Add picker cases to `TestResolveLatestMatchingVersion` in `backend/tests/unit/services/test_driver_version_resolution.py`: `_resolve_latest_matching_version` returns the driver version for `1.12.0b0`, `1.12.0-beta.1` and `1.12.0.b0` against `>=1.5,<2.0`, returns `None` for `2.0.0b1`, and returns `None` for `1.12.0b0` against `>=1.12.0,<1.13`; and with two overlapping driver versions (`>=1.5,<2.0` and `>=1.12.0b0,<1.13`) the existing latest-wins order still decides. Fails before T011 because the prerelease cases return `None`. Also remove or rewrite the cases that #594 added to this file for the old rule.
- [ ] T009 [P] [US1] Create `backend/tests/unit/services/driver/test_default_version.py`: build the driver specification model the way `backend/tests/unit/services/driver/test_driver_info.py` does, and assert that `default_version: 1.12.0b0` loads with `supported_versions: ">=1.5,<2.0"`, that the same default fails with `>=1.12.0,<1.13` with the unchanged message `default_version '1.12.0b0' does not satisfy supported_versions '>=1.12.0,<1.13'`, and that a stable default behaves as before. Fails before T012 for the first case.
- [ ] T010 [US1] Create `backend/tests/unit/services/test_deploy_prerelease_version.py` in the style of `backend/tests/unit/services/test_deploy_skip_initial_reconcile.py` (same fakes from `backend/tests/unit/services/fakes.py`): call `deploy_application` with `1.12.0-beta.1` against a driver version of range `>=1.5,<2.0` and assert that the stored application version is exactly `1.12.0-beta.1` (FR-003); and call it with no version when the driver version's `default_version` is the prerelease `1.12.0b0` and assert that the default is used (research D9, which the PRD marked "not tested yet"). Fails before T011.

### Implementation for User Story 1

- [ ] T011 [US1] In `backend/styrmin_backend/services/deployment.py`, change `_resolve_latest_matching_version` to test the version with `version_fits_range(target, driver_version.application_supported_versions)` instead of `target in SpecifierSet(...)`. Import the function from `styrmin_backend.services.version_range`. Make T008 and T010 pass. Check that `SpecifierSet` is still imported only if another line uses it.
- [ ] T012 [US1] In `backend/styrmin_backend/services/driver/models/resources/driver.py`, change `validate_default_version` to use `version_fits_range(Version(self.default_version), self.supported_versions)`. Keep the error message text unchanged. Make T009 pass.
- [ ] T013 [US1] Run `uv run pytest backend/tests/unit/services/test_driver_version_resolution.py backend/tests/unit/services/test_deploy_prerelease_version.py backend/tests/unit/services/driver -q` and confirm that the characterization test of T003 still passes.
- [ ] T014 [US1] Add the E2E node `test_deploy_prerelease_simple_app` to `backend/tests/e2e/test_deploy_app.py` (the file's `pytestmark` already carries `shard_general`; add no new shard marker). Use the session fixtures of the file and the session `simple-app` driver with its unchanged range. Steps for this task: (a) a module-scoped fixture that runs `docker tag <simple_app_image_v2> simple-app:0.2.0-beta.1` and removes only that tag afterwards (the string typed is the non-canonical spelling, so that FR-003 is a real assertion; see research D6); (b) create a deployment of `0.2.0-beta.1` through the `scenario_driver` method that creates a deployment, wait until it runs, and assert that the stored application version equals `0.2.0-beta.1`. Try the `[ui-chromium]` variant (the Deploy form pins the selected driver version, see research D7). If the Deploy form refuses the string, mark the node `@pytest.mark.api_only(reason=...)` with that reason and note the Deploy-form behaviour in the final report as a separate issue. Run `sleep infinity | uv run pytest backend/tests/e2e/test_deploy_app.py -k prerelease -v -s --pdb` and keep the output for T032.

**Checkpoint**: User Story 1 works and can be checked on its own with the node of T014.

---

## Phase 4: User Story 2 - Apply the same rule when changing a deployment (Priority: P2)

**Goal**: upgrading to a prerelease, following a beta to its release, and pinning a driver version while asking for a prerelease give the same verdict as creating one.

**Independent test**: the unit tests of T015 and T016, and the upgrade step of the node in T019.

### Tests for User Story 2

- [ ] T015 [US2] Add pin cases to `backend/tests/unit/services/test_driver_version_resolution.py`: `_ensure_pin_supports_version` accepts `1.12.0b0` for a pinned driver version of range `>=1.5,<2.0`, refuses `2.0.0b1` with `InvalidVersionError`, and refuses `1.12.0b0` for a pin with range `>=1.12.0,<1.13`. Fails before T017 for the accepting case.
- [ ] T016 [US2] Add upgrade cases for `update_deployment_version`, in the style of `backend/tests/unit/services/test_update_version_hook_check.py` or `backend/tests/unit/services/test_update_deployment_noop.py` (read both first and extend the one whose fakes fit): a deployment of `1.11.9` upgrades to `1.12.0b0` without a pin, with a pin of a driver version that fits, and a deployment of `1.12.0b0` upgrades to `1.12.0`. Fails before T017 for the cases that need the prerelease to be accepted.

### Implementation for User Story 2

- [ ] T017 [US2] In `backend/styrmin_backend/services/deployment.py`, change `_ensure_pin_supports_version` to use `version_fits_range(Version(version), pinned.application_supported_versions)`. Make T015 and T016 pass.
- [ ] T018 [US2] Create `backend/tests/unit/services/test_version_verdict_parity.py` for FR-002 and SC-002: run every row of the boundary table of [data-model.md](data-model.md) through the three call sites (`_resolve_latest_matching_version`, `_ensure_pin_supports_version`, and the driver specification's `default_version` validator) and assert that all three give the same verdict as `version_fits_range`, with 0 differences. Import the table from one shared constant (put it in `backend/tests/unit/services/test_version_range.py` or a small helper next to it) so that the tests of T004 and this one cannot drift.
- [ ] T019 [US2] Extend the E2E node of T014: after the deployment of `0.2.0-beta.1` runs, upgrade it to `0.2.0` through the `scenario_driver` method that upgrades a deployment (use the existing `simple_app_image_v2` fixture, which provides the image `simple-app:0.2.0`), wait until it runs, and assert the stored version is `0.2.0`. Re-run the node as in T014 and keep the output for T032.

**Checkpoint**: create, upgrade and pin give the same verdict (T018), and the E2E follows a beta to its release.

---

## Phase 5: User Story 3 - A version outside the range is refused with the supported ranges (Priority: P3)

**Goal**: a refused create, upgrade or pin request names the version and lists every supported range of the driver, and never explains a prerelease rule.

**Independent test**: request `2.0.0b1` with a driver of range `>=1.5,<2.0` and read the message (unit test of T020 and E2E step of T022).

### Tests for User Story 3

- [ ] T020 [US3] Add tests to `backend/tests/unit/services/test_unsupported_version_message.py` for [contracts/refusal-messages.md](contracts/refusal-messages.md): message 1 for an unpinned request of `2.0.0b1` names the version and lists every range once, newest driver version first; message 2 for a pin refusal names the version, the pinned driver version id and its range, and then lists `Supported ranges of the application driver {name}:` with every range of the driver; neither message contains "prerelease"; no resource is created when the error is raised (assert on the fakes of the unit-of-work). Fails before T021 for message 2.

### Implementation for User Story 3

- [ ] T021 [US3] In `backend/styrmin_backend/services/deployment.py`, change `_ensure_pin_supports_version` to take the `ApplicationDriver` as a second argument and build message 2 of the contract with the ranges of the driver, using the same ordered and de-duplicated list as `_unsupported_version_error` (extract the list into one small helper that both use). Update its two callers: in `update_deployment_version` (near the line that calls `_ensure_pin_supports_version(target_driver_version, version)`, where `application_driver` is already loaded) and in `deploy_application` (near `_ensure_pin_supports_version(pinned_driver_version, version)`, where the driver is `application`). Make T020 pass, then re-run T013's command.
- [ ] T022 [US3] Extend the E2E node of T014: after the upgrade, request `1.0.0b1` twice with the SDK, once unpinned and once with `driver_version_id` set to the session driver version, and assert for each that `StyrminAPIError` is raised, the message contains `1.0.0b1` and the range `>=0.1,<1.0`, the message does not contain "prerelease", and the list of deployments of the environment is unchanged. Re-run the node as in T014 and keep the output for T032.

**Checkpoint**: every refusal path lists the ranges and none explains a prerelease rule.

---

## Phase 6: User Story 4 - Driver authors learn how a prerelease is ordered (Priority: P4)

**Goal**: the documentation, the glossary and the changelog describe the new rule and the ordering of a prerelease below its release (FR-008, constitution principle VII).

**Independent test**: read the page and find the rule, the ordering and the range `>=1.12.0b0,<1.13`; the docs build passes.

- [ ] T023 [P] [US4] Rewrite the section "Prereleases in `supported_versions`" in `docs/docs/drivers/creating-a-driver.md` (brought in by T001) for the new rule: a range accepts a prerelease when its numbers fit; PEP 440 orders a prerelease below its final release, so `>=1.12.0,<1.13` refuses `1.12.0b0` and a prerelease of the upper bound (`2.0.0b1` against `<2.0`) is refused; to accept the prereleases of 1.12.0, write `>=1.12.0b0,<1.13`; a stable-looking range such as `>=1.5,<2.0` now also accepts `1.9.0rc1`; state that there is no way for a driver to forbid prereleases. Replace the table of #594 with one that matches the table in [data-model.md](data-model.md). Remove the sentences about "names a prerelease", `!=` clauses and the explanation in the error. Keep the anchor `#prereleases-in-supported_versions` so existing links work.
- [ ] T024 [P] [US4] In `docs/docs/drivers/loading-drivers.md`, change the sentence that #594 added about a pin (a prerelease "is included only if the range names a prerelease") to state that a prerelease is accepted when its numbers fit the range, and keep the link to the section of T023.
- [ ] T025 [P] [US4] In `CONTEXT.md`, rewrite the glossary entry **Prerelease** (added by #594) to say that a driver version's range accepts a prerelease when its numbers fit, and extend **Application version** to say that the typed text is stored unchanged and a prerelease may be requested. Use the terms of the glossary (driver version, application version, deployment). Do not describe how the check is built.
- [ ] T026 [P] [US4] Rewrite `changelog/591.changed.md` (brought in by T001): one line that says a prerelease application version such as `1.12.0b0` is now accepted when its numbers fit a driver version's range, and that the error for an unsupported version now lists the supported ranges. Follow `dev/guidelines/changelog.md`. Do not edit `CHANGELOG.md`.
- [ ] T027 [US4] Run `cd docs && pnpm build` and confirm that it passes and that the anchor of T023 exists.

**Checkpoint**: documentation, glossary and changelog match the new behaviour.

---

## Phase 7: Polish and cross-cutting checks

- [ ] T028 Remove the pieces of #594 that the new rule makes unnecessary: delete `backend/tests/e2e/test_prerelease_version.py`, and delete the helper `publish_simple_app_driver_build` from `backend/tests/e2e/helpers/drivers.py` if `grep -rn publish_simple_app_driver_build backend/tests` finds no other user. Confirm that `backend/tests/e2e/helpers/drivers.py` still imports cleanly.
- [ ] T029 Check once how `styrminctl` and the UI show a refusal, as in [quickstart.md](quickstart.md) step 6: request `2.0.0b1` with `styrminctl deployments create` and in the Deploy form (use the Playwright MCP server for the form, as `AGENTS.md` asks for UI work). Record what each shows in the final report. A rendering defect is a separate issue, not part of this change.
- [ ] T030 Search for stale statements about the old rule: `grep -rn "names a prerelease\|only if one of its clauses" docs dev CONTEXT.md backend changelog` must return nothing outside the files of this specification.
- [ ] T031 Run `uv run invoke format lint` and fix every finding it reports.
- [ ] T032 Run the whole backend suite with `uv run invoke test` and compare with the baseline of T002. Then record the E2E evidence required by constitution principle V in `specs/032-prerelease-version-range/e2e-evidence.md`: the pytest node id, the exact command, the ISO 8601 time of the passing run, the cluster identifier (the `vcluster` fixture id and the kubeconfig path under `/tmp/pytest-of-*/pytest-*/`) and the verbatim `PASSED` line. If the node is dual-entrypoint, record both variants. If the evidence cannot be produced, do not mark the work done; report it.
- [ ] T033 Walk through [quickstart.md](quickstart.md) steps 1 to 6 once and tick each expected result. Step 4 (a real `infrahub` driver at `1.12.0b0`) is optional: if it is not run, say in the final report that it was not verified.

---

## Dependencies and execution order

### Phase dependencies

- **Phase 1 (T001, T002)**: first. T002 needs T001.
- **Phase 2 (T003 to T007)**: needs Phase 1. T003, T004 and T006 can start together; T005 needs T004; T007 needs T006. Blocks every story.
- **Phase 3 (US1)**, **Phase 4 (US2)**, **Phase 5 (US3)**: need Phase 2. They edit the same files (`deployment.py`, `test_driver_version_resolution.py`, one E2E node), so run them in the order P1, P2, P3 on one branch. T019 and T022 extend the node that T014 creates.
- **Phase 6 (US4)**: needs T001 only for the files it edits; it can run in parallel with Phases 3 to 5, but its wording must match the final behaviour, so finish it after T021.
- **Phase 7**: last. T028 needs T014, T019 and T022. T032 needs everything else.

### Within each story

- Tests first, and each must fail for the stated reason before its code task.
- Code tasks before the E2E task of the story.

### Parallel opportunities

- T003, T004 and T006 touch different files.
- T008 (picker tests), T009 (driver-load tests) and T010 (deploy tests) are in different files and can be written together; T011 and T012 are in different files too.
- T023, T024, T025 and T026 are in four different files.

### Parallel example: documentation (US4)

```text
Task: "Rewrite the section 'Prereleases in supported_versions' in docs/docs/drivers/creating-a-driver.md"
Task: "Update docs/docs/drivers/loading-drivers.md"
Task: "Rewrite the Prerelease entry in CONTEXT.md"
Task: "Rewrite changelog/591.changed.md"
```

---

## Implementation strategy

### First deliverable: User Story 1

1. Phase 1 and Phase 2 (the shared check and the recorded behaviour).
2. Phase 3 (US1): the beta deploys with the unchanged driver. Stop and check the E2E node.

### Then, in priority order

3. Phase 4 (US2): upgrade and pin follow the same rule, with the parity test.
4. Phase 5 (US3): every refusal lists the ranges.
5. Phase 6 (US4): documentation, glossary and changelog.
6. Phase 7: remove what #594 left over, lint, run the suite, record the E2E evidence.

### Not known when these tasks were written

- Whether the Deploy form accepts the typed prerelease string in the UI variant of the E2E (T014).
- How `styrminctl` and the UI render the longer message (T029).
- The outcome that today's code gives for `latest` (T003).
- What happens to pull request #594 itself: for the maintainers to decide.
