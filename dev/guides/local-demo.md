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

`uv run invoke record` records demos of Styrmin features for the beta
presentation ([#518](https://github.com/opsmill/styrmin/issues/518)) and
writes one MP4 video for each demo. It runs on a demo stack that
`uv run invoke start` created. For each demo, the command:

1. deletes the environments that an earlier failed run of the same demo kept;
2. creates the demo's environment and deployments through the SDK, and,
   when the demo needs them, loads devices into Infrahub and a project into
   Semaphore, without recording;
3. performs the feature in the Styrmin UI with the E2E page objects, and in
   Infrahub and Semaphore when the demo uses them, while Playwright records
   the browser page;
4. shows each wait for the cluster that lasts longer than 6 s at a higher
   speed in the video, with a label that gives the real duration, and encodes the video with ffmpeg;
5. deletes the demo's environments.

The requirements are in [spec 029](../../specs/029-recorded-feature-demos/spec.md),
and the options, output and exit codes in the
[record command contract](../../specs/029-recorded-feature-demos/contracts/record-command.md).

### The four demos and which ones can be recorded today

| Slug | Video file | Environments the demo creates | What the video shows | Can be recorded today |
|------|------------|-------------------------------|----------------------|-----------------------|
| `deploy-upgrade` | `1-deploy-upgrade.mp4` | `network-lab-upgrade` | Infrahub deployed at the `previous` version and upgraded to `latest`, then the upgrade task with the step that runs the driver's upgrade action | Yes |
| `component-overrides` | `2-component-overrides.mp4` | `network-lab-overrides` | An image override on the Semaphore `server` component and a replica override of 2 on the Infrahub `server` component | Yes |
| `backup-restore` | `3-backup-restore.mp4` | `network-lab-backup` | An environment backup, a device deleted in Infrahub and a task template deleted in Semaphore, an environment restore, and the device and the template back | Yes |
| `clone` | `4-clone.mp4` | `network-lab` and `network-lab-clone` (planned) | An environment clone whose Semaphore lists a device added in the clone's Infrahub, while the source's Semaphore does not | No, waits for [#530](https://github.com/opsmill/styrmin/issues/530) |

Why `clone` is not available yet: an environment clone keeps the source's
service aliases, which point to the namespaces of the source environment, so
the clone's Semaphore would read the source's Infrahub
([E2E evidence](../../specs/029-recorded-feature-demos/e2e-evidence.md)).

`uv run invoke record` without `--demo` records every demo that is
available, so today it records `deploy-upgrade`, `component-overrides` and
`backup-restore`. `--demo clone` stops with exit code 2 and a message that
the demo is not available yet.

Demo 1 (`deploy-upgrade`) shows the `infrahub` driver's upgrade action, which
stops the Infrahub server and task workers, runs `infrahub upgrade` in a job,
and starts them again. The demo stack loads the driver from
`/styrmin/drivers/infrahub`, and the Styrmin agent runs the action from that
path in the agent pod, where the Styrmin image holds the driver too
([Actions of a driver loaded from a local directory](../../docs/docs/drivers/loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory)).
Before the fix to [#372](https://github.com/opsmill/styrmin/issues/372), the
upgrade did not run the action
([spike notes](../../specs/029-recorded-feature-demos/spike-notes.md#the-upgrade-runs-the-drivers-upgrade-action-since-the-fix-to-372)).
The demo fails unless the upgrade task lists the step "Run the upgrade hook"
as succeeded.

Demo 3 (`backup-restore`) deploys the `infrahub-enterprise` application
driver instead of `infrahub`. The environment backup runs
`neo4j-admin database backup` on Infrahub's database, which needs Neo4j
Enterprise, and the `infrahub` driver deploys the community edition
([research R-007](../../specs/029-recorded-feature-demos/research.md#r-007-environment-backups-need-the-infrahub-enterprise-driver)).
The demo loads that driver from `/styrmin/drivers/infrahub-enterprise` in the
Styrmin image, and the driver stays loaded after the demo.

### Prerequisites for recording

- The tools in [Prerequisites](#prerequisites) and a demo stack that
  `uv run invoke start` created. The command deletes the demo's environments
  through the Styrmin API, and reads the namespaces through the kube context
  `vcluster-docker_styrmin` to wait until they are gone. `vcluster connect`
  writes that context during `uv run invoke start`.
- `ffmpeg` on the PATH, any build with libx264, for example from
  `brew install ffmpeg` or `apt install ffmpeg`.
- The Chromium build of the Playwright version in `uv.lock` (1.64): run
  `uv sync`, then `uv run playwright install chromium`.
- Network access:
  - building the demo Semaphore image downloads the `opsmill.infrahub`
    Ansible collection from Ansible Galaxy and `infrahub-sdk` from PyPI;
  - each start of Semaphore in the vCluster runs `pip install infrahub-sdk`
    from PyPI (`general.additionalPythonPackages` in the `semaphore`
    driver's values).
- Memory: demo 4 (`clone`), once it is available, runs Infrahub and
  Semaphore in two environments at the same time. How much memory that needs
  is not measured.

### Commands to record the demos

```bash
uv run invoke record                            # every available demo, in order
uv run invoke record --demo backup-restore      # one demo
uv run invoke record --output-dir /tmp/videos   # write the videos to another directory
uv run invoke record --build-image              # rebuild the demo Semaphore image first
```

Before it starts the recorder, the command builds the demo Semaphore image
`styrmin-demo/semaphore:v2.16.47` from `backend/tests/e2e/demos/semaphore/`
when the image is missing, or every time with `--build-image`. The image
adds the `opsmill.infrahub` collection 1.8.3, `infrahub-sdk` and the demo
playbook to `semaphoreui/semaphore:v2.16.47`. The vCluster uses the image
from the host's Docker, and the image is never pushed to a registry.

Then, before any demo setup, the command checks in this order:

1. `ffmpeg` is on the PATH;
2. the demo stack answers at `http://styrmin.local.styrmin.io:8080` and the
   admin login from `dev/local/demo-values.yaml` works;
3. the `infrahub` and `semaphore` drivers are loaded, and the `local`
   cluster and the `local` backup storage location exist;
4. the Infrahub versions file is valid.

The first check that fails stops the command with exit code 2 and a message
that names what is missing.

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
today), which demo 3 uses. Which chart versions run which Infrahub releases
is not recorded here. On 2026-10-18, chart 4.33.2 ran 1.10.11 and 1.11.7, and
chart 4.19.2 ran 1.11.7 ([spike notes](../../specs/029-recorded-feature-demos/spike-notes.md)).
The demo stack reads the drivers from the Styrmin image
(`/styrmin/drivers/<name>`), so a changed driver reaches the demo stack after
`uv run invoke build` and `uv run invoke reset`.

### Videos the command writes

- The videos go to `demo-videos/` at the repository root, which git ignores,
  or to the directory that `--output-dir` names.
- Each file is named `<number>-<slug>.mp4`, for example
  `2-component-overrides.mp4`.
- Each video is H.264, `yuv420p`, 1920×1080, 30 frames per second, with no
  audio track and with its index at the start of the file (`faststart`).
  Whether the videos play in Keynote, PowerPoint and Google Slides without
  conversion is not checked yet.
- The command writes a video only when the demo's recording and encoding
  succeed. A failed run leaves the previous video of that demo in place.
- Raw recordings and label images go to a temporary directory named
  `styrmin-demo-<slug>-*`, which the command deletes when the demo ends,
  whatever the result.
- When deleting the environments fails after the video was written, the
  video stays and the summary reports the demo as failed in step `cleanup`.

### What the summary at the end of a run means

While it runs, the command prints each step title when the step starts and
each wait with its real duration when the wait ends. At the end it prints a
table with one line for each demo and the columns Demo, Result, Video and
Length. The Result column holds one of these values:

- `recorded`: the video was written. Video gives its path and Length its
  length in minutes and seconds. A video longer than 3:00 gets a warning
  line, and the command still counts it as recorded.
- `failed`: Video gives the step that failed (`setup`, a step title,
  `post-processing` or `cleanup`), the error, and the environments the demo
  kept. The full traceback is printed before the summary. The other demos
  still run.
- `skipped`: the prerequisites check failed, so no demo ran.

The exit code is 0 when every requested demo was recorded, 1 when at least
one demo failed, and 2 when the prerequisites check failed or `--demo` names
a demo that does not exist or is not available yet.

### What to do after a failed demo

1. Read the failing step and the error in the summary, and the traceback
   above it.
2. Inspect the environments the summary lists as kept. They are in the
   Styrmin UI with their deployments. In the vCluster, each deployment runs
   in namespace `styrmin-<deployment id>`:

   ```bash
   kubectl get ns | grep styrmin-
   kubectl get pods -n styrmin-<deployment id>
   ```

3. Delete the kept environments in the Styrmin UI once they are no longer
   needed. Kept environments still use the vCluster's memory, which can make
   later demos of the same run fail. They stay until the next run of the same
   demo deletes them, or until someone deletes them in the Styrmin UI.
4. Record the demo again with `uv run invoke record --demo <slug>`. The
   command deletes the kept environments before the setup and waits until
   their namespaces are gone, for at most 600 seconds. Only that demo's video
   is replaced.

### Time a run takes

Measured on 2026-10-18 on one Linux host
([full run log](../../specs/029-recorded-feature-demos/full-run.log)):

- `uv run invoke reset`: 2 min 52 s, and 2 min 9 s in an earlier
  measurement ([spike notes](../../specs/029-recorded-feature-demos/spike-notes.md#time-each-operation-took)).
- `uv run invoke record` with the two available demos, `component-overrides`
  and `backup-restore`: 22 min 15 s. The videos last 0:45 and 1:03.
- `uv run invoke record --demo backup-restore` after a failed run of demo 3:
  20 min 40 s, of which about 5 min 45 s went to deleting the environment the
  failed run kept. The video lasts 1:09.
- `uv run invoke record --demo deploy-upgrade`, measured on 2026-10-20 on a
  fresh demo stack: 8 min 21 s. The video lasts 0:35
  ([spike notes](../../specs/029-recorded-feature-demos/spike-notes.md#demo-1-recorded-tasks-t033-and-t034)).

The setup, which deploys Infrahub and Semaphore and waits for them, and the
waits for the cluster take most of the time. The environment restore of
demo 3 took between 1 min 9 s and 5 min 19 s over five runs, and the cause
of the difference is not known
([spike notes](../../specs/029-recorded-feature-demos/spike-notes.md#real-duration-of-each-wait-1)).
A run with all four demos is not measured. Before any measurement, research
expected 60 to 90 minutes for it
([research R-017](../../specs/029-recorded-feature-demos/research.md#r-017-how-long-a-full-run-takes)).

### Problems seen when recording the demos

- Every demo fails in step `setup` with
  `BrowserType.launch: Executable doesn't exist`: the Chromium build of the
  installed Playwright version is missing. Run
  `uv run playwright install chromium` and record again.
- kr8s prints `UserWarning: Kubernetes version v1.36.0 is not supported`:
  the vCluster runs a Kubernetes version that kr8s 0.20.15 does not list. The
  warning did not affect the runs of 2026-10-18.
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
