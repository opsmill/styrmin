# Research: Recorded Demos of Four Styrmin Features

Research for [plan.md](plan.md), done on 2026-10-17. Sources are linked in each item. "Not verified" marks a fact that comes from reading code or documentation and was not observed in a run.

Two findings change what the spec assumed. They are recorded in the spec's Clarifications (planning session) and Assumptions:

- R-007: the `infrahub` driver cannot take an environment backup, so demos 3 and 4 deploy the `infrahub-enterprise` driver.
- R-013: after a clone, the clone's Semaphore probably still reaches the **source** Infrahub, so demo 4 and the FR-016 check are expected to fail on the current code. The plan puts this check first and stops for a maintainer decision if it fails.

## Third-party dependency evaluation

The research directive asks to extend a dependency, or contribute upstream, before designing around a gap. Each gap found:

| Dependency | Gap | Extension or upstream route | Decision |
| --- | --- | --- | --- |
| Playwright screencast | No pause or resume (R-002) | Upstream request [microsoft/playwright#41178](https://github.com/microsoft/playwright/issues/41178) (MP4 output and pause/resume) was closed as "not planned" on 2026-06-08. The extension point the maintainer named is the `on_frame` callback with your own encoder. | Record continuously and speed up the waits afterwards with ffmpeg, as the PRD decided. `on_frame` with an own encoder is rejected: it moves video encoding into the recorder, and the real duration of a wait is known only when it ends, so the speed-up factor cannot be chosen while frames arrive. |
| ffmpeg | `drawtext` is missing from Homebrew's `ffmpeg` 9.0.2 (R-003) | Homebrew offers `ffmpeg-full`, which is keg-only. Building ffmpeg with libfreetype is the developer's choice, not something to contribute. | Render each label as a PNG with the browser the recorder already runs, and place it with ffmpeg's `overlay` filter, which every build has. |
| Semaphore Helm chart 16.0.11 | No value installs Ansible Galaxy collections (R-009) | Extension points exist: `extraInitContainers`, `extraVolumes`, and Semaphore's own install of `collections/requirements.yml` from the repository before each run. | Keep the PRD's image: demo 2 needs an image that contains the collection, so the image is needed anyway. Both extension routes need Galaxy access from the vCluster at every start or run, and the requirements route writes an MD5 file into the repository directory, which a read-only baked directory refuses. |
| `opsmill.infrahub` 1.9.0 | Requires ansible-core 2.19; the Semaphore 2.16.47 image has 2.18.12 (R-009) | Upstream already ships 1.8.3, which supports ansible-core 2.18. | Pin `opsmill.infrahub` 1.8.3. |
| `opsmill.infrahub` inventory plugin | Requires a token even when Infrahub allows anonymous reads (R-008) | None needed: the plugin reads `INFRAHUB_API_TOKEN`. | Set the token as a secret of the Semaphore environment. |
| Neo4j Community | No online backup, which the `infrahub` driver's backup uses (R-007) | Changing the driver's backup to an offline `neo4j-admin database dump` is a driver and product change, outside this PRD. | Deploy the existing `infrahub-enterprise` driver in demos 3 and 4. |
| Infrahub Helm chart 4.33.2 | Not documented with Infrahub 1.10.x (R-015) | Not a gap to extend; a version choice. | Verify in the first implementation task; the versions file can be changed by hand. |

## R-001: Playwright version and the Screencast API

- **Decision**: Upgrade Playwright from 1.58.0 to 1.64.0 (`playwright>=1.64,<1.65` in the root dev dependency group; today it arrives only through `pytest-playwright-asyncio`). Use:
  - `page.screencast.start(path=..., size={"width": 1920, "height": 1080})` with a browser context whose viewport is 1920×1080, so the frame is not scaled or padded;
  - `page.screencast.show_actions(cursor="pointer", position="top")` for the cursor and the highlight;
  - `page.screencast.show_chapter(title, description=..., duration=2500)` for step titles;
  - `page.screencast.stop()` to write the raw file.
- **Rationale**:
  - The Python package gained `size` and the `cursor` option in 1.61 ([issue #3083](https://github.com/microsoft/playwright-python/issues/3083), [1.61 notes](https://github.com/microsoft/playwright-python/releases/tag/v1.61.0)). 1.64.0 (2026-10-13) keeps the cursor visible across page loads ([1.64 notes](https://github.com/microsoft/playwright-python/releases/tag/v1.64.0)). The page objects navigate with `page.goto` before most actions, so without 1.64 the cursor would disappear after each navigation.
  - `pytest-playwright-asyncio` 0.10.0 sets no upper bound on Playwright ([PyPI](https://pypi.org/project/pytest-playwright-asyncio/)).
  - CI installs the browser with `uv run playwright install chromium` ([`ci.yml`](../../.github/workflows/ci.yml)), which follows the locked package version, so no workflow changes.
- **Facts the recorder relies on** ([Screencast API](https://playwright.dev/python/docs/api/class-screencast), [videoRecorder.ts 1.64](https://github.com/microsoft/playwright/blob/v1.64.0/packages/playwright-core/src/server/videoRecorder.ts)):
  - 1.64 writes WebM with VP9 at 25 frames per second by default. Frame times follow when the browser showed each frame, so cuts must use times, not frame numbers.
  - The video records the page viewport only. A popup is a separate page and is not recorded.
  - `show_chapter` returns after its duration plus a 300 ms fade, so each chapter adds about 2.8 s to the video.
  - `show_actions` holds each action for its `duration` (500 ms by default), which slows the script.
  - The video's time 0 is its first frame, slightly after `start()` returns.
- **Not verified**: whether one screencast keeps recording when the page navigates to another origin (Styrmin to Infrahub to Semaphore). The 1.64 note about the cursor surviving navigations suggests it does. The first recorder task checks it; if it does not, the recorder opens each web application in its own recorded page and joins the files.
- **Alternatives considered**: staying on 1.61 to 1.63 (rejected: the cursor disappears after navigations); recording with `record_video_dir` on the browser context (rejected: no chapters, cursor or highlights).
- **Effect on the E2E suite**: the UI variant runs in a newer Chromium. The E2E UI shards in CI are the check; the PR lists them.

## R-002: Speeding up the waits

- **Decision**: The recorder records the start and end of each wait, in seconds since the screencast started, with `time.monotonic()`. After `stop()`, the post-processor speeds those parts up with ffmpeg.
- **Rationale**: the Screencast API has no pause (R-001, dependency table). The PRD chose post-processing ([ffmpeg setpts](https://ffmpeg.org/ffmpeg-filters.html#setpts_002c-asetpts)).
- **What counts as a wait**: each call that blocks until the cluster or an application reaches a state: a deployment reaching Running, a task, an environment backup, restore or clone reaching a terminal state, a Semaphore task finishing, and Infrahub answering again after a restore. The demo script wraps each such call in `recorder.wait(label)`. The scenario driver's `wait_for_*` methods are the calls wrapped.
- **Alternatives considered**: stopping the screencast during waits and joining the files (rejected: the audience would not see the progress, and the PRD wants the wait visible and labelled).

## R-003: Labels on the sped-up parts

- **Decision**: For each sped-up part, render a PNG label with the recorder's browser (`page.set_content` of a small HTML card, then `locator.screenshot(omit_background=True)`) on a page that is not recorded, and place it with ffmpeg's `overlay` filter during that part.
- **Rationale**: `drawtext` needs ffmpeg built with libfreetype and libharfbuzz. Homebrew's `ffmpeg` 9.0.2 has neither since [PR #261303](https://github.com/Homebrew/homebrew-core/pull/261303) (2026-01-14) ([formula](https://formulae.brew.sh/formula/ffmpeg)); Debian and Ubuntu builds have them ([Debian rules](https://sources.debian.org/src/ffmpeg/7:9.0.2-3/debian/rules/)). The `overlay` filter and the PNG decoder need no optional library. Rendering with the browser uses the same fonts as the chapter titles.
- **Label text**: `Sped up 63×: <label> took 4 min 12 s`. The function that builds it is pure and unit tested.
- **Alternatives considered**: `drawtext` (rejected: missing on macOS with Homebrew); `show_overlay` during the recording (rejected: the real duration and the factor are known only after the wait ends).

## R-004: MP4 settings

- **Decision**: `-c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 30 -movflags +faststart -an`, at 1920×1080.
- **Rationale**: PowerPoint recommends MP4 with H.264 ([Microsoft](https://support.microsoft.com/en-us/office/video-and-audio-file-formats-supported-in-powerpoint-d8b12450-26db-4c7b-a5c1-593d3418fb59)); Keynote plays what QuickTime plays and recommends H.264 ([Apple](https://support.apple.com/guide/keynote/tan12af068f9/mac)); Google Drive plays H.264 MP4 up to 1920×1080 ([Google](https://support.google.com/drive/answer/2423694)). The ffmpeg H.264 guide says `yuv420p` is needed for QuickTime and most players, and gives CRF 17 to 18 as visually lossless ([ffmpeg wiki, archived](https://web.archive.org/web/20261014102325/https://trac.ffmpeg.org/wiki/Encode/H.264)). `+faststart` puts the index first, which Drive streaming uses.
- **Not found**: whether any of the three applications needs an audio track or a given frame rate. SC-003 is checked by opening one video in each application, recorded in the PR.

## R-005: From the waits to the final video

- **Decision**: A pure function `plan_segments(waits, cuts, raw_duration, *, min_wait=6.0, target=4.0)` returns the segments of the final video (see [data-model.md](data-model.md), Segment):
  - A wait shorter than `min_wait` seconds stays at normal speed.
  - A longer wait becomes one segment with `factor = ceil(duration / target)`, so it lasts at most `target` seconds in the video, and a label.
  - A cut (R-016) becomes a `cut` segment, which the ffmpeg arguments leave out.
  - The parts between waits and cuts are segments with factor 1.
  - The function rejects overlapping or out-of-order waits and cuts and waits outside `[0, raw_duration]`, and clips a wait whose end is slightly past the raw duration.
- A second pure function builds the ffmpeg arguments from the segments and the label files. Each segment is its own input, cut with input seeking (`-ss start -to end -i raw.webm`), so ffmpeg does not keep every frame of the file in memory for later branches. Each input gets `setpts=(PTS-STARTPTS)/factor`, a sped-up input gets its label with `overlay=(W-w)/2:H-h-64`, and all inputs are joined with `concat=n=K:v=1:a=0`, then `fps=30,format=yuv420p`.
- **Rationale**: `trim` and input seeking keep the original time stamps, and `concat` needs each part to start at 0, which `setpts=PTS-STARTPTS` gives ([trim](https://ffmpeg.org/ffmpeg-filters.html#trim), [concat](https://ffmpeg.org/ffmpeg-filters.html#concat)). Parts sped up by different factors have different frame rates, and `fps=30` after `concat` gives a constant rate.
- **Video length**: the planned length is the sum of the segments' lengths. With 4-second waits, a demo's length is about its active time (clicks, typing, chapters) plus 4 seconds for each wait. The recorder warns when the planned length passes 180 seconds (SC-002); the fix is in the demo script (fewer or shorter steps), not a larger factor.
- **Unit tests** (the only unit tests the PRD asks for): segments cover the video with no gap; short waits are not sped up; factor and length of a long wait; label text; a cut is left out; rejection of overlapping waits and cuts; clipping at the end; the ffmpeg arguments for a plan with one sped-up part and one cut.

## R-006: Typing one key at a time

- **Decision**:
  - Add `enter_text(locator, text, *, keystroke_delay_ms)` to [`pages/_dom.py`](../../backend/tests/e2e/pages/_dom.py). With no delay it calls `locator.fill(text)`, as today. With a delay it calls `locator.fill("")` and then `locator.press_sequentially(text, delay=keystroke_delay_ms)`; an empty `text` only clears the field.
  - Each page object constructor gains a keyword argument `keystroke_delay_ms: int | None = None`. Each `.fill(` call in the page objects becomes `enter_text(...)`, 66 calls in nine files.
  - `UiScenarioDriver(page=..., base_url=..., keystroke_delay_ms=None)` passes the value to every page object it creates. The E2E fixtures keep the default, so the E2E suite keeps filling fields in one step (FR-004).
  - The demos use 45 ms per key.
- **Rationale**: `Locator.press_sequentially` is the documented way to type key by key; `Locator.type` is deprecated ([locator docs](https://playwright.dev/python/docs/api/class-locator#locator-press-sequentially)). Clearing first keeps `fill`'s replace semantics. The setting is chosen when a page object is created, as the PRD says.
- **Risk**: a field that reacts to each key (a combobox filter, an input that re-renders while typing) can behave differently with keys than with `fill`. The `wait_for_dialog_open` rule (#365) applies to both. Each demo run exercises the typed path; the E2E suite does not, by design.
- **Alternatives considered**: a module-level switch (rejected: global state shared by the E2E session); typing in the demo scripts (rejected: needs selectors in the demo scripts, against FR-003).

## R-007: Environment backups need the `infrahub-enterprise` driver

- **Finding**: the `neo4j` backup kind runs `neo4j-admin database backup` ([`velero/hooks.py`](../../backend/styrmin_backend/agent/service/kubernetes/velero/hooks.py), `neo4j_backup_hooks`). Online backup is a Neo4j Enterprise feature. The `infrahub` driver deploys the community chart, and its backup E2E test is skipped with the reason "backup/restore not supported with community" ([`test_infrahub_backup_restore.py`](../../backend/tests/e2e/test_infrahub_backup_restore.py)). The `infrahub-enterprise` driver's chart sets `neo4j.edition: enterprise` and `acceptLicenseAgreement: "yes"` (chart 4.19.2, `helm show values`), and its backup test runs in CI (`test_infrahub_enterprise_backup_and_restore_lifecycle`).
- **Decision**: demos 3 and 4 deploy the `infrahub-enterprise` driver. Their setup loads it with `client.drivers.load_local_version("/styrmin/drivers/infrahub-enterprise")`; the Styrmin image already contains every example driver under `/styrmin/drivers` ([`docker/Dockerfile`](../../docker/Dockerfile)). Demos 1 and 2 deploy the `infrahub` driver, as the PRD says.
- **Rationale**: both drivers define the same `infrahub` service on port 8000 and the same components, so the demos and FR-013 do not change. Chart 4.19.2 has `appVersion: 1.11.2`, the same minor version as 1.11.7.
- **Not verified**: that chart 4.19.2 runs Infrahub 1.11.7. The first implementation task checks it (plan, Phase 2).
- **Alternatives considered**: changing the `infrahub` driver to back up Neo4j with an offline dump (rejected: a driver and product change outside the PRD, with a stop of the database during each backup).

## R-008: Devices in Infrahub and the inventory

- **Schema** (spec Clarifications), kept in `backend/tests/e2e/demos/infrahub/schema.yml`: namespace `Infra`, node `Device`, label "Network device", `display_label: "{{ name__value }}"`, `human_friendly_id: ["name__value"]`, one unique `Text` attribute `name`. `Infra` is not a restricted namespace in 1.11.7 ([constants](https://github.com/opsmill/infrahub/blob/infrahub-v1.11.7/backend/infrahub/core/constants/__init__.py)). Nodes without `menu_placement` appear in the menu under "Other" ([menu docs](https://docs.infrahub.app/menu/overview)).
- **Loading**: the setup uses `infrahub-sdk` (already in the dev group) with the token below: `client.schema.load(schemas=[...], wait_until_converged=True)`, checking `response.errors`, then `client.create(kind="InfraDevice", name=...).save()`.
- **Token**: Infrahub charts 4.33.2 and 4.19.2 preset `INFRAHUB_INITIAL_ADMIN_TOKEN: 06438eb2-8019-4776-878c-0941b1f1d1ec`; the E2E tests use the same value. The inventory plugin requires a token ([inventory.py 1.9.0](https://github.com/opsmill/infrahub-ansible/blob/1.9.0/plugins/inventory/inventory.py)), so the Semaphore environment sets it as the secret `INFRAHUB_API_TOKEN`. A cloned Infrahub keeps the token, because the token lives in its restored database.
- **Inventory file** `inventory/infrahub.yml` in the image: `plugin: opsmill.infrahub.inventory`, `api_endpoint: http://infrahub:8000`, `hostnames: [name]`, `nodes: {InfraDevice: {include: [name]}}`. The address names Infrahub's service by its short name only (FR-013).
- **Playbook** `list_hosts.yml`: `hosts: all`, `gather_facts: false`, `connection: local`, one `debug` task that prints the sorted `groups['all']` and its length, so the output reads `"Devices in the inventory: 2"` and lists `sw1`, `sw2`. No task connects to a device.
- **Web UI** (1.10 and 1.11 are the same): list `/objects/InfraDevice` (`data-testid="object-items"`); add with the "Add Network device" button (`create-object-button`), a side panel and "Save"; delete from the row menu (`actions-cell-<label>`) or the details menu (`object-details-menu`), confirmed with `modal-delete-confirm`. Login at `/login` with `admin` and `infrahub`.

## R-009: The demo Semaphore image

- **Decision**: `backend/tests/e2e/demos/semaphore/Dockerfile`, verified by the research build on 2026-10-17:

  ```dockerfile
  FROM semaphoreui/semaphore:v2.16.47
  USER root
  RUN mkdir -p /usr/share/ansible/collections \
   && ansible-galaxy collection install 'opsmill.infrahub:==1.8.3' -p /usr/share/ansible/collections \
   && chown -R 1001:0 /usr/share/ansible
  COPY --chown=1001:0 ansible /opt/demo/ansible
  USER 1001
  RUN pip install --no-cache-dir 'infrahub-sdk>=1.19,<2'
  ```

- The image is tagged `styrmin-demo/semaphore:v2.16.47`. The tag matches the chart's `image.tag: "v{{ app.version }}"` in the `semaphore` driver's values, so setting the driver parameter `docker_image` to `styrmin-demo/semaphore` selects it ([`values.j2.yml`](../../driver/examples/semaphore/values.j2.yml)). The driver's `pullPolicy: IfNotPresent` lets the vCluster use the local image, as `uv run invoke start` does for the Styrmin image ([`helm/styrmin/README.md`](../../helm/styrmin/README.md), "Running against a locally-built image").
- **Facts** (Semaphore v2.16.47 source, [Dockerfile](https://github.com/semaphoreui/semaphore/blob/v2.16.47/deployment/docker/server/Dockerfile)):
  - The image runs as uid 1001 on Alpine with Ansible in `/opt/semaphore/apps/ansible/11.1.0/venv` (ansible-core 2.18.12, Python 3.12).
  - Semaphore runs `ansible-playbook` with `HOME=/tmp/semaphore/project_<id>`, so a collection under `~/.ansible` is not found; `/usr/share/ansible/collections` is.
  - `opsmill.infrahub` 1.9.0 requires ansible-core 2.19, 1.8.3 requires 2.18 ([Galaxy](https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/index/opsmill/infrahub/versions/)).
  - The driver's values already ask the chart to `pip install infrahub-sdk` at each start (`general.additionalPythonPackages`), which needs PyPI access from the vCluster. That is the driver's existing behaviour and does not change.
- **Demo 2** sets the image override of the Semaphore `server` component to `styrmin-demo/semaphore:v2.16.47`. **Demo 4** deploys Semaphore with `docker_image: styrmin-demo/semaphore` in its setup, because its playbook needs the collection.
- **Build**: `tasks/demo.py` builds the image when it is missing, as `start` does for the Styrmin image, and rebuilds it with `--build-image`.

## R-010: Semaphore setup through its API

The setup uses `httpx` against the Semaphore URL from the deployment's `humanReadableUrl` ([`get_deployment.graphql`](../../python_sdk/src/styrmin_sdk/graphql/get_deployment.graphql)), logged in as `admin` with `admin-password` from the driver's values. From the v2.16.47 source ([api/router.go](https://github.com/semaphoreui/semaphore/blob/v2.16.47/api/router.go)):

1. `POST /api/auth/login` `{"auth": "admin", "password": "admin-password"}` sets the `semaphore` cookie.
2. `POST /api/projects` `{"name": "Network lab"}`. It also creates a key named "None" of type `none`; the setup reads it from `GET /api/project/{pid}/keys`.
3. `POST /api/project/{pid}/repositories` with `git_url: "/opt/demo/ansible"`, `git_branch: ""` and the "None" key. A path starting with `/` is a local repository: Semaphore runs the playbook in it without cloning ([Repository.go](https://github.com/semaphoreui/semaphore/blob/v2.16.47/db/Repository.go)).
4. `POST /api/project/{pid}/inventory` with `type: "file"`, `inventory: "inventory/infrahub.yml"` and the repository id.
5. `POST /api/project/{pid}/environment` with `json: "{}"`, `env: "{}"` and the secret `{"type": "env", "name": "INFRAHUB_API_TOKEN", "secret": "<token>", "operation": "create"}`. `json` and `env` are strings that contain JSON.
6. `POST /api/project/{pid}/templates` with `app: "ansible"`, `name: "List network devices"`, `playbook: "list_hosts.yml"` and the three ids.

Quirks to handle: every body carries `project_id`; `AddRepository`, `AddEnvironment` and `AddTemplate` can create the record and still answer 400 when a field is wrong, so the setup checks the status and the created object. The setup runs no task; demos run tasks in the web UI.

## R-011: Page objects for Infrahub and Semaphore

- **Location**: `backend/tests/e2e/demos/pages/infrahub.py` and `.../pages/semaphore.py`, used by the demos only (FR-014). They follow the E2E page objects: constructor `(page, *, keystroke_delay_ms=None)`, `enter_text` from `_dom.py`, and a deterministic end signal for each action.
- **Infrahub** (`InfrahubDevicesPage`): `goto(base_url)`, `list_device_names()`, `add_device(name)` (ends when the row appears), `delete_device(name)` (ends when the row disappears). Selectors from R-008.
- **Semaphore** (`SemaphoreTemplatesPage`): `goto_template(base_url, project, template)`, `run()` (clicks "Run" in the header and in the "New Task" dialog), `wait_for_output(timeout)` (waits until the task log shows a finished state and returns the log text), `delete_template()` (trash icon, "Delete template" dialog), `template_names()`. The Semaphore UI is Vuetify without test ids, so locators use roles and labels ([TemplateView.vue](https://github.com/semaphoreui/semaphore/blob/v2.16.47/web/src/views/project/TemplateView.vue), [TaskLogView.vue](https://github.com/semaphoreui/semaphore/blob/v2.16.47/web/src/components/TaskLogView.vue)).
- **Not verified**: exact Vuetify labels; the first Semaphore task writes the locators against the running demo stack.

## R-012: Where the recorder lives and how it runs

- **Decision**: a package `backend/tests/e2e/demos/`, run as `python -m tests.e2e.demos` from `backend/` by a new invoke task `record` in [`tasks/demo.py`](../../tasks/demo.py).
- **Rationale**:
  - The demos import `tests.e2e.pages` and `tests.e2e.drivers`. `tests` is importable from `backend/`, which is how `uv run invoke test` runs pytest ([`tasks/__init__.py`](../../tasks/__init__.py)). `ty` already has `extra-paths = ["backend"]`.
  - pytest collects only `test_*.py`, so the demo modules are not collected by the E2E suite.
  - The ty and ruff overrides for `backend/tests/**` apply.
- **Unit tests** for the post-processor live in `backend/tests/unit/demos/`, which the CI unit job runs. The planning module imports nothing from Playwright.
- **Alternatives considered**: a top-level `demos/` directory (rejected: needs `backend` added to `sys.path` at run time); `tasks/demos/` (rejected: same, and invoke would import Playwright when it loads its tasks).

## R-013: A clone's alias Services point to the source

- **Finding** (code reading, not verified in a run):
  - A deployment's backup includes its whole namespace (`included_namespaces=[target_namespace]`), so it includes the `ExternalName` alias Services that point to the other deployments' namespaces ([`builders/backup.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py)).
  - A cross-target restore maps the namespace but keeps each object's content, including `spec.externalName`, and uses `existing_resource_policy="update"` ([`workflows/templates/backup.py`](../../backend/styrmin_backend/workflows/templates/backup.py)).
  - Counterparts are created with their initial reconcile deferred ([ADR-056](../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md)). Cross-target recovery re-applies prerequisites, the HelmRelease and the operator's services phase, which applies the deployment's own Services, not the aliases ([`restore_recovery.py`](../../backend/styrmin_backend/operator/restore_recovery.py), [`pipeline.py`](../../backend/styrmin_backend/operator/pipeline.py)). Aliases are written only by the Prefect create, update and upgrade flows ([`service_aliases.py`](../../backend/styrmin_backend/agent/tasks/service_aliases.py)).
  - So after a clone, the clone Semaphore's `infrahub` alias most likely still points to `infrahub.styrmin-<source Infrahub id>.svc`, and the clone's Semaphore would list the source's two devices. In `test_environment_clone_lifecycle`, the counterpart's namespace would keep the source's aliases of the other deployments of the shared environment.
- **Consequences**:
  - The FR-016 check is expected to fail on the current code, and demo 4 to show two devices instead of three. The docs' statement that applications in a clone reach each other in the clone ([`ingress-and-networking.md`](../../docs/docs/concepts-and-architecture/ingress-and-networking.md#networking-between-applications)) would then be wrong.
  - Fixing it changes the agent's restore or clone flow, which the PRD keeps out of scope ("API or interface surface: none", "§I to §IV: no product code changes").
- **Decision**: the first implementation task adds the FR-016 check and runs it. If it passes, the plan continues. If it fails, the implementer files a bug issue with the evidence and stops for a maintainer decision between: fixing the product first in its own change, or landing the check marked `xfail(strict=True)` with the issue link and recording demo 4 after the fix. The plan does not decide this, because it is a product change the PRD does not cover.
- **Check design**: after the first clone completes, list the Services labelled `styrmin.io/service-alias=true` in the counterpart's namespace and assert that the namespace part of each `spec.externalName` is a namespace of a deployment of the clone. It is read-only and adds no deployment (Constitution §V, "reuse before you boot").

## R-014: Names, leftovers and deleting environments

- **Names**: each demo has its own environment names ([data-model.md](data-model.md)), so a failed demo's kept environment never collides with another demo's cleanup.
- **Leftovers** (FR-009): before its setup, a demo looks up each of its names on the `local` cluster with `client.environments.get(environment_name=..., cluster_name="local")` and deletes the ones found, the clone first.
- **Deletion**: `client.environments.delete` deletes the environment row at once and asks each deployment to tear down; the operator then deletes each namespace `styrmin-<deployment id>` ([`services/environments.py`](../../backend/styrmin_backend/services/environments.py), `delete_environment`). The demo reads the deployment ids before the delete, then waits up to 10 minutes for those namespaces to disappear, with `kr8s` and the current kubeconfig, so the next demo does not start while Infrahub pods still use memory.
- **Kept environments** (FR-010): a failed demo skips the deletion and lists its environments in the summary.

## R-015: Infrahub versions for demo 1

- **Facts**: chart 4.33.2 has `appVersion: 1.11.2` and Neo4j `2026.05.0`. `global.infrahubTag` changes only the server and task-worker images; the `infrahub` driver also sets the Prefect tag to the application version ([`values.j2.yml`](../../driver/examples/infrahub/values.j2.yml)). Infrahub 1.10.x was released with chart 4.32.3 and Neo4j `2025.10.1`, and no document says 1.10.x runs on chart 4.33.2. The latest releases are 1.11.7 (2026-10-14) and 1.10.11 (2026-10-01) ([releases](https://github.com/opsmill/infrahub/releases)).
- **Decision**: the versions file starts with `previous: "1.10.11"` and `latest: "1.11.7"`. The upgrade from 1.10 to 1.11 runs the driver's upgrade action with Infrahub's migrations, which is what demo 1 shows.
- **Verification**: the first demo task deploys `previous` on the demo stack and upgrades it to `latest` through the SDK. If 1.10.11 does not start on chart 4.33.2, the implementer sets `previous` to the newest 1.11 release below `latest` and records why in the PR.

## R-016: Logging in without recording it

- **Decision**:
  - Before the screencast starts, the recorder logs in to Styrmin with `LoginPage` on the page it will record.
  - Logins to Infrahub and Semaphore happen on a second page of the same browser context, which is not recorded. Cookies and `localStorage` are per origin and shared by the pages of a context, so the recorded page is logged in too.
  - For applications that exist only after a recorded step (the clone's Infrahub and Semaphore in demo 4), the recorder marks the time spent on the second page as a part to cut from the video: a segment with no output. `plan_segments` accepts such cut ranges next to the waits.
- **Rationale**: the login forms are not part of any demo, and they would add about 10 seconds to each video.

## R-017: How long a full run takes

Not a requirement, recorded for the guide. Each setup of demos 2 to 4 deploys Infrahub and Semaphore and waits for them (the E2E suite allows 600 seconds for Infrahub, [`conftest.py`](../../backend/tests/e2e/conftest.py)). Demo 3 waits for a backup and a restore, and demo 4 for a clone of two deployments. A full run of the four demos is expected to take between 60 and 90 minutes. Not measured.
