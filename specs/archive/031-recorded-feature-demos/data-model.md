# Data Model: Recorded Demos of Four Styrmin Features

The feature adds no Styrmin entity, no database table and no GraphQL type ([spec.md](spec.md), Key Entities). The records below exist only in the recorder's memory while a demo runs, plus two files kept in the repository, the Infrahub versions file and the device schema, and, since the review of PR #540, the video plan in each work directory and the file of the environments the command created.

## Demo

One of the four recorded demos.

| Field | Type | Rule |
| --- | --- | --- |
| `slug` | string | One of `deploy-upgrade`, `component-overrides`, `backup-restore`, `clone`. The developer names a demo by its slug (FR-001). |
| `number` | integer | 1 to 4, the order in the PRD. Used in the video file name, for example `3-backup-restore.mp4`. |
| `environment_names` | list of strings | The fixed environment names the demo creates (FR-008). No two demos share a name, so a demo never deletes the environment that another demo's failed run kept (FR-009, FR-010). |
| `setup` | async function | Creates what the demo needs through the SDK and the Infrahub and Semaphore APIs. Not recorded (FR-002). |
| `record` | async function | Performs the recorded steps through page objects (FR-003). |
| `title` | string | The title of the closing card (FR-020). |
| `summary` | list of strings | The lines of the closing card; `{previous}`, `{latest}` and `{semaphore_image}` are filled in (FR-020). |
| `expected_minutes` | integer | How long a run of the demo usually takes, printed before it starts (FR-025). |
| `uses_semaphore_image` | boolean | True for demos 2 to 4: the command builds the demo Semaphore image before them. |

Environment names, from FR-008:

| Demo | Environments | Deployments in each environment | Infrahub driver |
| --- | --- | --- | --- |
| `deploy-upgrade` | `network-lab-upgrade` | `infrahub` (created during the recording) | `infrahub` |
| `component-overrides` | `network-lab-overrides` | `infrahub`, `semaphore` | `infrahub` |
| `backup-restore` | `network-lab-backup` | `infrahub`, `semaphore` | `infrahub-enterprise` (research R-007) |
| `clone` | `network-lab`, `network-lab-clone` | `infrahub`, `semaphore` (the clone's are counterparts) | `infrahub-enterprise` (research R-007) |

## Step

A titled part of a recording.

| Field | Type | Rule |
| --- | --- | --- |
| `title` | string | Shown as a chapter title at the start of the step (FR-004). Also names the step in a failure report (FR-010). |
| `started_at` | float | Seconds since the screencast started. |

## Wait

A part of a recording during which the demo waits for the cluster (FR-005).

| Field | Type | Rule |
| --- | --- | --- |
| `label` | string | What the cluster is doing, for example "Infrahub is starting". |
| `start` | float | Seconds since the screencast started. |
| `end` | float | Seconds since the screencast started. `end > start`. |

Waits do not overlap and are recorded in order. A wait shorter than the speed-up threshold is played at normal speed.

## Cut

A part of a recording that the final video leaves out: the time the recorder spends logging in to a web application on a page that is not recorded (research R-016).

| Field | Type | Rule |
| --- | --- | --- |
| `start` | float | Seconds since the screencast started. |
| `end` | float | Seconds since the screencast started. `end > start`. |

Cuts and waits do not overlap.

## Segment

A part of the final video, computed from the waits, the cuts and the raw video's duration by the post-processor's pure planning function (research R-005).

| Field | Type | Rule |
| --- | --- | --- |
| `start` | float | Seconds in the raw video. |
| `end` | float | Seconds in the raw video. |
| `kind` | `normal`, `sped_up`, `cut` | `cut` parts are left out of the final video. |
| `factor` | integer | 1 for a `normal` part; 2 or more for a `sped_up` part; not used for a `cut` part. |
| `label` | string or none | Present only when `factor > 1`. Gives the wait, its real duration and the factor, for example "The backup runs (4 min 12 s, shown 63× faster)" (FR-020). |

Rules:

- The segments, including the cut ones, cover the raw video from 0 to its duration with no gap and no overlap.
- A sped-up segment lasts `(end - start) / factor` seconds in the final video, and that length is at most the target length of a sped-up wait.
- The planned length of the final video is the sum of the segments' final lengths, then 6 s of closing card. The recorder reports a warning when the video exceeds 180 seconds (SC-002).

## Video plan

What the encoder needs besides the raw video: the video's file name, the segments, the chapters (each step title with its start in the raw video) and the closing card. The command saves it as `plan.json` next to `raw.webm` in the demo's work directory before it encodes, so that `--encode-again` can encode a kept recording (FR-024). The chapter file next to each MP4 gives each chapter's start in the final video, where a time inside a cut moves to the first frame after it (FR-021).

## Created environments file

`$XDG_STATE_HOME/styrmin/demo-environments.json` (by default under `~/.local/state`) maps each demo stack URL to the ids and names of the environments that the command created, or that the developer confirmed. The command deletes an environment with a demo's name only when its id is in this file (FR-009). An environment created again by `uv run invoke reset` has a new id, so ids left in the file never match it.

## Demo result

One line of the command's summary (FR-011).

| Field | Type | Rule |
| --- | --- | --- |
| `slug` | string | The demo. |
| `status` | `recorded`, `failed`, `interrupted`, `skipped` | `interrupted` when Ctrl-C stopped the demo (FR-023); `skipped` when the demo did not run, because the prerequisites check, the image build or the confirmation of a deletion failed (FR-012), or because Ctrl-C stopped an earlier demo. |
| `video_path` | path or none | Set only when `status` is `recorded`. |
| `video_seconds` | float or none | Length of the final video. |
| `failed_step` | string or none | The title of the step that failed, or `setup`, `recording`, `post-processing` or `cleanup`. |
| `error` | string or none | The error message. |
| `kept_environments` | list of strings | The environments left for inspection after a failure or an interruption (FR-010). |
| `kept_work_dir` | path or none | The work directory with the raw recording and the video plan, kept after a failed encoding (FR-024). |

State transitions of one demo run:

```text
cleanup of leftovers -> setup -> recording -> post-processing -> deletion of environments -> recorded
        |                 |          |               |                      |
        +-----------------+----------+---------------+----------------------+--> failed
```

A failure before the recording keeps no video. A failure during the recording deletes the raw video. A failure during the post-processing keeps the raw video and the video plan, and deletes the partial video (FR-024). The deletion of the environments starts when the encoding starts; a failure while deleting them after a successful encoding keeps the video and reports the demo as failed with `failed_step = cleanup`.

## Infrahub versions file

`backend/tests/e2e/demos/infrahub_versions.yml`, updated by hand (FR-006).

| Key | Type | Rule |
| --- | --- | --- |
| `previous` | string | The Infrahub version demo 1 deploys. Within the `infrahub` driver's `supported_versions` (`>=1.5,<2.0`). |
| `latest` | string | The version demo 1 upgrades to, and the version demos 2 to 4 deploy. Greater than `previous`. |

The recorder validates both keys before any setup and stops with an error naming the file when a key is missing or `latest` is not greater than `previous`.

## Device schema

`backend/tests/e2e/demos/infrahub/schema.yml`: one Infrahub node kind for a network device with a unique `name` attribute, shown in the Infrahub menu. The setup loads it into each Infrahub it creates, before the recording starts (spec Clarifications, second session). The inventory file lists the devices of this kind (research R-008).
