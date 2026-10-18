# Implementation Report: Recorded Demos of Four Styrmin Features

Status: INCOMPLETE. Demos 1 and 4 wait for open issues, and task T047 needs a person with Keynote, PowerPoint and Google Slides.

- Feature: recorded demos of four Styrmin features for the beta presentation ([#518](https://github.com/opsmill/styrmin/issues/518))
- Spec directory: `specs/029-recorded-feature-demos`
- Base commit: `11a4b58b` (tasks T001 to T032 and T035 to T038 were already done before this run)
- Head commit: the commit that adds this report, on top of `0e711e19`
- Wall-clock time: about 1 h 35 min, the sum of the run times of the three implementation agents and the review. The time from start to end was not measured.

## Chunk ledger

| Chunk | Tasks | Done / partial / blocked | Commit |
|---|---|---|---|
| Phase 3: demo 1, deploy and upgrade | T033, T034 | 0 / 0 / 2 (not dispatched) | none |
| Phase 6: demo 4, environment clone | T039, T040 | 0 / 0 / 2 (not dispatched) | none |
| Phase 7: record all demos with one command | T041, T042 | 2 / 0 / 0 | `4c31ee69` |
| Phase 8: re-record one demo after a failed run | T043 | 1 / 0 / 0 | `150e84a9` |
| Phase 9: documentation, checks and pull request notes | T044, T045, T046, T048 | 4 / 0 / 0 | `fd96cf9b` |
| Phase 9: play a video in three presentation applications | T047 | 0 / 0 / 1 (not dispatched) | none |
| Review fixes | none | not applicable | `0e711e19` |

Decisions and surprises the agents reported:

- Phase 7, T041: with ffmpeg missing, `uv run invoke record` exited with code 2 and printed the contract's ffmpeg message. With the demo stack stopped, it exited with code 2 and printed the demo stack message.
- Phase 7, T042: on a fresh demo stack, `uv run invoke record` exited with code 0 and recorded two videos:
  - `2-component-overrides.mp4`, 0:45;
  - `3-backup-restore.mp4`, 1:03.

  Both are `h264,1920,1080,yuv420p` at 30 frames per second, with no audio and with `faststart`. Only the `local` environment remained.
- Phase 7: the run hit three host problems outside the demo code, and the agent fixed each one on the host:
  - the kernel had not loaded `br_netfilter`, so Flannel crashed and Traefik never became ready (`sudo modprobe br_netfilter`);
  - `uv run invoke start` skips `uv run invoke build`, and with it `helm dependency update`, when the Styrmin image exists, so a worktree without `helm/styrmin/charts/` failed until `uv run invoke build` ran;
  - the Chromium build for Playwright 1.64 was not installed (`uv run playwright install chromium`).
- Phase 7: `uv run invoke record` builds a missing demo Semaphore image before it runs the prerequisites check.
- Phase 7: `full-run.log` matches `*.log` in `.gitignore`, so it was added with `git add -f`.
- Phase 8, T043: with Velero scaled to 0, demo 3 failed in step "Back up the whole environment" with `ScenarioTimeout` after 600 s. The command exited with code 1, kept `network-lab-backup`, and wrote no new video. With Velero back at 1, the next run deleted `network-lab-backup` before the setup, exited with code 0 and rewrote only `3-backup-restore.mp4` (1:09). When Velero restarted, one of the two backups left by the failed run ended `PartiallyFailed`; the cause was not examined.
- Phase 9: no towncrier fragment, because [spec.md](spec.md) Clarifications decided on none and only development tooling changes.
- Phase 9: no local E2E test ran after the page-object commit `b6c85a35`. The UI cells of the `e2e-tests` job in CI are the check of that change ([pr-notes.md](pr-notes.md)).
- Phase 9: `develop` has 77 commits that the branch does not have.

## Tasks not completed

- T033 and T034 (demo 1, deploy and upgrade): wait for [#372](https://github.com/opsmill/styrmin/issues/372), which is open. A driver loaded from a local directory does not register its upgrade action, so the upgrade does not run `infrahub upgrade`. The maintainer decided on 2026-10-18 that demo 1 waits for the fix ([spike-notes.md](spike-notes.md)).
- T039 and T040 (demo 4, environment clone): wait for [#530](https://github.com/opsmill/styrmin/issues/530), which is open. A clone keeps the source's service aliases. The maintainer decided on 2026-10-18 that demo 4 waits for the fix ([e2e-evidence.md](e2e-evidence.md)).
- T047 (play one video in Keynote, PowerPoint and Google Slides): needs a person with a Mac or Windows machine and the three applications.

## Local-pass evidence

n/a: this run added or modified no tests. The three chunks changed only documentation, logs, `tasks.md` and the pull request notes, which `git diff --stat 11a4b58b..0e711e19` shows. The checks that ran:

- `uv run invoke test`, ended 2026-10-18T23:44:51Z, exit code 0: `5081 passed, 3 skipped, 36 warnings in 213.39s (0:03:33)`.
- `uv run invoke format lint`, exit code 0 at 2026-10-18T23:48:30Z, and again after the review fixes.

## Review findings

Two reviews ran on the diff from `11a4b58b`: one checked the documents against the project rules and the writing rules, and one checked each claim against the code and the logs. The tests, errors, types and simplify reviews did not run, because no code or test changed.

Fixed in `0e711e19`:

| Severity | File | Finding |
|---|---|---|
| High | `specs/029-recorded-feature-demos/pr-notes.md` | Called the run of demos 2 and 3 the full proof of the E2E exception, which asked for all four demos. Now asks the maintainer to confirm. |
| Medium | `dev/guides/local-demo.md` | Said every wait is sped up; only waits longer than 6 s are. |
| Medium | `dev/guides/local-demo.md` | Said the command deletes namespaces through the kube context; it deletes environments through the Styrmin API and only reads namespaces. |
| Medium | `dev/knowledge/backend/e2e-testing.md` | Said every Styrmin action goes through the page objects; the setup uses the SDK. |
| Medium | `specs/029-recorded-feature-demos/pr-notes.md` | Left out the `CLAUDE.md` change and the reason the Playwright upgrade needs no fragment. |
| Low | `specs/029-recorded-feature-demos/pr-notes.md` | Heading "Changelog fragment" did not say what is below it. |
| Low | `specs/029-recorded-feature-demos/tasks.md` | T042 was ticked without saying that only two demos were recorded. |

Not fixed:

| Severity | File | Finding |
|---|---|---|
| Medium | `dev/guides/local-demo.md` | The `br_netfilter` problem also affects the public quickstart (`docs/docs/installation/quickstart.md`), which does not mention it. |
| Medium | `dev/guides/local-demo.md`, `pr-notes.md` | "today" and values copied from the versions file go out of date; use a date or point to the file. |
| Medium | `dev/guides/local-demo.md`, `e2e-testing.md`, `pr-notes.md` | Some sources are not linked, and "five runs" cites only spike-notes.md, which counts three. |
| Medium | `dev/guides/local-demo.md`, `pr-notes.md` | Lists of three or more items inside sentences, and terms such as "spike notes", "grilling session" and "run loop". |
| Medium | `specs/029-recorded-feature-demos/pr-notes.md` | Headings "Evidence" and "Governance gates crossed" do not say what is below them. |
| Low | `dev/guides/local-demo.md` | "step" can be confused with the glossary term Step; `ffprobe` is not listed as a prerequisite. |
| Low | `specs/029-recorded-feature-demos/full-run.log` | Contains the host kernel version, the user name and a worktree path. Renaming it to `full-run.md` would remove the need for `git add -f`. |
| Low | `dev/knowledge/backend/e2e-testing.md` | The Key Files link to `backend/tests/e2e/demos/` does not resolve from this file; nearby rows use the same pattern. |
| Low | `specs/029-recorded-feature-demos/pr-notes.md` | Playwright was a transitive dependency locked at 1.58.0, not a direct one; FR-018 does not mention CI workflows; the quoted test results are in no log file. |

## Autonomous decisions

- Phases 3 and 6 were not dispatched, because the maintainer's decisions of 2026-10-18 make demos 1 and 4 wait for #372 and #530, and both issues are still open.
- T042 ran plain `uv run invoke record`, which records every registered demo (2 and 3), instead of the task's fallback of three `--demo` runs, because demo 1 also waits.
- T047 was not dispatched, because no agent can open Keynote, PowerPoint or Google Slides.
- The pull request notes were written to `specs/029-recorded-feature-demos/pr-notes.md`; the task does not name a file.
- The orchestrator fixed the high finding and the medium factual errors itself, and left the writing-rule findings for a later pass.
- The host problems of Phase 7 were fixed on the host and documented in the guide; `uv run invoke start` was not changed.

## Suggested next steps

1. Decide whether the run of demos 2 and 3 is enough for the approved E2E exception (pr-notes.md, "Questions for the maintainer").
2. Play one video in Keynote, PowerPoint and Google Slides (T047) and record the result in `full-run.log`.
3. Move commit `472fe403` off the branch and rebase on `develop` before pushing.
4. Address the review findings that are not fixed, in particular the `br_netfilter` item in the public quickstart.
5. When #372 and #530 are fixed, rerun `speckit-opsmill-implement` for T033, T034, T039 and T040.
