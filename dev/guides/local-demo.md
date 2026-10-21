# Local Demo on vCluster

A turnkey local Styrmin environment — server, agent, Prefect, Postgres,
Garage, Velero, and a Traefik ingress — running entirely inside a vCluster.
The top-level invoke commands below drive the full lifecycle.

## Prerequisites

| Tool | Used for |
|------|----------|
| `docker` | Runs the vCluster node and builds the Styrmin image |
| `vcluster` | Creates the virtual Kubernetes cluster |
| `helm` | Installs Styrmin, Traefik, and Velero |
| `kubectl` | Applies the Garage manifest, waits for deployments, port-forwards Traefik |

DNS for the demo hostname `styrmin.local.styrmin.io` is provided by the
Cloudflare-hosted wildcard `*.local.styrmin.io` → `127.0.0.1`; no
`/etc/hosts` edit is needed.

## Commands

| Command | Description |
|---------|-------------|
| `uv run invoke build` | Build the `registry.opsmill.io/opsmill/styrmin:latest` image and update Helm dependencies |
| `uv run invoke start` | Create the vCluster and deploy everything end-to-end |
| `uv run invoke stop` | Pause the environment (`vcluster pause`), preserving state |
| `uv run invoke destroy` | Delete the vCluster and all associated resources |
| `uv run invoke reset` | `destroy` + `start` — start fresh |
| `uv run invoke record` | Record the feature demos as MP4 videos on the running stack (see [Recording the demos](#recording-the-demos)) |

`start` auto-builds the image if it's missing. Pass `--build-image` to
force a rebuild.

## Access URLs

After `start` completes, the summary panel prints the demo URL:

```
http://styrmin.local.styrmin.io:8080
```

`start` backgrounds a `kubectl port-forward svc/traefik 8080:80` (PID
recorded at `.vcluster/traefik.pid`) and `stop` tears it down. The
non-privileged port is needed on macOS, and we use it on Linux too so
the flow is identical across platforms.

The GraphQL endpoint is the same base URL + `/graphql`.

Garage has no web console. Its S3 endpoint is reachable on demand via:

```bash
kubectl port-forward svc/garage 3900:3900 -n styrmin
```

Credentials: access key `GKdeadbeefdeadbeefdeadbeef`, secret key
`deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef`,
region `garage`, bucket `velero`. Point any S3 client at
`http://localhost:3900` with path-style addressing.

## Platform notes

- **Traefik exposure**: Installed with `service.type=ClusterIP` on every
  platform and reached via a backgrounded `kubectl port-forward
  svc/traefik 8080:80`. We avoid `service.type=LoadBalancer` (and
  vCluster's embedded LB provider) on Linux for parity with macOS — one
  code path, one access URL, no host-network surprises.
- **Single shared ingress**: The demo cluster is bootstrapped with
  `ingress_class=traefik` only — `dedicated_ingress` is intentionally
  omitted so every deployment's Ingress is served by the one front-door
  Traefik. The per-environment dedicated-Traefik path exists for
  multi-environment isolation in production and would not be reachable
  through the single port-forward.

## Recording the demos

`uv run invoke record` records videos of four Styrmin features for the beta
presentation ([#518](https://github.com/opsmill/styrmin/issues/518)) and
writes one MP4 file for each demo. It runs on the demo stack that
`uv run invoke start` creates. Fatih Acar owns the command.

### Record the demos for the first time

1. Check out the `develop` commit that merges
   [PR #540](https://github.com/opsmill/styrmin/pull/540), or a later one.
   The beta videos are recorded from that commit. Demo 1 needs the fix to
   [#372](https://github.com/opsmill/styrmin/issues/372)
   ([PR #535](https://github.com/opsmill/styrmin/pull/535)) and demo 4 the fix
   to [#530](https://github.com/opsmill/styrmin/issues/530)
   ([PR #531](https://github.com/opsmill/styrmin/pull/531)). The first
   `develop` commit that holds both fixes is `bb56eac9`.
2. Install the tools: the ones in [Prerequisites](#prerequisites), ffmpeg
   (`brew install ffmpeg` or `apt install ffmpeg`), then `uv sync` and
   `uv run playwright install chromium`.
3. Build the Styrmin image from the checkout: `uv run invoke build`.
   `uv run invoke start` reuses an image that already exists, even one built
   from an older commit, so build the image after each checkout. With an image
   built before the fixes, demo 1 fails after about 8 minutes, and its error
   names the fix to #372.
4. Create the demo stack from that image: `uv run invoke reset`. It deletes the
   vCluster `styrmin` and everything in it.
5. Record the four demos: `uv run invoke record`. The run takes about 50 minutes.
6. Watch each video in `demo-videos/`, with the
   [notes for the presenter](#notes-for-the-presenter).

### When to record the demos again

Record the demos again:

- before each presentation that uses the videos;
- after a change to a page of the Styrmin UI that a demo uses;
- after a change to `backend/tests/e2e/demos/infrahub_versions.yml`.

CI does not run the demos. The Styrmin page-object methods that the demos
added are also called by the `[ui-chromium]` variants of
`test_override_then_clear` and `test_token_follows_upgrade_and_action_job` in
`backend/tests/e2e/test_deployment_image_override.py`, and by
`test_pods_tab_copy_logs_command` in `backend/tests/e2e/test_ui_smoke.py`, so
a UI change that breaks them fails an E2E test. No test uses the page objects
for Infrahub and Semaphore in `backend/tests/e2e/demos/pages/`: a recording
of demos 3 and 4 is their only test.

### The four demos

| Slug | Video file | Environments the demo creates | What the video shows |
|------|------------|-------------------------------|----------------------|
| `deploy-upgrade` | `1-deploy-upgrade.mp4` | `network-lab-upgrade` | Infrahub deployed at the `previous` version and upgraded to `latest`, then the upgrade task with the step that runs the driver's upgrade action |
| `component-overrides` | `2-component-overrides.mp4` | `network-lab-overrides` | An image override on the Semaphore `server` component, then the Pods tab with the server pod on the new image; a replica override of 2 on the Infrahub `server` component, then the Pods tab with two server pods |
| `backup-restore` | `3-backup-restore.mp4` | `network-lab-backup` | An environment backup, a device deleted in Infrahub and a task template deleted in Semaphore, an environment restore, and the device and the template back |
| `clone` | `4-clone.mp4` | `network-lab` and `network-lab-clone` | An environment clone whose Semaphore lists a device added in the clone's Infrahub, while the source's Semaphore does not |

Demo 1 shows the `infrahub` driver's upgrade action, which stops the Infrahub
server and task workers, runs `infrahub upgrade` in a job, and starts them
again. The Styrmin agent runs the action from the driver directory
`/styrmin/drivers/infrahub` in the agent pod
([Actions of a driver loaded from a local directory](../../docs/docs/drivers/loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory)).
Since the fix to #372, an upgrade runs the action; before it, it did not. The
demo fails unless the upgrade task lists the step "Run the upgrade hook" as
succeeded and its entry on the Timeline tab shows the `latest` version.

Demos 3 and 4 deploy the `infrahub-enterprise` application driver instead of
`infrahub`. The environment backup runs `neo4j-admin database backup` on
Infrahub's database, which needs Neo4j Enterprise, and the `infrahub` driver
deploys the community edition. The demos load the driver from
`/styrmin/drivers/infrahub-enterprise` in the Styrmin image, and the driver
stays loaded after the demo.

Demo 4 needs the fix to #530: since that fix, an environment clone writes its
own service aliases, so the clone's Semaphore reaches the clone's Infrahub by
the short name `infrahub`. With an image built before the fix, the clone's
Semaphore lists 2 devices instead of 3, and the error names the fix.

### What the command does for each demo

1. It deletes the demo's environments that an earlier run of the command left
   (see [Environments the command deletes](#environments-the-command-deletes)).
2. It creates the demo's environment and deployments through the SDK, and,
   when the demo needs them, loads devices into Infrahub and a project into
   Semaphore. This part is not recorded.
3. It performs the feature in the Styrmin UI with the E2E page objects, and in
   Infrahub and Semaphore when the demo uses them, while Playwright records the
   browser page.
4. It deletes the demo's environments while ffmpeg encodes the video, so that
   the environments and ffmpeg do not use memory at the same time.

### Environments the command deletes

Before its setup, each demo deletes the environments on the cluster `local`
that have the demo's names (see the table above), and after a successful
recording it deletes them again. The command deletes only environments that it
created itself. It records their ids in
`$XDG_STATE_HOME/styrmin/demo-environments.json` (by default
`~/.local/state/styrmin/demo-environments.json`), for each demo stack URL.

When an environment with one of these names exists and the command did not
create it, for example one made by hand or by a version of the command from
before this file existed, the command lists it before the first demo and asks
`Delete them? [y/N]`. Without a yes, or when no terminal can answer, the
command stops with exit code 2 and changes nothing. Give your own environments
other names than `network-lab`, `network-lab-*`.

### Prerequisites for recording

- The tools in [Prerequisites](#prerequisites) and a demo stack that
  `uv run invoke start` created. The command waits for the deleted
  deployments' namespaces through the kube context `vcluster-docker_styrmin`,
  which `vcluster connect` writes during `uv run invoke start`.
- `ffmpeg` and `ffprobe` on the PATH, any build with libx264.
- The Chromium build of the Playwright version in `uv.lock` (1.64), from
  `uv run playwright install chromium`.
- Network access:
  - building the demo Semaphore image downloads the `opsmill.infrahub`
    Ansible collection from Ansible Galaxy and `infrahub-sdk` from PyPI;
  - each start of Semaphore in the vCluster runs `pip install infrahub-sdk`
    from PyPI (`general.additionalPythonPackages` in the `semaphore`
    driver's values).
- Memory: demo 4 (`clone`) runs Infrahub and Semaphore in two environments
  at the same time. It was measured with `free -m` every 20 seconds in two
  runs on 2026-10-20, on a Linux host with 31,465 MiB of memory, no swap, and
  other processes running:
  - in the run of the four demos, the memory in use rose from 17,604 MiB
    before demo 4 to at most 26,672 MiB during it, and the available memory
    fell to 4,792 MiB, while ffmpeg encoded the video and the two environments
    still ran;
  - in a recording of demo 4 alone, the memory in use rose from 17,330 MiB to
    at most 26,993 MiB, and the available memory fell to 4,472 MiB.

  How much of that the two environments used is not measured. Since then, the
  command deletes the environments while ffmpeg encodes. In the run of the
  four demos on 2026-10-21, the memory in use rose from 16,810 MiB before
  demo 4 to at most 26,130 MiB during it, and the available memory fell to
  5,335 MiB.
- Disk: the vCluster's node evicts pods when the host's free disk falls below
  15% of its size, 14.4 GiB on a 96 GB disk. The demos pull Infrahub, Infrahub
  Enterprise, Neo4j and Semaphore images into the vCluster during the run. On
  2026-10-21, a run that started with 18 GB free fell below that limit during
  demo 1: Velero, Prefect and Garage were evicted, and demos 2 to 4 failed in
  their setup with "An internal error occurred". The next run, started with
  20 GB free, recorded the four demos; 6.6 GB of Docker build cache was
  deleted during it, and the free disk never fell below 17 GB. Check
  `df -h /` before a run;
  `docker system df` shows which images and build cache take the space.

Before any demo, the command checks in this order, and the first check that
fails stops it with exit code 2 and a message that names what is missing:

1. `ffmpeg` and `ffprobe` are on the PATH;
2. the Chromium build of the installed Playwright exists;
3. `docker` is on the PATH, when a selected demo deploys the demo Semaphore
   image;
4. the kube context `vcluster-docker_styrmin` reaches the demo stack;
5. the demo stack answers at `http://styrmin.local.styrmin.io:8080`;
6. the demo stack accepts the admin login from `dev/local/demo-values.yaml`.
   The stack keeps the password it was created with, so run
   `uv run invoke reset` after a change to that file;
7. the `infrahub` and `semaphore` drivers are loaded, and the `local`
   cluster and the `local` backup storage location exist;
8. the Infrahub versions file is valid.

Then the command builds the demo Semaphore image when a selected demo deploys
it, and confirms the environments it may delete.

### Commands to record the demos

```bash
uv run invoke record                                     # the four demos, in order
uv run invoke record --demo backup-restore               # one demo
uv run invoke record --demo clone --demo deploy-upgrade  # several demos, in order
uv run invoke record --output-dir /tmp/videos            # write the videos to another directory
uv run invoke record --build-image                       # build the demo Semaphore image without Docker's cache
uv run invoke record --delete-environments               # only delete the demos' environments
uv run invoke record --encode-again <directory>          # only encode a recording that a failed encoding kept
```

Before demos 2 to 4, the command builds the demo Semaphore image
`styrmin-demo/semaphore:v2.16.47` from `backend/tests/e2e/demos/semaphore/`.
Docker reuses its cached layers when nothing changed, so the build takes a
few seconds, and a changed Dockerfile or playbook always reaches the image.
The image adds the `opsmill.infrahub` collection 1.8.3, `infrahub-sdk` 1.23.2
and the demo playbook to `semaphoreui/semaphore:v2.16.47`, pinned by its
digest. The `FROM` line of the Dockerfile is the one place that names the
Semaphore version: the command tags the image with it and deploys the
`semaphore` driver at it. The vCluster uses the image from the host's Docker,
and the image is never pushed to a registry.

### Infrahub versions the demos deploy

`backend/tests/e2e/demos/infrahub_versions.yml` holds two quoted versions:

- `previous` (`1.10.11` today): the version demo 1 deploys before it
  upgrades;
- `latest` (`1.11.7` today): the version demo 1 upgrades to and every other
  demo deploys.

Someone updates the file by hand, for example when a new Infrahub release
should appear in the videos. The prerequisites check fails when a key is
missing, when a value is not a quoted version, or when `latest` is not
greater than `previous`.

A new Infrahub release may need a newer Helm chart in the application
driver: `spec.helm.main.version` in
`driver/examples/infrahub/driver.styrmin.yml` (chart 4.33.2 today) and in
`driver/examples/infrahub-enterprise/driver.styrmin.yml` (chart 4.19.2
today). Which chart versions run which Infrahub releases is not recorded
here. On 2026-10-18, chart 4.33.2 ran 1.10.11 and 1.11.7, and chart 4.19.2
ran 1.11.7. The demo stack reads the drivers from the Styrmin image
(`/styrmin/drivers/<name>`), so a changed driver reaches the demo stack after
`uv run invoke build` and `uv run invoke reset`.

### Videos and files the command writes

- The videos go to `demo-videos/` at the repository root, which git ignores,
  or to the directory that `--output-dir` names.
- Each video is named `<number>-<slug>.mp4`, for example
  `2-component-overrides.mp4`. It is H.264, `yuv420p`, 1920×1080, 30 frames
  per second, with no audio track and with its index at the start of the file
  (`faststart`). Whether the videos play in Keynote, PowerPoint and Google
  Slides without conversion is not checked yet.
- Each video keeps a caption in its bottom left corner that names the
  application on screen and its environment, for example
  `Semaphore in network-lab-clone (clone)`. Each sped-up wait shows a label
  with its real duration and the speed-up factor, for example
  `The upgrade runs (2 min 55 s, shown 44× faster)`. Each video ends on a
  closing card of 6 seconds that gives the demo's title and what it showed.
- Next to each video, `<number>-<slug>.chapters.txt` gives the start of each
  chapter in the video, one `<minutes>:<seconds> <title>` line per chapter,
  then the start of the closing card, `Summary`.
- The command writes the video and its chapter file only when the demo's
  recording and encoding succeed, each under a temporary name that it then
  renames. A failed run leaves the previous video of that demo in place.
- Raw recordings, label images and the plan of each video go to a work
  directory named `styrmin-demo-<slug>-*` in the system's temporary directory.
  The command deletes it when the demo ends, except when the encoding fails:
  then it keeps it, so that `uv run invoke record --encode-again <directory>`
  can encode the video again without recording again. A recording of demo 1
  or 3 takes about 10 minutes.
- When deleting the environments fails after the video was written, the
  video stays and the summary reports the demo as failed in step `cleanup`.

### What the command prints while it runs

- Before each demo, how long it usually takes, setup and cleanup included.
- Each sub-step of the setup: each environment it creates, each deployment
  and the wait until it runs, the load of the devices into Infrahub and of
  the project into Semaphore.
- Each step title when the step starts, and each wait for the cluster when it
  starts and when it ends, with its real duration.
- During a wait or a deletion, one line every minute, so that a wait of
  several minutes, such as a restore, never looks like a hang.

At the end it prints a table with one line for each demo and the columns
Demo, Result, Video and Length. The Result column holds one of these values:

- `recorded`: the video was written. Video gives its path and Length its
  length in minutes and seconds. A video longer than 3:00 gets a warning
  line, and the command still counts it as recorded.
- `failed`: Video gives the step that failed (`setup`, a step title,
  `post-processing` or `cleanup`), the error, the environments the demo
  kept, the recording it kept, and one `next:` line for each thing to do. The
  full traceback is printed before the summary. The other demos still run.
- `interrupted`: Ctrl-C stopped the demo; Video gives the step it was in and
  the environments it kept.
- `skipped`: the demo did not run, because the prerequisites check, the image
  build or the confirmation of a deletion failed, or because Ctrl-C stopped an
  earlier demo.

The exit code is 0 when every requested demo was recorded, 1 when at least
one demo failed, 2 when the prerequisites check, the image build or the
confirmation of a deletion failed, or when `--demo` names a slug that is not
one of the four, and 130 after Ctrl-C.

### Stop a run with Ctrl-C

Ctrl-C stops the demo that runs, closes the browser and the Styrmin client,
prints the summary of the demos so far, and exits with code 130. The summary
lists the environments that the stopped demo kept. They still use the
vCluster's memory: delete them with
`uv run invoke record --delete-environments --demo <slug>`, or let the next
recording of that demo delete them. A second Ctrl-C stops the command at once,
without a summary.

### What to do after a failed demo

1. Read the failing step and the error in the summary, and the traceback
   above it. Each failed line ends with the next steps.
2. Inspect the environments the summary lists as kept. They are in the
   Styrmin UI with their deployments. In the vCluster, each deployment runs
   in namespace `styrmin-<deployment id>`:

   ```bash
   kubectl get ns | grep styrmin-
   kubectl get pods -n styrmin-<deployment id>
   ```

3. Delete the kept environments once they are no longer needed:
   `uv run invoke record --delete-environments --demo <slug>`. Kept
   environments still use the vCluster's memory, which can make later demos of
   the same run fail.
4. When the encoding failed, encode the kept recording with
   `uv run invoke record --encode-again <directory>`. Otherwise, record the
   demo again with `uv run invoke record --demo <slug>`. The command deletes
   the kept environments before the setup and waits until their namespaces
   are gone, for at most 10 minutes. Only that demo's video is replaced.

### Notes for the presenter

Each video has no voice. Each chapter starts with its title in the middle of
the page; the chapter file gives where each one starts. Each wait for the
cluster plays faster, with a label at the bottom that gives its real duration.
The caption in the bottom left corner says which application and which
environment are on screen.

1. **Deploy and upgrade Infrahub.** The demo deploys Infrahub at the
   `previous` version into the empty environment `network-lab-upgrade`, then
   upgrades it to `latest` from the Upgrade dialog. The last chapter shows the
   upgrade task on the Timeline tab. Point at the step "Run the upgrade hook":
   the Infrahub driver's upgrade action stopped Infrahub, ran
   `infrahub upgrade` in a job, which applies the database migrations, and
   started Infrahub again. Above the upgrade task, the timeline lists the two
   tasks that the action started, "Stop Components" and "Start Components".
   The three steps after "Run the upgrade hook" show
   "Superseded by Stop Components": stopping Infrahub replaced the rollout
   that these steps describe. The upgrade task's result is Succeeded.
   "Stop Components" can itself show Superseded instead of Succeeded, when
   "Start Components" changes the deployment before the operator reports that
   the stop finished; the upgrade succeeded in both cases.
2. **Override the image and the replicas of a component.** The demo changes
   one component of each deployment, without a change to its application
   driver. First it sets the image of the Semaphore `server` component to
   `styrmin-demo/semaphore:v2.16.47`, an image that adds the Infrahub Ansible
   collection; the Settings tab shows the override, and the Pods tab shows
   the server pod with the new image. The Pods tab cuts the image name to
   `docker.io/styrmin-demo/semaph…`, because its image column is narrow; the
   Settings tab shows the full name just before. Then it sets 2 replicas on the
   Infrahub `server` component; the Pods tab shows two server pods.
3. **Back up and restore an environment.** One backup covers both
   applications of `network-lab-backup`, Infrahub and Semaphore. The demo then
   deletes the device `sw2` in Infrahub and the task template
   "List network devices" in Semaphore, restores the backup, and shows both
   back. The restore is the longest wait of the four demos: it took between
   1 and 6 minutes in the recordings of 2026-10-18 to 2026-10-20. After the
   restore, Infrahub and Semaphore restart, which the video also shows faster.
4. **Clone an environment.** The caption tells the two environments apart:
   `network-lab` is the source and `network-lab-clone` the clone, and their
   Semaphore pages look the same. Semaphore reads its inventory from the
   Infrahub of its own environment, by the short name `infrahub`. The source
   lists 2 devices. The demo clones the environment, adds the device `sw3` in
   the clone's Infrahub, and runs the same task template in the clone's
   Semaphore, which lists 3 devices without any change to its settings. The
   source still lists 2. Both runs after the clone are "Task #2", because the
   clone's Semaphore database is a copy of the source's, which held task #1.

### Time a run takes

Measured on one Linux host:

- `uv run invoke reset`: between 2 min 9 s and 2 min 52 s in four runs from
  2026-10-18 to 2026-10-21.
- `uv run invoke record` with the four demos, on 2026-10-21: 50 min 13 s. The
  demo stack was 23 minutes old; a first run on it had failed in demos 2 to 4
  because the disk was full. Each demo took, including its setup, recording,
  encoding and cleanup:
  - `deploy-upgrade`: 9 min 31 s, for a video of 0:51;
  - `component-overrides`: 15 min 11 s, for a video of 1:18. 5 min 8 s of it
    went to deleting the environment that an interrupted run had kept;
  - `backup-restore`: 14 min 53 s, for a video of 1:34;
  - `clone`: 10 min 14 s, for a video of 1:32.
- The same run of 2026-10-20, before the review of PR #540 added the Pods tab
  to demo 2, longer pauses on each result and the closing card: 48 min 28 s,
  for videos of 0:35, 0:45, 1:08 and 1:08.
- `uv run invoke record --demo backup-restore` after a failed run of demo 3,
  on 2026-10-18: 20 min 40 s, of which about 5 min 45 s went to deleting the
  environment the failed run kept.

The setup, which deploys Infrahub and Semaphore and waits for them, and the
waits for the cluster take most of the time. The environment restore of demo 3
took between 1 min 9 s and 5 min 40 s over seven runs, 5 min 1 s on
2026-10-21; the cause of the difference is not known. After each recording of
2026-10-21, the deletion of the demo's environments, which waits until their
namespaces are gone, took between 2 min 1 s and 4 min 1 s, while ffmpeg
encoded the video.

### Problems seen when recording the demos

- kr8s prints `UserWarning: Kubernetes version v1.36.0 is not supported`:
  the vCluster runs a Kubernetes version that kr8s 0.20.15 does not list. The
  warning did not affect the runs of 2026-10-18 and 2026-10-20.
- When the host disk is nearly full, the vCluster's node evicts pods, and
  Styrmin operations fail with "An internal error occurred". This happened on
  2026-10-21 in an E2E run and in a recording, both with the host disk 85%
  full (see the disk item in
  [Prerequisites for recording](#prerequisites-for-recording)). Run
  `kubectl get events -n styrmin | grep Evicted` to confirm it. Free disk
  space, wait until `kubectl get pods -n styrmin` shows the evicted pods
  running again, then record the failed demos again with `--demo`.
- `uv run invoke start` or `uv run invoke reset` fails before the recording
  can start: see the Traefik and Helm items in
  [Troubleshooting](#troubleshooting).

## Troubleshooting

**`invoke start` hangs on "Waiting for the Styrmin server to be ready"**
— check `kubectl get pods -n styrmin` for pending/errored pods. Postgres
takes the longest on first start (it initializes the `prefect` database).

**URL works briefly then stops responding** — the backgrounded
port-forward died. Check `/tmp/styrmin-traefik-portforward.log`, then
re-run `uv run invoke start` to restart it (safely idempotent).

**Bootstrap fails with "Cluster already exists"** — expected on a
re-run; `start` catches this and continues. The bootstrap records
(`local` cluster, `local` environment, `infrahub` driver) persist across
`stop`/`start` cycles because the Postgres PVC is preserved.

**Want to rebuild the image?** Use `uv run invoke start --build-image`
or `uv run invoke build` followed by `uv run invoke start`.

**`invoke start` fails because Traefik never becomes ready** — on a Linux
host, check the Flannel pods (`kubectl get pods -n kube-flannel`). When their
logs show `Failed to check br_netfilter: stat
/proc/sys/net/bridge/bridge-nf-call-iptables: no such file or directory`, the
host kernel has not loaded the `br_netfilter` module. Load it with
`sudo modprobe br_netfilter` and run `uv run invoke reset`.

**`helm upgrade --install styrmin` fails with "found in Chart.yaml, but
missing in charts/ directory"** — `uv run invoke start` runs
`uv run invoke build`, the task that runs `helm dependency update`, only when
the Styrmin image is missing. A checkout without `helm/styrmin/charts/`
therefore fails when the image already exists on the host. Run
`uv run invoke build`, then `uv run invoke start` again.
