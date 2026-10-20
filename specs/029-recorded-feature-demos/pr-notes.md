# Pull Request Notes: Recorded Demos of Four Styrmin Features

## Summary

For the beta presentation ([#518](https://github.com/opsmill/styrmin/issues/518)), a presenter needs one video for each of four Styrmin features: deploy and upgrade, component overrides, environment backup and restore, and environment clone. This branch adds `uv run invoke record`, which records the demos on the local demo stack and writes one MP4 video for each ([spec](spec.md), [plan](plan.md)).

All four demos can be recorded: `deploy-upgrade` (demo 1), `component-overrides` (demo 2), `backup-restore` (demo 3) and `clone` (demo 4). One run of all four demos, on a demo stack that `uv run invoke reset` had just created, passed on 2026-10-20 ([full-run.log](full-run.log)). Not done or not decided yet:

- The maintainer has not yet confirmed that demos 3 and 4 may show the `infrahub-enterprise` driver (see [Questions for the maintainer](#questions-for-the-maintainer)).
- Nobody has played a video in Keynote, PowerPoint and Google Slides yet (task T047).

Suggested title: `test(e2e): record demos of Styrmin features for the beta presentation (#518)`.

## Changes in this pull request

- Playwright 1.58.0 to 1.64.0 in the root `dev` dependency group (`pyproject.toml`, `uv.lock`), for its Screencast API.
- E2E page objects (`backend/tests/e2e/pages/`) and `UiScenarioDriver`:
  - every page-object class and `UiScenarioDriver` take `keystroke_delay_ms: int | None = None`;
  - every `.fill(...)` call goes through `enter_text` in `pages/_dom.py`, which calls `fill` when the delay is `None` and types one key at a time otherwise;
  - `DeploymentDetailPage` gains `open_timeline`, `read_task_ids`, `wait_for_new_task`, `show_component_overrides` and `show_timeline_entry`.

  The E2E suite keeps `None`, because `backend/tests/e2e/conftest.py` does not pass the argument.
- The demo package `backend/tests/e2e/demos/`:
  - the run loop and summary, the prerequisites check, the catalog, the recorder, the video planning and the ffmpeg encoding;
  - SDK helpers for the demo stack, and the Infrahub and Semaphore setup and page objects;
  - the demo Semaphore image (`semaphore/Dockerfile`) and the Infrahub versions file;
  - the scenarios of the four demos: `scenarios/deploy_upgrade.py`, `scenarios/component_overrides.py`, `scenarios/backup_restore.py` and `scenarios/clone.py`.
- Unit tests in `backend/tests/unit/demos/` (one test module for each scenario, including `test_deploy_upgrade.py` and `test_clone.py`), `backend/tests/unit/test_e2e_page_typing.py` and `backend/tests/unit/test_e2e_timeline_wait.py`.
- The `record` task in `tasks/demo.py`, registered in `tasks/__init__.py`, and `demo-videos/` in `.gitignore`.
- The line `Active plan: [specs/029-recorded-feature-demos/plan.md](specs/029-recorded-feature-demos/plan.md)` in `CLAUDE.md`, which the speckit plan step added. On `develop`, the line names the archived plan `specs/archive/029-local-driver-actions/plan.md`, another spec with the number 029.
- Documentation: "Recording the demos" and two troubleshooting items in [`dev/guides/local-demo.md`](../../dev/guides/local-demo.md), and "Page objects shared with the recorded demos" in [`dev/knowledge/backend/e2e-testing.md`](../../dev/knowledge/backend/e2e-testing.md).

No product code, E2E test, GraphQL schema, SDK, `styrminctl`, frontend, database schema, application driver or CI workflow changes (FR-018). The only files the branch changes under `backend/tests/e2e/` outside `demos/` are the page objects and `drivers/ui_driver.py`.

## Rebase on develop on 2026-10-20

- Commit `472fe403` ("test(e2e): check that a clone's service aliases stay in the clone") was dropped from the branch before the rebase. It added the FR-016 alias check (task T005) to `test_environment_clone_lifecycle`, and [PR #531](https://github.com/opsmill/styrmin/pull/531) adds its own alias check to the same test ([E2E evidence](e2e-evidence.md#the-defect-is-fixed-by-531-which-carries-its-own-alias-check)).
- The branch was then rebased on `origin/develop` at `bb56eac9`, which holds the fixes to [#372](https://github.com/opsmill/styrmin/issues/372) ([PR #535](https://github.com/opsmill/styrmin/pull/535)) and [#530](https://github.com/opsmill/styrmin/issues/530) (PR #531). Two conflicts were resolved:
  - `CLAUDE.md` keeps this branch's `Active plan` line;
  - `backend/tests/e2e/pages/drivers_list.py` keeps the field `driver_directory` that `develop` added to the Load Driver drawer, and enters it with `enter_text`, as the other fields of the drawer.
- The ref `backup/demo-beta-presentation-before-rebase-20261020` holds the branch as it was before the rebase.
- On 2026-10-18, `fac/demo-beta-presentation-bhshh` had been pushed to GitHub at `11a4b58b`, with `472fe403` and the history from before the rebase. On 2026-10-20, after the local run of `test_task_steps.py` in the `ui-chromium` variant, the rebased branch replaced it with `git push --force-with-lease`, pinned to `11a4b58b`.

## Evidence

- [e2e-evidence.md](e2e-evidence.md): the two failing runs of the FR-016 alias check (T006, T007), the passing UI smoke run with Playwright 1.64 (T011), the decision on the defect (T008), and why the check is no longer part of this branch.
- [spike-notes.md](spike-notes.md): the checks of the deployments, the screencast and the Semaphore inventory on the demo stack, and the first recording of each demo with the changes made after watching it.
- [full-run.log](full-run.log): the prerequisites check (T041), the run of all four demos on a fresh demo stack (T042), the earlier run of demos 2 and 3 that it replaces, and a failed and re-recorded run of demo 3 (T043).

Summary of the run of all four demos, from 2026-10-20T14:09:56Z to 14:58:24Z (48 min 28 s), exit code 0, quoted from [full-run.log](full-run.log):

```text
Demo                 Result    Video                                  Length
deploy-upgrade       recorded  demo-videos/1-deploy-upgrade.mp4       0:35
component-overrides  recorded  demo-videos/2-component-overrides.mp4  0:45
backup-restore       recorded  demo-videos/3-backup-restore.mp4       1:08
clone                recorded  demo-videos/4-clone.mp4                1:08
```

- The run started on a demo stack that `uv run invoke reset` created from 14:07:11Z to 14:09:35Z, after `uv run invoke build` built the Styrmin image from commit `249fee29`.
- The four videos are H.264, `yuv420p`, 1920×1080, 30 frames per second, with no audio stream and with `faststart`.
- After the run, only the `local` environment remained, with no deployment, and no `styrmin-<deployment id>` namespace was left.
- During demo 4, the host's memory in use reached at most 26,672 MiB of 31,465 MiB, with at least 4,792 MiB available and no swap used. Other processes ran on the host, so how much the two environments of demo 4 used is not known.
- The re-run of demo 3 after a failed run, on 2026-10-18 before the rebase, took from 23:17:07Z to 23:37:47Z and wrote a video of 1:09 (task T043).

Checks run for the pull request on 2026-10-20, after the rebase and after the run of the four demos:

- `uv run invoke test`: `5625 passed, 3 skipped, 36 warnings in 233.21s (0:03:53)`, ended at 2026-10-20T15:03:22Z, exit code 0. After the pytest summary, the Prefect log handler printed `--- Logging error ---` with `ValueError: I/O operation on closed file.` for the message `Stopping temporary server on http://127.0.0.1:8245`, as in the run of 2026-10-18. The exit code stayed 0. Whether this happens on `develop` too is not known.
- `uv run invoke format lint`: exit code 0 at 2026-10-20T15:03:44Z. ruff format left 1027 files unchanged, ruff and ty printed `All checks passed!`, rumdl found no issue in 79 files, all 282 `.graphql` files passed validation, and the generated types were up to date. yamllint printed two warnings, for `driver/examples/infrahub-mcp/driver.styrmin.yml` and `.specify/workflows/speckit/workflow.yml`, two files that this branch does not change.

## Approved exception to Constitution §V

The demo scripts have no E2E test. The grilling session of 2026-10-17 approved this exception ([spec Clarifications](spec.md)). The agreed proof is one run of all four demos on a demo stack that `uv run invoke start` just created, with the command output attached to the pull request. That run passed on 2026-10-20: `uv run invoke reset`, then `uv run invoke record`, with exit code 0, four `recorded` lines, and only the `local` environment left afterwards. The summary is quoted under [Evidence](#evidence), and the full output is in [full-run.log](full-run.log). An earlier run, on 2026-10-18, covered demos 2 and 3 only, because demos 1 and 4 were not registered then. The log keeps that run, marked as superseded.

## Governance gates crossed

The constitution's gate "New dependencies" applies to three items, all approved in the grilling session of 2026-10-17 ([spec Clarifications](spec.md)):

- Playwright 1.58.0 to 1.64.0. This also changes the Chromium build that the UI E2E tests run in, locally and in CI. CI installs the browser with `uv run playwright install chromium`, which follows the lock file, so no workflow change is needed.
- `ffmpeg` on the developer's PATH, any build with libx264. Only `uv run invoke record` needs it. CI does not run the demos.
- A Semaphore image built locally, `styrmin-demo/semaphore:v2.16.47`, from `semaphoreui/semaphore:v2.16.47` with the `opsmill.infrahub` Ansible collection 1.8.3, `infrahub-sdk`, and the demo playbook and inventory file. It is never pushed to a registry (FR-015).

No other gate is crossed: no database schema, GraphQL schema, CI workflow, or authentication change.

## Questions for the maintainer

### Demos 3 and 4 show the `infrahub-enterprise` driver

An environment backup of Infrahub runs `neo4j-admin database backup`, which needs Neo4j Enterprise. The `infrahub` driver deploys the community chart, and its backup E2E test is skipped with the reason "backup/restore not supported with community". So demos 3 and 4 deploy the `infrahub-enterprise` driver, whose chart sets `neo4j.edition: enterprise` and `acceptLicenseAgreement: "yes"` ([research R-007](research.md#r-007-environment-backups-need-the-infrahub-enterprise-driver)). Demos 1 and 2 deploy `infrahub`. The beta audience may ask why two Infrahub editions appear ([critique P2](critiques/critique-20261017.md)).

Since the fix to #372, the agent runs the setup actions of `infrahub-enterprise`, which the demo stack loads from a local directory. In the recording of demo 4 alone, both setup actions ended in state `Completed` ([spike notes](spike-notes.md#the-infrahub-enterprise-drivers-setup-actions-ran)). In the run of the four demos, demos 3 and 4 each ran the pre-hook and the post-hook of `infrahub-enterprise`, and each of these flow runs ended `Completed` ([full-run.log](full-run.log)).

Question: is it acceptable that demos 3 and 4 show the Enterprise edition?

## The FR-016 alias check is in develop through PR #531

The FR-016 check of this branch failed on both variants of `test_environment_clone_lifecycle`, as research [R-013](research.md#r-013-a-clones-alias-services-point-to-the-source) expected: the counterpart deployment's namespace kept an alias Service whose `spec.externalName` points to a namespace of the source environment ([e2e-evidence.md](e2e-evidence.md)). The defect was filed as [#530](https://github.com/opsmill/styrmin/issues/530) and fixed by [PR #531](https://github.com/opsmill/styrmin/pull/531), "fix(clone): a clone writes its own service aliases (#530)", merged into `develop` on 2026-10-19.

PR #531 adds its own alias check to `test_environment_clone_lifecycle`, so this branch no longer carries one. The local runs of that check are in [spec 030 E2E evidence](../030-clone-service-aliases/e2e-evidence.md). [e2e-evidence.md](e2e-evidence.md) keeps the failing runs of this branch's check and describes the check that `develop` now holds. Demo 4 shows the case that the check cannot show alone: the clone's Semaphore reaches the clone's Infrahub through the alias `infrahub` ([spike notes](spike-notes.md#the-clones-alias-services-point-to-the-clone-fr-016-positive-case)).

## Work this pull request does not finish

Task T047: play one video in Keynote, PowerPoint and Google Slides (uploaded to Google Drive) without conversion (SC-003). It needs a person with a Mac or Windows machine and access to the three applications. The result goes into [full-run.log](full-run.log).

## Check of the page-object change in CI

The local UI smoke run of task T011 ended at 2026-10-18T10:07:20Z, before the page-object change (commit `b6c85a35` before the rebase, `fb749950` after it). It checks the Playwright upgrade, not the page-object change. After the rebase, on 2026-10-20, `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[ui-chromium]` passed locally (`1 passed, 4 skipped, 5 deselected` in 7 min 14 s). It reads the timeline through `read_timeline` and runs the page objects with the default `None` ([e2e-evidence.md](e2e-evidence.md#the-timeline-test-passes-in-the-ui-variant-after-the-page-object-changes)). No other UI E2E test ran locally after the page-object change. The demos ran the page objects with a delay of 45 ms, and the unit test `backend/tests/unit/test_e2e_page_typing.py` checks that `enter_text` calls only `fill(text)` when the delay is `None`.

The check of the page-object change in the other UI tests is the UI cells of the `e2e-tests` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml). They run `pytest -m "ci and shard_<shard>" -k "ui-chromium"`. Counted after the rebase, on 2026-10-20, there are seven:

- `E2E Tests (ui / general)`
- `E2E Tests (ui / env)`
- `E2E Tests (ui / compute)`
- `E2E Tests (ui / backup)`
- `E2E Tests (ui / env_backup)`
- `E2E Tests (ui / configuration)`
- `E2E Tests (ui / task_steps)`

The matrix lists nine shards and excludes `ui / infrahub` and `ui / apply`, because every test of those shards is `api_only`. The nine shard names match `_VALID_SHARDS` in [`backend/tests/e2e/conftest.py`](../../backend/tests/e2e/conftest.py).

## Host setup problems seen during the runs

The first run of task T042, on 2026-10-18, hit three problems on the host, outside the demo code ([full-run.log](full-run.log)). The guide describes each one ([local demo guide](../../dev/guides/local-demo.md)):

- The host kernel had not loaded `br_netfilter`. Flannel in the vCluster crashed and Traefik never became ready, so `uv run invoke reset` failed. `sudo modprobe br_netfilter` fixed it.
- `uv run invoke start` skips `uv run invoke build`, and with it `helm dependency update`, when the Styrmin image already exists. In a worktree without `helm/styrmin/charts/`, the Helm install failed until `uv run invoke build` ran.
- The Chromium build for Playwright 1.64 was not installed, so both demos failed in step `setup`. `uv run playwright install chromium` fixed it.

Before the run of the four demos on 2026-10-20, the module was loaded, the chart dependencies were present and the Chromium build was installed, so none of these problems occurred. `uv run invoke build` ran before `uv run invoke reset`, because `uv run invoke start` reuses any existing image tagged `registry.opsmill.io/opsmill/styrmin:latest`, and other worktrees on this host build Styrmin images too.

Also, `uv run invoke record` builds the demo Semaphore image when it is missing before it runs the prerequisites check, so a first run can spend time on the image build (11 s on this host) even when the check then fails.

## No towncrier fragment, because only development tooling changes

This pull request adds no towncrier fragment. [`dev/guidelines/changelog.md`](../../dev/guidelines/changelog.md) asks for a fragment in a pull request that changes user-visible behaviour, and nothing changes for Styrmin users: the record command, the page objects and the demo files are development tooling. The grilling session of 2026-10-17 also decided on no towncrier fragment ([spec Clarifications](spec.md)). The guideline's `housekeeping` type covers development scripts and earlier pull requests used it for them (for example `+e2e-pdb-wrapper.housekeeping.md`), so the maintainer can still ask for one. The guideline records dependency-version bumps as `changed`; the Playwright upgrade needs no fragment because Playwright is in the root `dev` dependency group only, so a Styrmin installation does not include it.
