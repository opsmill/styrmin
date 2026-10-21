# Contract: The Demo Record Command

The feature's only interface is a developer command. It changes no GraphQL, SDK or `styrminctl` surface (FR-018). This contract describes the command after the review of [PR #540](https://github.com/opsmill/styrmin/pull/540) on 2026-10-21.

## Invocation

```bash
uv run invoke record                                     # all four demos, in PRD order
uv run invoke record --demo backup-restore               # one demo
uv run invoke record --demo clone --demo deploy-upgrade  # several demos, in PRD order
uv run invoke record --demo clone --output-dir /tmp/v    # another output directory
uv run invoke record --build-image                       # build the demo Semaphore image without Docker's cache
uv run invoke record --delete-environments               # only delete the demos' environments
uv run invoke record --encode-again /tmp/styrmin-demo-clone-abc123  # only encode a kept recording
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--demo` | all four | A slug: `deploy-upgrade`, `component-overrides`, `backup-restore` or `clone` (FR-001). Repeat the option to select several demos (FR-022). An unknown slug stops the command before any check, with exit code 2 and a message that lists the four slugs. |
| `--output-dir` | `demo-videos/` at the repository root, ignored by git | Where the MP4 files and their chapter files are written (FR-007, FR-021). |
| `--build-image` | off | Build the demo Semaphore image without Docker's build cache. The command builds the image before each run that needs it anyway, from Docker's cache when nothing changed, so a changed Dockerfile or playbook always reaches the image. |
| `--delete-environments` | off | Only delete the environments of the selected demos, then exit (FR-022). |
| `--encode-again DIR` | none | Only encode the raw recording that a failed encoding kept in `DIR`, write the video to the output directory and delete `DIR` (FR-024). Needs no demo stack. |

The task lives in [`tasks/demo.py`](../../../tasks/demo.py) next to `build`, `start`, `stop`, `destroy` and `reset`. It runs the recorder as `python -m tests.e2e.demos` from `backend/`, the same way `uv run invoke test` runs pytest from `backend/`, so the recorder imports the E2E page objects (research R-010). The recorder's own option for `--build-image` is `--rebuild-image`.

## Prerequisites check (FR-012)

Run before any setup and before the image build, in this order. The first failure stops the command with exit code 2 and one message that names what is missing:

| Check | Message on failure |
| --- | --- |
| `ffmpeg` and `ffprobe` are on the PATH | `ffmpeg or ffprobe is not on the PATH. Install ffmpeg (for example 'brew install ffmpeg' or 'apt install ffmpeg') and run the command again.` |
| The Chromium build of the installed Playwright exists | `The Chromium build of the installed Playwright is missing (<path>). Run 'uv run playwright install chromium' and run the command again.` |
| `docker` is on the PATH, when a selected demo deploys the demo Semaphore image | `docker is not on the PATH. The command builds the demo Semaphore image with it.` |
| The kube context `vcluster-docker_styrmin` reaches the demo stack | `The kube context 'vcluster-docker_styrmin' does not reach the demo stack (<error>). Run 'uv run invoke start', which writes the context with 'vcluster connect'.` |
| The demo stack's GraphQL endpoint at `http://styrmin.local.styrmin.io:8080/graphql` answers | `The demo stack does not respond at http://styrmin.local.styrmin.io:8080. Run 'uv run invoke start' first.` |
| The demo stack accepts the admin login from `dev/local/demo-values.yaml` | `The demo stack at <url> rejected the login of '<username>'. …` (names the values file, and `uv run invoke reset` after a change to it) |
| The `infrahub` and `semaphore` drivers are loaded, the `local` cluster exists and has a backup storage location | `The demo stack is missing <item>. Run 'uv run invoke start' again.` |
| The Infrahub versions file is valid | `<path>: <problem>` |

A failed build of the demo Semaphore image also stops the command with exit code 2, with the last 20 lines of the build output.

## Environments the command may delete (FR-009)

The command records the id of each environment that it creates, or that the developer confirms, in `$XDG_STATE_HOME/styrmin/demo-environments.json` (by default `~/.local/state/styrmin/demo-environments.json`), for each demo stack URL. Before the first demo, it lists the existing environments with a selected demo's names. When one is not in the file, it lists them and asks `Delete them? [y/N]`. Without a yes, or without a terminal, it stops with exit code 2 before any change. A demo also refuses to delete an environment that is not in the file.

## Output

For each demo, the command prints how long the demo usually takes, each sub-step of the setup, each step title as it starts, each wait when it starts, every minute while it lasts and when it ends with its real duration, and the deletion of each environment with the wait for its namespaces (FR-025). At the end it prints one summary table:

```text
Demo                  Result       Video                                   Length
deploy-upgrade        recorded     demo-videos/1-deploy-upgrade.mp4        0:52
component-overrides   recorded     demo-videos/2-component-overrides.mp4   1:21
backup-restore        failed       step "Restore the backup": <error>      -
                                   kept environments: network-lab-backup
                                   next: inspect the kept environments in the Styrmin UI, then delete them
                                   with 'uv run invoke record --delete-environments --demo backup-restore'
                                   next: read the error above, then record the demo again with
                                   'uv run invoke record --demo backup-restore'
clone                 recorded     demo-videos/4-clone.mp4                 1:30
```

- A recorded video longer than 3:00 is listed with a warning (SC-002). The command still exits 0 for it.
- A failed demo lists the failing step, the error, the environments it kept, the kept recording when the encoding failed, and one next step for each (FR-010, FR-025). The summary adds that kept environments still use the cluster's memory, and that `--delete-environments` deletes them (critique P3).
- An interrupted demo is listed as `interrupted` with the step it was in and the environments it kept; the demos after it are listed as `skipped` (FR-023).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every requested demo was recorded, or `--delete-environments` or `--encode-again` succeeded. |
| 1 | At least one demo failed. The other demos still ran (FR-011). |
| 2 | The prerequisites check, the image build or the confirmation of a deletion failed, or `--demo` names an unknown slug. No setup ran. |
| 130 | Ctrl-C stopped the command, after it printed the summary so far (FR-023). |

## Files written

- `<output-dir>/<number>-<slug>.mp4`: H.264, `yuv420p`, 1920×1080, 30 frames per second, no audio track, `faststart` (FR-007, research R-004). It ends on a closing card of 6 s (FR-020). A file is written only when its demo's recording and encoding succeed; a failed run of a demo leaves the previous video of that demo in place.
- `<output-dir>/<number>-<slug>.chapters.txt`: one line per chapter, `<m:ss> <title>`, then `<m:ss> Summary` for the closing card (FR-021).
- Each file is written under a temporary name in the output directory and then renamed, so the output directory never holds a part of a file.
- Raw recordings, label images and the plan of each video go to a work directory named `styrmin-demo-<slug>-*` in the system's temporary directory. The command deletes it when the demo ends, except after a failed encoding, when it keeps it for `--encode-again` (FR-024).
