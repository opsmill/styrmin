# Contract: The Demo Record Command

The feature's only interface is a developer command. It changes no GraphQL, SDK or `styrminctl` surface (FR-018).

## Invocation

```bash
uv run invoke record                                   # all four demos, in PRD order
uv run invoke record --demo backup-restore             # one demo
uv run invoke record --demo clone --output-dir /tmp/v  # another output directory
uv run invoke record --build-image                     # rebuild the demo Semaphore image first
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--demo` | all four | One slug: `deploy-upgrade`, `component-overrides`, `backup-restore` or `clone` (FR-001). An unknown slug stops the command before any check, with a message that lists the four slugs. |
| `--output-dir` | `demo-videos/` at the repository root, ignored by git | Where the MP4 files are written (FR-007). |
| `--build-image` | off | Rebuild the demo Semaphore image even when it exists. Without it, the command builds the image only when it is missing, as `uv run invoke start` does for the Styrmin image ([`tasks/demo.py`](../../../tasks/demo.py)). |

The task lives in [`tasks/demo.py`](../../../tasks/demo.py) next to `build`, `start`, `stop`, `destroy` and `reset`. It runs the recorder as `python -m tests.e2e.demos` from `backend/`, the same way `uv run invoke test` runs pytest from `backend/`, so the recorder imports the E2E page objects (research R-010).

## Prerequisites check (FR-012)

Run before any setup, in this order. The first failure stops the command with exit code 2 and one message that names what is missing:

| Check | Message on failure |
| --- | --- |
| `ffmpeg` is on the PATH | `ffmpeg is not on the PATH. Install it (for example 'brew install ffmpeg' or 'apt install ffmpeg') and run the command again.` |
| The demo stack's GraphQL endpoint at `http://styrmin.local.styrmin.io:8080/graphql` answers, and the admin login from `dev/local/demo-values.yaml` succeeds | `The demo stack does not respond at http://styrmin.local.styrmin.io:8080. Run 'uv run invoke start' first.` |
| The `infrahub` and `semaphore` drivers are loaded, the `local` cluster exists and has a backup storage location | `The demo stack is missing <item>. Run 'uv run invoke start' again.` |
| The Infrahub versions file is valid | `<path>: <problem>` |

## Output

For each demo, in order, the command prints the step titles as they start and the waits as they end, with their real durations. At the end it prints one summary table:

```text
Demo                  Result     Video                               Length
deploy-upgrade        recorded   demo-videos/1-deploy-upgrade.mp4    2:41
component-overrides   recorded   demo-videos/2-component-overrides.mp4  1:52
backup-restore        failed     step "Restore the backup": <error>  -
                                 kept environments: network-lab-backup
clone                 recorded   demo-videos/4-clone.mp4             2:58
```

- A recorded video longer than 3:00 is listed with a warning (SC-002). The command still exits 0 for it.
- A failed demo lists the failing step, the error and the environments it kept (FR-010).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every requested demo was recorded. |
| 1 | At least one demo failed. The other demos still ran (FR-011). |
| 2 | The prerequisites check failed. No setup ran. |

## Files written

- `<output-dir>/<number>-<slug>.mp4`: H.264, `yuv420p`, 1920×1080, 30 frames per second, no audio track, `faststart` (FR-007, research R-004). A file is written only when its demo succeeds; a failed run of a demo leaves the previous video of that demo in place.
- Raw recordings and label images go to a temporary directory that the command deletes when the demo ends, whatever the result.
