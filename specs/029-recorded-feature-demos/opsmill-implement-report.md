# Implementation Report: Recorded Demos of Four Styrmin Features

Status: INCOMPLETE. All four demos record in one run, and every task but one is done. Task T047 (play a video in Keynote, PowerPoint and Google Slides) needs a person with those applications.

- Feature: recorded demos of four Styrmin features for the beta presentation ([#518](https://github.com/opsmill/styrmin/issues/518))
- Spec directory: `specs/029-recorded-feature-demos`
- This report covers two sessions of `speckit-opsmill-implement`:
  - 2026-10-18, from base commit `11a4b58b`: phases 7, 8 and 9 for demos 2 and 3, while demos 1 and 4 waited for [#372](https://github.com/opsmill/styrmin/issues/372) and [#530](https://github.com/opsmill/styrmin/issues/530).
  - 2026-10-20, after the maintainer said both issues are fixed: drop commit `472fe403`, rebase on `develop` at `bb56eac9`, then phases 3 and 6, the run of all four demos, and the documentation, from base commit `17468791`.
- Head commit: the commit that adds this report, on top of `4358d79c`.
- Wall-clock time: not measured from start to end. The four-demo recording run took 48 min 28 s.

## Branch history changes on 2026-10-20

- Commit `472fe403` (the FR-016 alias check in `test_environment_clone_lifecycle`) was dropped. PR [#531](https://github.com/opsmill/styrmin/pull/531), which fixes #530, adds its own alias check to the same test on `develop`.
- The branch was rebased on `origin/develop` at `bb56eac9`. Two conflicts were resolved by keeping both sides:
  - `CLAUDE.md`: the `Active plan` line keeps this branch's plan; `develop` named the archived plan of the #372 fix.
  - `backend/tests/e2e/pages/drivers_list.py`: `develop` added a `driver_directory` field to `load_remote_version`; it goes through `enter_text` like the other two fields.
- The rebase rewrote the SHAs of the 2026-10-18 commits. For example, the page-object commit `b6c85a35` is now `fb749950`.
- The branch before these changes is kept in the local ref `backup/demo-beta-presentation-before-rebase-20261020`.
- `origin/fac/demo-beta-presentation-bhshh` is at `11a4b58b` (pushed on 2026-10-18) and still holds `472fe403`. Publishing the rebased branch needs `git push --force-with-lease`. Nothing was pushed.
- `git fetch` over SSH is refused on this host (`Permission denied (publickey)`); `develop` was fetched over HTTPS with the `gh` credentials.

## Chunk ledger

| Chunk | Tasks | Done / partial / blocked | Commits (after the rebase) |
|---|---|---|---|
| Phase 7: record the available demos with one command (2026-10-18) | T041, T042 | 2 / 0 / 0 | `6e5af7ee` |
| Phase 8: re-record one demo after a failed run (2026-10-18) | T043 | 1 / 0 / 0 | `0b66311e` |
| Phase 9: documentation, checks and pull request notes (2026-10-18) | T044, T045, T046, T048 | 4 / 0 / 0 | `8d060696` |
| Review fixes (2026-10-18) | none | not applicable | `65b1b32a` |
| Phase 3: demo 1, deploy and upgrade | T033, T034 | 2 / 0 / 0 | `888d4c99` |
| Phase 6: demo 4, environment clone | T039, T040 | 2 / 0 / 0 | `249fee29` |
| Run of all four demos and documentation update | T042, T044, T045, T046, T048 (again) | 5 / 0 / 0 | `b13b47d3`, `63b21856` |
| Review fixes (2026-10-20) | none | not applicable | `25a35791`, `4358d79c` |
| Phase 9: play a video in three presentation applications | T047 | 0 / 0 / 1 (not dispatched) | none |

Decisions and findings the agents reported:

- Phase 3 (demo 1):
  - The upgrade now runs the `infrahub` driver's upgrade action. The upgrade Job logged "Database version 75, Target 79", "Applied 4 migrations" and "Upgrade complete SUCCESS", and the Infrahub server started after it logged no `Expected database graph version` line.
  - `read_task_ids()` moved to the end of the first chapter, because in the first recording the timeline appeared and the page reloaded at once.
  - New page-object method `DeploymentDetailPage.show_timeline_entry(task_id)`, because the upgrade task was below the bottom of the page in the first recording.
  - Two product observations are written in [spike-notes.md](spike-notes.md): a 1.11.7 server starts before the action stops it and logs the graph-version warning twice, and three steps of the upgrade task show as "Superseded by Stop Components".
- Phase 6 (demo 4):
  - Counts 2, then 3 in the clone, then 2 in the source, readable on screen.
  - The clone's alias Services point only to namespaces of the clone.
  - `infrahub-enterprise`, loaded from its local directory, ran its setup actions to `Completed`. The #372 follow-ups had listed this driver as never run that way.
  - Two recorded waits were added after the clone ("The clone's Infrahub starts", "The clone's Semaphore starts"), because the logins cut from the video need both applications to answer.
- Run of all four demos, 2026-10-20T14:09:56Z to 14:58:24Z, exit code 0:
  - videos of 0:35, 0:45, 1:08 and 1:08, all `h264,1920,1080,yuv420p` at 30 frames per second;
  - memory peaked at 26,672 MiB used with 4,792 MiB available while ffmpeg encoded demo 4's video, on a host with 31,465 MiB and no swap;
  - afterwards only the `local` environment and no `styrmin-` namespace were left.
- Review fixes, 2026-10-20: demo 1 was recorded again (exit code 0, 0:35) to confirm the new version check. Its upgrade wait took 5 min 56 s, against 2 min 55 s in the earlier runs, and the "Stop Components" task showed Superseded instead of Succeeded. The cause was not examined.
- 2026-10-18 session: the host problems found then (the `br_netfilter` module, Helm chart dependencies skipped by `uv run invoke start`, the Playwright 1.64 Chromium) are described in [dev/guides/local-demo.md](../../dev/guides/local-demo.md). With Velero at 0, demo 3 failed in its backup chapter with exit code 1 and kept its environment; the next run deleted it before the setup.

## Tasks not completed

- T047 (play one video in Keynote, PowerPoint and Google Slides without conversion, SC-003): needs a person with a Mac or Windows machine and the three applications.

## Local-pass evidence

Unit tests added or modified on 2026-10-20 (the 2026-10-18 session added or modified none). Environment for every row: this host, Python 3.14.4, no demo stack needed.

| Test id | Type | Run command | Passed at | Verbatim pass line |
|---|---|---|---|---|
| `backend/tests/unit/demos/test_deploy_upgrade.py` (all tests, added in `888d4c99`, changed in `25a35791`) | unit | `uv run pytest backend/tests/unit/demos backend/tests/unit/test_e2e_page_typing.py backend/tests/unit/test_e2e_timeline_wait.py -v` | 2026-10-20T15:19:22Z | `PASSED` per test |
| `backend/tests/unit/demos/test_clone.py` (12 tests added in `249fee29`; `test_the_count_pattern_matches_the_line_the_playbook_prints` and `test_device_count_hides_the_infrahub_token_in_the_last_lines` added or changed in `25a35791`) | unit | same | 2026-10-20T15:19:22Z | `PASSED` per test |
| `backend/tests/unit/demos/test_catalog.py::test_the_registered_demos_follow_the_catalog_rules` (changed) | unit | same | 2026-10-20T15:19:22Z | `PASSED` |
| `backend/tests/unit/demos/test_main.py::test_an_unknown_slug_lists_the_four_slugs_and_exits_2` (changed; two tests of the removed "not available yet" path deleted) | unit | same | 2026-10-20T15:19:22Z | `PASSED` |
| `backend/tests/unit/test_e2e_timeline_wait.py::test_show_timeline_entry_names_a_task_the_open_tab_does_not_list` and `::test_show_timeline_entry_names_an_entry_that_does_not_expand` (added) | unit | same | 2026-10-20T15:19:22Z | `PASSED`; selection summary `62 passed, 1 warning in 0.37s` |
| The three unit suites above, together | unit | `uv run pytest backend/tests/unit/demos backend/tests/unit/test_e2e_page_typing.py backend/tests/unit/test_e2e_timeline_wait.py -q` | 2026-10-20T15:19:29Z | `174 passed, 1 warning in 0.58s` |
| Full backend suite after the review fixes | unit, functional | `uv run invoke test` | 2026-10-20T15:33:56Z | `5631 passed, 3 skipped, 36 warnings in 231.91s (0:03:51)` |
| `backend/tests/e2e/test_task_steps.py::test_helmrelease_failure_shows_fluxcd_reason[ui-chromium]` (not changed; run for the page-object changes) | e2e | `sleep infinity \| uv run pytest backend/tests/e2e/test_task_steps.py -m "ci and shard_task_steps" -k "ui-chromium" -v -s --pdb` | 2026-10-20T16:02:37Z | `PASSED`; `1 passed, 4 skipped, 5 deselected, 4 warnings in 434.65s (0:07:14)` (vCluster `pytest-b6282f18-4a55-4a2b-8107-0d5dd70e187c`, commit `28b1d20a`) |

The demo scenarios have no E2E test (approved exception). Their proof is the run of all four demos on a demo stack that `uv run invoke reset` had just created, in [full-run.log](full-run.log) ("T042, second run").

One UI E2E test ran locally after the page-object changes, at the maintainer's request: `test_task_steps.py` in the `ui-chromium` variant, which reads the timeline through `read_timeline` and enters text through `enter_text` with the default `None` ([e2e-evidence.md](e2e-evidence.md#the-timeline-test-passes-in-the-ui-variant-after-the-page-object-changes)). The UI cells of the `e2e-tests` job in CI check the other UI tests ([pr-notes.md](pr-notes.md)).

## Review findings

The 2026-10-18 review findings and their outcome are in the earlier version of this report (commit `17468791`). The review of `17468791..HEAD` on 2026-10-20 ran all six review aspects in three agents. It found no critical or high finding.

Fixed in `25a35791` and `4358d79c`:

| Severity | File | Finding |
|---|---|---|
| Medium | `backend/tests/e2e/demos/scenarios/deploy_upgrade.py` | The version check after the upgrade read `deployment.applicationVersion`, which Styrmin sets when it accepts the request, so it could not fail. It now reads the upgrade task's timeline entry. |
| Medium | `backend/tests/e2e/demos/__main__.py`, `tasks/demo.py` | The "not available yet" code path could no longer run, and the help text said "every available demo". |
| Medium | `specs/029-recorded-feature-demos/spike-notes.md`, `e2e-evidence.md` | Wrong rebase base commit, an outdated critique citation, a tense contradiction, and no note that `472fe403` had been pushed. |
| Medium | `dev/knowledge/backend/e2e-testing.md` | Did not say that `show_timeline_entry` needs the Timeline tab already open. |
| Medium | `spike-notes.md`, `deploy_upgrade.py` | "step" used for a recorded chapter next to the glossary term Step. |
| Low | `backend/tests/e2e/pages/deployment_detail.py` | `show_timeline_entry` re-raised `from None`, and did not wrap the expand assertion. |
| Low | `backend/tests/e2e/demos/scenarios/clone.py` | The error text with the last log lines did not hide the Infrahub token; two docstrings were inaccurate. |
| Low | `backend/tests/unit/demos/test_clone.py`, `test_deploy_upgrade.py` | The count-pattern test did not use the pattern; only the FAILED status was tested. |

Not fixed:

| Severity | File | Finding |
|---|---|---|
| Medium | `backend/tests/e2e/demos/scenarios/clone.py` | The setup and the `Lab` type repeat `backup_restore.py` field for field, and `SEMAPHORE_VERSION` is copied in three scenarios. Suggested: a `network_lab.py` module with `deploy_network_lab(context, environment_name)`. Deferred because it changes demos 3 and 4, which would need to be recorded again. |
| Low | `clone.py`, `deploy_upgrade.py` | `clone.Lab.infrahub_url` is never read; two different types are named `Lab`. |
| Low | `clone.py` | Repeats the "last 10 log lines" code of `pages/semaphore.py`. |
| Low | `spike-notes.md` | The demo 2 and demo 3 sections still use "step" for a recorded chapter. |

## Autonomous decisions

- On 2026-10-18, phases 3 and 6 were not dispatched because the maintainer had decided that demos 1 and 4 wait for #372 and #530. On 2026-10-20 the maintainer said both are fixed, and both phases were done.
- `472fe403` was dropped rather than kept, as the maintainer asked; PR #531's alias check on `develop` covers the same assertion. On 2026-10-20 the orchestrator stated in [e2e-evidence.md](e2e-evidence.md) that PR #531's runs meet the dependency of Phase 6 on T006 and T007.
- T042, T044, T045, T046 and T048 were done again after demos 1 and 4 landed, so the run of all four demos that the approved exception asks for exists and the documents describe the current state.
- The version check of demo 1 was changed after the run of all four demos; demo 1 was recorded again alone to confirm it ([full-run.log](full-run.log)).
- The shared setup helper for demos 3 and 4 was deferred.
- T047 was not dispatched, because no agent can open Keynote, PowerPoint or Google Slides.
- `full-run.log` is committed with `git add -f`, because it matches `*.log` in `.gitignore`.

## Suggested next steps

1. Push the rebased branch with `--force-with-lease` (the remote branch holds `472fe403`) and open the pull request from [pr-notes.md](pr-notes.md). The maintainer asked for both on 2026-10-20, after the local run of `test_task_steps.py`.
2. Play one video in Keynote, PowerPoint and Google Slides (T047) and record the result in `full-run.log`.
3. Confirm that demos 3 and 4 may show the `infrahub-enterprise` driver (question in [pr-notes.md](pr-notes.md)).
4. Consider the deferred shared setup helper for demos 3 and 4, and look into the slower upgrade (5 min 56 s) seen in the last demo 1 run.
