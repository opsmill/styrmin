# Quickstart: Verify the Recorded Demos

How to check that the feature works. The command's options, output and exit codes are in [contracts/record-command.md](contracts/record-command.md).

## Prerequisites

- The tools of the [local demo guide](../../dev/guides/local-demo.md): `docker`, `vcluster`, `helm`, `kubectl`.
- `ffmpeg` on the PATH, any build with libx264. `brew install ffmpeg` or `apt install ffmpeg` is enough; `drawtext` is not needed.
- `uv sync` run after the Playwright upgrade, then `uv run playwright install chromium`.
- Enough memory for two environments with Infrahub and Semaphore at the same time, which demo 4 needs. How much is not measured (spec Assumptions).

## 1. Unit tests of the post-processor

```bash
uv run pytest backend/tests/unit/demos -v
```

Expected: every test passes. They cover the segments, the speed-up factor, the labels, the cuts and the ffmpeg arguments ([research.md](research.md), R-005).

## 2. The clone alias check (FR-016)

Run each variant in its own session ([E2E testing](../../dev/knowledge/backend/e2e-testing.md)):

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[api-chromium]" -v -s --pdb 2>&1 | tee /tmp/clone-api.log
sleep infinity | uv run pytest "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle[ui-chromium]" -v -s --pdb 2>&1 | tee /tmp/clone-ui.log
```

Expected: `PASSED` for both. If the alias check fails, the counterpart's namespace holds an alias that points to a source namespace (research R-013): stop and report it as described in the plan.

## 3. Record all four demos on a fresh demo stack

```bash
uv run invoke reset          # destroy and start a fresh demo stack
uv run invoke record
```

Expected:

- The command exits 0 and prints a summary with four `recorded` lines.
- `demo-videos/` contains `1-deploy-upgrade.mp4`, `2-component-overrides.mp4`, `3-backup-restore.mp4` and `4-clone.mp4`, each 3:00 or less.
- `ffprobe -v error -show_entries stream=codec_name,width,height,pix_fmt -of csv=p=0 demo-videos/1-deploy-upgrade.mp4` prints `h264,1920,1080,yuv420p`.
- In the Styrmin UI, only the `local` environment remains. `kubectl get ns | grep styrmin-` lists no namespace of a demo deployment.

Attach the command's output to the PR (the approved E2E exception).

## 4. Watch the videos

For each video, check:

- each step starts with a title;
- each click and each text field shows a cursor and a highlight, and text appears one key at a time;
- each wait for the cluster is sped up, with a label that gives its real duration and the factor;
- demo 3 shows the device and the template back after the restore;
- demo 4 shows 2 devices in the source, 3 in the clone, and 2 in the source again.

Open one video in Keynote, PowerPoint and Google Slides (uploaded to Google Drive) and play it without conversion (SC-003). Record the result in the PR.

## 5. Re-record one demo after a failure (User Story 6)

1. Make demo 3 fail once, for example by stopping the vCluster's Velero deployment during its backup (`kubectl -n styrmin scale deploy/velero --replicas=0`; Velero is a subchart of the Styrmin chart), then run `uv run invoke record --demo backup-restore`.
   - Expected: exit code 1; the summary names the failing step and the error and lists `network-lab-backup` as kept; no new `3-backup-restore.mp4` was written; the environment still exists.
2. Restore Velero (`--replicas=1`) and run `uv run invoke record --demo backup-restore` again.
   - Expected: exit code 0; the command deleted the leftover `network-lab-backup` before its setup, recorded demo 3 and wrote only `3-backup-restore.mp4`.

## 6. Prerequisites check (FR-012)

- With `ffmpeg` removed from the PATH (`PATH=/usr/bin:/bin uv run invoke record` on a system where ffmpeg is elsewhere): exit code 2 and the ffmpeg message, before any setup.
- With the demo stack paused (`uv run invoke stop`): exit code 2 and the demo stack message.

## 7. The E2E suite still fills fields in one step

The UI E2E shards in CI run with the default `keystroke_delay_ms=None`. Locally, `test_ui_smoke.py` in the `ui-chromium` variant is enough to check the page objects after the change.
