# Pull Request Notes: Recorded Demos of Four Styrmin Features

## Summary

For the beta presentation ([#518](https://github.com/opsmill/styrmin/issues/518)), a presenter needs one video for each of four Styrmin features: deploy and upgrade, component overrides, environment backup and restore, and environment clone. This branch adds `uv run invoke record`, which records the demos on the local demo stack and writes one MP4 video for each ([spec](spec.md), [plan](plan.md)).

Two of the four demos can be recorded today: `component-overrides` (demo 2) and `backup-restore` (demo 3). Not done or not decided yet:

- Demo 1 (`deploy-upgrade`) waits for [#372](https://github.com/opsmill/styrmin/issues/372), and demo 4 (`clone`) waits for [#530](https://github.com/opsmill/styrmin/issues/530). Both issues are open.
- The maintainer has not yet confirmed that demos 3 and 4 may show the `infrahub-enterprise` driver.
- Nobody has played a video in Keynote, PowerPoint and Google Slides yet (task T047).
- Commit `472fe403` must be moved off the branch before it is pushed.

Suggested title: `test(e2e): record demos of Styrmin features for the beta presentation (#518)`.

## Changes in this pull request

- Playwright 1.58.0 to 1.64.0 in the root `dev` dependency group (`pyproject.toml`, `uv.lock`), for its Screencast API.
- E2E page objects (`backend/tests/e2e/pages/`) and `UiScenarioDriver`:
  - every page-object class and `UiScenarioDriver` take `keystroke_delay_ms: int | None = None`;
  - every `.fill(...)` call goes through `enter_text` in `pages/_dom.py`, which calls `fill` when the delay is `None` and types one key at a time otherwise;
  - `DeploymentDetailPage` gains `open_timeline`, `read_task_ids`, `wait_for_new_task` and `show_component_overrides`.

  The E2E suite keeps `None`, because `backend/tests/e2e/conftest.py` does not pass the argument.
- The demo package `backend/tests/e2e/demos/`: run loop and summary, prerequisites check, catalog, recorder, video planning and ffmpeg encoding, SDK helpers for the demo stack, Infrahub and Semaphore setup and page objects, the demo Semaphore image (`semaphore/Dockerfile`), the Infrahub versions file, and the scenarios of demos 2 and 3.
- Unit tests in `backend/tests/unit/demos/`, `backend/tests/unit/test_e2e_page_typing.py` and `backend/tests/unit/test_e2e_timeline_wait.py`.
- The `record` task in `tasks/demo.py`, registered in `tasks/__init__.py`, and `demo-videos/` in `.gitignore`.
- The line `Active plan: [specs/029-recorded-feature-demos/plan.md](specs/029-recorded-feature-demos/plan.md)` in `CLAUDE.md`, which the speckit plan step added.
- Documentation: "Recording the demos" and two troubleshooting items in [`dev/guides/local-demo.md`](../../dev/guides/local-demo.md), and "Page objects shared with the recorded demos" in [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md).
- The FR-016 alias check in `test_environment_clone_lifecycle` (commit `472fe403`), which must leave the branch before it is pushed (see [Steps before the branch is pushed](#steps-before-the-branch-is-pushed)).

No product code, GraphQL schema, SDK, `styrminctl`, frontend, database schema, application driver or CI workflow changes (FR-018).

## Evidence

- [e2e-evidence.md](e2e-evidence.md): the two failing runs of the FR-016 alias check (T006, T007), the passing UI smoke run with Playwright 1.64 (T011), and the decision on the defect (T008).
- [spike-notes.md](spike-notes.md): the checks of the deployments, the screencast and the Semaphore inventory on the demo stack, and the first recordings of demos 2 and 3 with the changes made after watching them.
- [full-run.log](full-run.log): the prerequisites check (T041), the run of all available demos on a fresh demo stack (T042), and a failed and re-recorded run of demo 3 (T043).

Summary of the run of all available demos, from 2026-10-18T22:35:28Z to 22:57:43Z (22 min 15 s), exit code 0, quoted from [full-run.log](full-run.log):

```text
Demo                 Result    Video                                  Length
component-overrides  recorded  demo-videos/2-component-overrides.mp4  0:45
backup-restore       recorded  demo-videos/3-backup-restore.mp4       1:03
```

Both videos are H.264, `yuv420p`, 1920×1080, 30 frames per second, with no audio stream and with `faststart`. After the run, only the `local` environment remained and no `styrmin-<deployment id>` namespace was left. The re-run of demo 3 after a failed run took from 23:17:07Z to 23:37:47Z and wrote a video of 1:09.

Checks run for the pull request on 2026-10-18:

- `uv run invoke test`: `5081 passed, 3 skipped, 36 warnings in 213.39s (0:03:33)`, ended at 2026-10-18T23:44:51Z, exit code 0. After the pytest summary, the Prefect log handler printed `--- Logging error ---` with `ValueError: I/O operation on closed file.` for the message `Stopping temporary server on http://127.0.0.1:8413`. The exit code stayed 0. Whether this happens on `develop` too is not known.
- `uv run invoke format lint`: exit code 0 at 2026-10-18T23:48:30Z. ruff format left 990 files unchanged, ruff and ty printed `All checks passed!`, rumdl found no issue, all 274 `.graphql` files passed validation, and the generated types were up to date.

## Approved exception to Constitution §V

The demo scripts have no E2E test. The grilling session of 2026-10-17 approved this exception ([spec Clarifications](spec.md)). The agreed proof is one run of all four demos on a demo stack that `uv run invoke start` just created, with the command output attached to the pull request. Because demos 1 and 4 are not available, the run covered demos 2 and 3 only ([full-run.log](full-run.log)). The output above and the log are the proof for the two demos this pull request adds. Demos 1 and 4 need their own run when they land. Whether a run of two demos is enough for the exception is a question for the maintainer (see [Questions for the maintainer](#questions-for-the-maintainer)).

## Governance gates crossed

The constitution's gate "New dependencies" applies to three items, all approved in the grilling session of 2026-10-17 ([spec Clarifications](spec.md)):

- Playwright 1.58.0 to 1.64.0. This also changes the Chromium build that the UI E2E tests run in, locally and in CI. CI installs the browser with `uv run playwright install chromium`, which follows the lock file, so no workflow change is needed.
- `ffmpeg` on the developer's PATH, any build with libx264. Only `uv run invoke record` needs it. CI does not run the demos.
- A Semaphore image built locally, `styrmin-demo/semaphore:v2.16.47`, from `semaphoreui/semaphore:v2.16.47` with the `opsmill.infrahub` Ansible collection 1.8.3, `infrahub-sdk`, and the demo playbook and inventory file. It is never pushed to a registry (FR-015).

No other gate is crossed: no database schema, GraphQL schema, CI workflow, or authentication change.

## Questions for the maintainer

### The approved exception asked for a run of all four demos

The exception to Constitution §V asked for one run of all four demos ([spec Clarifications](spec.md)). The run in [full-run.log](full-run.log) covered demos 2 and 3, because demos 1 and 4 wait for [#372](https://github.com/opsmill/styrmin/issues/372) and [#530](https://github.com/opsmill/styrmin/issues/530). The maintainer has not yet confirmed that this run is enough for this pull request.

### Demos 3 and 4 show the `infrahub-enterprise` driver

An environment backup of Infrahub runs `neo4j-admin database backup`, which needs Neo4j Enterprise. The `infrahub` driver deploys the community chart, and its backup E2E test is skipped with the reason "backup/restore not supported with community". So demo 3 deploys the `infrahub-enterprise` driver, whose chart sets `neo4j.edition: enterprise` and `acceptLicenseAgreement: "yes"`, and demo 4 will too ([research R-007](research.md#r-007-environment-backups-need-the-infrahub-enterprise-driver)). Demo 2 deploys `infrahub`. The beta audience may ask why two Infrahub editions appear ([critique P2](critiques/critique-20261017.md)).

Question: is it acceptable that demos 3 and 4 show the Enterprise edition?

### The FR-016 alias check fails, filed as #530

The FR-016 check failed on both variants of `test_environment_clone_lifecycle`, as research [R-013](research.md#r-013-a-clones-alias-services-point-to-the-source) expected: the counterpart deployment's namespace kept an alias Service whose `spec.externalName` points to a namespace of the source environment ([e2e-evidence.md](e2e-evidence.md)). The defect is filed as [#530](https://github.com/opsmill/styrmin/issues/530), "fix(clone): a clone keeps the source's service aliases, which point to the source environment's namespaces". The maintainer decided on 2026-10-18 that:

- the product fix is made in its own issue and pull request;
- the FR-016 assertion stays as written, with no `xfail`;
- demo 4 waits for the fix.

## Work this pull request does not finish

- Demo 1 (`deploy-upgrade`, tasks T033 and T034) waits for [#372](https://github.com/opsmill/styrmin/issues/372), "actions of drivers loaded from a local directory are never registered and never run". The demo stack loads the `infrahub` driver from a local directory, so the upgrade does not run the driver's upgrade action and Infrahub 1.11.7 runs on a database that `infrahub upgrade` has not migrated. The maintainer decided on 2026-10-18 that demo 1 waits for the fix ([spike-notes.md](spike-notes.md#the-upgrade-does-not-run-the-drivers-upgrade-action)).
- Demo 4 (`clone`, tasks T039 and T040) waits for [#530](https://github.com/opsmill/styrmin/issues/530) (see above).
- Task T047: play one video in Keynote, PowerPoint and Google Slides (uploaded to Google Drive) without conversion (SC-003). It needs a person with a Mac or Windows machine and access to the three applications. The result goes into [full-run.log](full-run.log).
- Quickstart §3 expects four videos. The run produced two, for the reasons above.

## Steps before the branch is pushed

- Move commit `472fe403` ("test(e2e): check that a clone's service aliases stay in the clone") off the branch. Later commits sit on top of it, and the check fails until #530 is fixed ([e2e-evidence.md](e2e-evidence.md#decision-on-the-defect-t008)). After that, `e2e-evidence.md` still describes the runs of a check that this pull request no longer contains.
- `develop` has 77 commits that the branch does not have (counted on 2026-10-18). Whether the branch rebases on `develop` without conflicts is not known.

## Check of the page-object change in CI

The local UI smoke run of task T011 ended at 2026-10-18T10:07:20Z, before the page-object commit `b6c85a35` (10:56:49Z). It checks the Playwright upgrade, not the page-object change. No other E2E test ran locally after the page-object change. The demos ran the page objects with a delay of 45 ms, and the unit test `backend/tests/unit/test_e2e_page_typing.py` checks that `enter_text` calls only `fill(text)` when the delay is `None`.

The check of the page-object change with the default `None` is the UI cells of the `e2e-tests` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml). They run `pytest -m "ci and shard_<shard>" -k "ui-chromium"`:

- `E2E Tests (ui / general)`
- `E2E Tests (ui / env)`
- `E2E Tests (ui / compute)`
- `E2E Tests (ui / backup)`
- `E2E Tests (ui / env_backup)`
- `E2E Tests (ui / configuration)`
- `E2E Tests (ui / task_steps)`

The matrix excludes `ui / infrahub` and `ui / apply`, because every test of those shards is `api_only`. The shard names come from `_VALID_SHARDS` in [`backend/tests/e2e/conftest.py`](../../backend/tests/e2e/conftest.py).

## Host setup problems seen during the full run

The run of task T042 hit three problems on the host, outside the demo code ([full-run.log](full-run.log)). The guide now describes each one ([local demo guide](../../dev/guides/local-demo.md)):

- The host kernel had not loaded `br_netfilter`. Flannel in the vCluster crashed and Traefik never became ready, so `uv run invoke reset` failed. `sudo modprobe br_netfilter` fixed it.
- `uv run invoke start` skips `uv run invoke build`, and with it `helm dependency update`, when the Styrmin image already exists. In a worktree without `helm/styrmin/charts/`, the Helm install failed until `uv run invoke build` ran.
- The Chromium build for Playwright 1.64 was not installed, so both demos failed in step `setup`. `uv run playwright install chromium` fixed it.

Also, `uv run invoke record` builds the demo Semaphore image when it is missing before it runs the prerequisites check, so a first run can spend time on the image build (11 s on this host) even when the check then fails.

## No towncrier fragment, because only development tooling changes

This pull request adds no towncrier fragment. [`dev/guidelines/changelog.md`](../../dev/guidelines/changelog.md) asks for a fragment in a pull request that changes user-visible behaviour, and nothing changes for Styrmin users: the record command, the page objects and the demo files are development tooling. The grilling session of 2026-10-17 also decided on no towncrier fragment ([spec Clarifications](spec.md)). The guideline's `housekeeping` type covers development scripts and earlier pull requests used it for them (for example `+e2e-pdb-wrapper.housekeeping.md`), so the maintainer can still ask for one. The guideline records dependency-version bumps as `changed`; the Playwright upgrade needs no fragment because Playwright is in the root `dev` dependency group only, so a Styrmin installation does not include it.
