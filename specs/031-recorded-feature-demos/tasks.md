---
description: "Task list for the recorded demos of four Styrmin features"
---

# Tasks: Recorded Demos of Four Styrmin Features

**Input**: Design documents from `specs/031-recorded-feature-demos/`: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/record-command.md](contracts/record-command.md), [quickstart.md](quickstart.md), [critique](critiques/critique-20261017.md)

**Tests**: The PRD asks for unit tests of the post-processor only, plus the read-only FR-016 E2E check. The demo scripts have no E2E test (approved exception); one full run on a fresh demo stack is their proof. One extra unit test guards FR-004 (the E2E suite keeps `fill`).

**Organization**: Phase 2 holds everything the four demos share, including the checks that research expects to fail. Phases 3 to 6 add one demo each and can be done in any order after Phase 2. Phases 7 and 8 check the command across demos.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US6 (spec user stories)
- Paths are relative to the repository root. `demos/` below means `backend/tests/e2e/demos/`.

## E2E run rules (apply to T006 and T007)

- Build the server image once before the first session: `docker compose build server`.
- One CI shard per pytest session, and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |` and stop the run by PID, not with `pkill -f`.
- Record each passing run in `specs/031-recorded-feature-demos/e2e-evidence.md`: the pytest node ID, the exact command, ISO 8601 start and end times, the vcluster name and kubeconfig path, and the verbatim `PASSED` line (Constitution §V).

## Demo stack rules (apply to every task that records or runs a demo)

- Start from `uv run invoke start` (or `uv run invoke reset` for a fresh stack). `kubectl` must point at the demo vCluster (`vcluster connect styrmin --driver=docker`).
- `ffmpeg` on the PATH. On a Linux host without it: `apt-get install -y ffmpeg`.
- Never record secrets in a step title, a label or a log line.

---

## Phase 1: Setup

**Purpose**: dependencies, the package skeleton, and a green baseline.

- [X] T001 Run `uv sync` and `uv run pytest backend/tests/unit -q -x --ignore=backend/tests/unit/cli` and note the result as the baseline (no file change). Check that `docker`, `vcluster`, `helm`, `kubectl` and `ffmpeg` are on the PATH; install ffmpeg if it is missing
- [X] T002 Upgrade Playwright (research R-001): add `"playwright>=1.64,<1.65",` to the `dev` dependency group in `pyproject.toml`, run `uv lock --upgrade-package playwright` so `uv.lock` pins 1.64.x, then `uv sync` and `uv run playwright install chromium`. Check that `uv run python -c "import playwright; from playwright.async_api import Page; print(Page.screencast)"` works
- [X] T003 [P] Add `demo-videos/` under the "Local demo runtime state" comment in `.gitignore`
- [X] T004 [P] Create the package skeleton with empty modules that only hold a one-line docstring: `backend/tests/e2e/demos/__init__.py`, `demos/pages/__init__.py`, `demos/scenarios/__init__.py`, and `backend/tests/unit/demos/__init__.py`

---

## Phase 2: Foundational (blocks every story)

### 2a. Checks first (research R-001, R-007, R-013, R-015)

**Purpose**: find out early what research expects to fail. T008 decides whether US4 can go on.

- [X] T005 *(Dropped on 2026-10-20: commit `472fe403`, which held this check, was removed from the branch, because PR #531 adds its own alias check to the same test. FR-016 is dropped.)* Add the FR-016 alias check to `test_environment_clone_lifecycle` in `backend/tests/e2e/test_backup_restore.py` (research R-013): right after the first clone reaches its terminal status and `counterpart_deployment_id` is known (step 6), list with `kr8s` (as `portforward_simple_app` does, with `vcluster["kubeconfig_path"]`) the Services labelled `styrmin.io/service-alias=true` in namespace `styrmin-<counterpart_deployment_id>`. For each, take the namespace part of `spec.externalName` (`<name>.<namespace>.svc.<domain>`) and assert it is in the set of namespaces of the clone's deployments (`styrmin-<counterpart_deployment_id>` and `styrmin-<id>` of every deployment `client.deployments.list` returns for the created environment). The assertion message lists each offending alias name and its `externalName`. Add a comment of at most three lines: the check proves no alias points to the source; demo 4 proves the positive case (critique E5). Do not add a deployment or a new test node
- [X] T006 *(Dropped on 2026-10-20: commit `472fe403`, which held this check, was removed from the branch, because PR #531 adds its own alias check to the same test. FR-016 is dropped.)* Run `test_environment_clone_lifecycle[api-chromium]` with `-m "ci and shard_env_backup"` following the E2E run rules, and record the result in `specs/031-recorded-feature-demos/e2e-evidence.md` (PASSED evidence, or the failure output with the offending aliases)
- [X] T007 *(Dropped on 2026-10-20: commit `472fe403`, which held this check, was removed from the branch, because PR #531 adds its own alias check to the same test. FR-016 is dropped.)* Run `test_environment_clone_lifecycle[ui-chromium]` in its own session the same way, and record the result in `specs/031-recorded-feature-demos/e2e-evidence.md`
- [X] T008 If T006 or T007 fails on the alias assertion: create a GitHub issue with the `create-issue` skill ("a clone keeps the source's service aliases"), citing research R-013, the failure output, and the docs statement in `docs/docs/concepts-and-architecture/ingress-and-networking.md` that the defect contradicts. Stop and ask the maintainer how the product fix will be made. Keep T005 on the branch uncommitted or in a separate commit that is not pushed until the check passes; do not mark it `xfail` (critique X1). Phases 3, 4, 5, 7 (for demos 1 to 3), 8 and 9 go on; Phase 6 waits for the fix. Record the decision in `specs/031-recorded-feature-demos/e2e-evidence.md`. If both runs pass, write "alias check passed; no issue needed" there and go on
- [X] T009 Verify the deployments the demos rely on, on a fresh demo stack (`uv run invoke reset`), with a throwaway script in the session scratchpad (not committed) that uses `StyrminClient` with the admin credentials from `dev/local/demo-values.yaml`:
  - create environment `spike-upgrade` on cluster `local`, deploy `infrahub` at `1.10.11`, wait for Running (up to 900 s), upgrade to `1.11.7` with `client.deployments.update_version`, wait for Running (research R-015);
  - `client.drivers.load_local_version("/styrmin/drivers/infrahub-enterprise")`, create environment `spike-backup`, assign the stack's backup storage location (`client.backup_storage_locations.list()` then `assign`), deploy `infrahub-enterprise` at `1.11.7`, wait for Running, take an environment backup and restore it with `client.environment_backups`, wait for both to complete (research R-007);
  - delete both environments.

  Write the outcome to `specs/031-recorded-feature-demos/spike-notes.md`. If 1.10.11 does not start on chart 4.33.2, try the newest 1.11 release below 1.11.7 and note which version demo 1 will use. If `infrahub-enterprise` 1.11.7 does not start or its backup fails, stop and report it to the maintainer, because demos 3 and 4 depend on it
- [X] T010 Verify the screencast (research R-001) with a throwaway script in the scratchpad: open a 1920×1080 page on the demo stack's Styrmin URL, `screencast.start(path=..., size=...)`, `show_actions(cursor="pointer")`, `show_chapter("Test", duration=1500)`, navigate to the `spike-upgrade` Infrahub URL (another origin) before T009 deletes it or to any other `*.local.styrmin.io` page, click once, `stop()`. Check with `ffprobe` that the file lasts the whole run and look at its last frames to confirm the second origin was recorded. Note the result in `specs/031-recorded-feature-demos/spike-notes.md`; if the recording stops at the navigation, note that the recorder must open one recorded page per web application and join the files (R-001 fallback), and apply that in T019
- [X] T011 Run `test_ui_smoke.py` in the `ui-chromium` variant locally after the Playwright upgrade (E2E run rules, `-m "ci and shard_general"` filtered to that file) and record the result in `specs/031-recorded-feature-demos/e2e-evidence.md`

### 2b. Typing one key at a time in the page objects (research R-006, FR-004)

- [X] T012 Add `async def enter_text(locator: Locator, text: str, *, keystroke_delay_ms: int | None) -> None` to `backend/tests/e2e/pages/_dom.py`: with `keystroke_delay_ms is None` it calls `await locator.fill(text)` and nothing else; otherwise it calls `await locator.fill("")` and, when `text` is not empty, `await locator.press_sequentially(text, delay=keystroke_delay_ms)`. Docstring of at most three lines
- [X] T013 [P] Create `backend/tests/unit/test_e2e_page_typing.py` with a fake locator that records calls, and check: `enter_text(..., keystroke_delay_ms=None)` calls only `fill(text)`; with a delay it calls `fill("")` then `press_sequentially(text, delay=...)`; with a delay and an empty text it calls only `fill("")`
- [X] T014 Give every page-object class a keyword-only constructor argument `keystroke_delay_ms: int | None = None` stored as `self._keystroke_delay_ms`, and replace every `.fill(<value>)` call with `await enter_text(<locator>, <value>, keystroke_delay_ms=self._keystroke_delay_ms)`, in `backend/tests/e2e/pages/cluster_detail.py`, `deploy_form.py`, `deployment_detail.py`, `drivers_list.py`, `environments.py`, `groups_admin.py`, `login.py`, `pods_tab.py`, `settings.py` and `users_admin.py` (66 calls today; `grep -n "\.fill(" backend/tests/e2e/pages/*.py` must print nothing afterwards except inside `_dom.py`). A page object that creates another page object passes the value on (critique E2)
- [X] T015 In `backend/tests/e2e/drivers/ui_driver.py` add `keystroke_delay_ms: int | None = None` as a keyword-only argument of `UiScenarioDriver.__init__` and pass it to every page object it creates. Do not change the two call sites in `backend/tests/e2e/conftest.py`, so the E2E suite keeps `None`
- [X] T016 Add to `DeploymentDetailPage` in `backend/tests/e2e/pages/deployment_detail.py` (plan Design, critique E1):
  - `open_timeline()`: clicks the "Timeline" tab button and waits for an entry or the "No operations" placeholder, as `read_timeline` does (refactor `read_timeline` to call it);
  - `read_task_ids() -> set[str]`: the `data-task-id` of every `[data-testid=timeline-entry]`, after `open_timeline()`;
  - `wait_for_new_task(task_type: str, *, known_task_ids: set[str], timeout: float) -> str`: polls the timeline until an entry with `data-task-type == task_type` whose id is not in `known_task_ids` has `data-task-result` `succeeded`, and returns its id. It raises `ScenarioActionError` naming the task id when the result is `failed`, and `ScenarioTimeout` after `timeout` seconds. Task types and results are the values of `TaskType` and `TaskResult` in `backend/styrmin_backend/domain/models.py` (`upgrade_instance`, `update_instance`; `running`, `failed`, `succeeded`, `superseded`)

### 2c. The post-processor (research R-002 to R-005, R-016)

- [X] T017 [P] Write `backend/tests/unit/demos/test_video.py` first, against the API of T018: segments cover `[0, raw_duration]` with no gap or overlap; a wait shorter than `min_wait` stays `normal`; a 252 s wait with `target=4.0` gives one `sped_up` segment with factor 63 that lasts 4 s; `label_text` gives `"Sped up 63×: Backup in progress took 4 min 12 s"`; a cut gives a `cut` segment that `planned_length` leaves out; overlapping waits, a wait overlapping a cut, and waits out of order raise `ValueError`; a wait ending up to 1 s after `raw_duration` is clipped; `ffmpeg_arguments` for a plan with one normal, one sped-up and one cut segment has one `-ss/-to/-i` input per kept segment plus one label input, a filter graph with `setpts=(PTS-STARTPTS)/63`, `overlay=(W-w)/2:H-h-64`, `concat=n=2:v=1:a=0`, `fps=30,format=yuv420p`, and the output options of research R-004
- [X] T018 Create `demos/video.py` with no Playwright import: frozen dataclasses `Wait(label, start, end)`, `Cut(start, end)` and `Segment(start, end, kind, factor, label)` as in `data-model.md`; `plan_segments(waits, cuts, raw_duration, *, min_wait=6.0, target=4.0) -> list[Segment]`; `format_duration(seconds) -> str` (`"4 min 12 s"`, `"38 s"`); `label_text(label, real_seconds, factor) -> str`; `planned_length(segments) -> float`; `ffmpeg_arguments(raw_path, segments, label_paths, output_path) -> list[str]` (label paths given in the order of the `sped_up` segments). Make T017 pass with `uv run pytest backend/tests/unit/demos -q`
- [X] T019 Create `demos/encode.py`: `async render_label(context: BrowserContext, text: str, path: Path) -> None` (opens a page that is not recorded, `set_content` with a dark rounded card in the system-ui font at 30 px, `locator.screenshot(path=..., omit_background=True)`, closes the page); `run_ffmpeg(arguments: list[str]) -> None` (subprocess, raises with the last 20 lines of stderr on failure); `async encode_video(context, raw_path, segments, output_path, work_dir) -> None` that renders one label per sped-up segment, runs ffmpeg to a temporary file in `work_dir`, and moves it to `output_path` only when ffmpeg succeeds

### 2d. The recorder and the stack helpers

- [X] T020 Create `demos/recorder.py` with class `DemoRecorder` (data-model Step, Wait, Cut; research R-001, R-016; FR-004, FR-005, FR-010):
  - `async start(page, raw_path)`: `page.screencast.start(path=raw_path, size={"width": 1920, "height": 1080})`, `show_actions(cursor="pointer", position="top")`, and `t0 = time.monotonic()`;
  - `step(title)` async context manager: prints the title, calls `show_chapter(title, duration=2500)`, and keeps the current title so a failure names it;
  - `wait(label)` async context manager: records a `Wait` from `time.monotonic() - t0` at entry and exit, and prints the label and the real duration;
  - `unrecorded()` async context manager: yields a new page of the same context and records a `Cut` for its lifetime;
  - `async stop() -> tuple[list[Wait], list[Cut], float]`: stops the screencast and returns the waits, the cuts and the raw duration from `ffprobe`;
  - `current_step` property for failure reports.
- [X] T021 Create `demos/stack.py` with the SDK helpers (research R-014; FR-002, FR-008, FR-009): `async connect(api_url, username, password) -> StyrminClient`; `async delete_environments(client, names, *, timeout=600)` (deletes each existing environment of `names` on cluster `local`, in the given order, after reading its deployment ids, then waits with `kr8s` until every namespace `styrmin-<deployment id>` is gone); `async create_environment(client, name) -> str` (cluster `local`, `config={}`, then assigns the backup storage location that `uv run invoke start` created); `async load_enterprise_driver(client)` (`load_local_version("/styrmin/drivers/infrahub-enterprise")`, tolerating an already-loaded version); `async deploy(client, *, environment_id, driver, version, name, parameters=None, timeout=900) -> GetDeploymentDeployment` (creates and waits for Running, returns the deployment with its `deployedServices`); `service_url(deployment, service_name) -> str` (the `humanReadableUrl`)
- [X] T022 [P] Create `demos/infrahub/schema.yml` (research R-008: namespace `Infra`, node `Device`, label "Network device", `icon: mdi:router-network`, `display_label: "{{ name__value }}"`, `human_friendly_id: ["name__value"]`, unique `Text` attribute `name`) and `demos/infrahub_setup.py`: `INFRAHUB_TOKEN = "06438eb2-8019-4776-878c-0941b1f1d1ec"` with a comment that both Infrahub charts preset it; `async load_devices(url, names)` that loads the schema with `wait_until_converged=True`, raises when `response.errors` is not empty, and creates one `InfraDevice` per name; `async wait_until_ready(url, timeout)` that polls `GET /api/schema/summary` until it answers 200
- [X] T023 [P] Create the demo Semaphore image (research R-009; FR-015): `demos/semaphore/Dockerfile` as in R-009 (pin `opsmill.infrahub` 1.8.3, `/usr/share/ansible/collections`, `infrahub-sdk>=1.19,<2`, playbook copied to `/opt/demo/ansible`); `demos/semaphore/ansible/list_hosts.yml` (`hosts: all`, `gather_facts: false`, `connection: local`, one `ansible.builtin.debug` task with `run_once: true` printing `"Devices in the inventory: {{ groups['all'] | length }}"` and the sorted host list); `demos/semaphore/ansible/inventory/infrahub.yml` (`plugin: opsmill.infrahub.inventory`, `api_endpoint: http://infrahub:8000`, `hostnames: [name]`, `nodes: {InfraDevice: {include: [name]}}`, no token: it comes from `INFRAHUB_API_TOKEN`)
- [X] T024 [P] Create `demos/semaphore_setup.py` (research R-010): `async configure(url, *, infrahub_token) -> SemaphoreProject` that logs in as `admin`/`admin-password` (the `semaphore` driver's values), creates the project "Network lab", reads its "None" key, and creates the repository (`/opt/demo/ansible`), the `file` inventory (`inventory/infrahub.yml`), the environment with the `INFRAHUB_API_TOKEN` secret, and the template "List network devices" (`app: "ansible"`, `playbook: "list_hosts.yml"`). Every body carries `project_id`; check each status code and each created object, because some endpoints create the record and still answer 400. Return the project, template and environment ids
- [X] T025 [P] Create `demos/pages/infrahub.py` with `InfrahubDevicesPage(page, *, keystroke_delay_ms=None)` (FR-014, research R-008, R-011): `goto(base_url)` (`/objects/InfraDevice`, waits for `[data-testid=object-items]`); `list_device_names() -> list[str]`; `add_device(name)` ("Add Network device" via `create-object-button`, `enter_text` into the Name field, "Save", ends when the row appears); `delete_device(name)` (row menu `actions-cell-<name>` or details menu `object-details-menu`, "Delete", `modal-delete-confirm`, ends when the row disappears). Write the locators against a running Infrahub 1.11.7 from T009 or the demo setup, using the Playwright MCP server if it is connected
- [X] T026 [P] Create `demos/pages/semaphore.py` with `SemaphoreTemplatesPage(page, *, keystroke_delay_ms=None)` (FR-014, research R-011): `goto_template(base_url, project_id, template_id)`; `run() -> None` (header "Run" button, then "Run" in the "New Task" dialog); `wait_for_output(timeout) -> str` (waits until the task log dialog shows a finished state and returns the log text without ANSI codes; raises on a failed task); `close_output()`; `delete_template()` (trash icon, "Delete template" dialog); `template_names(base_url, project_id) -> list[str]`. Use roles and labels; Semaphore has no test ids
- [X] T027 Create `demos/catalog.py`: a frozen dataclass `Demo(slug, number, environment_names, run)` where `run` is the scenario's async entry point, and `DEMOS: tuple[Demo, ...]` in PRD order. Each scenario module registers itself here as its story adds it; until then `DEMOS` holds the demos written so far. Also add `VERSIONS_PATH` (`demos/infrahub_versions.yml`), a frozen dataclass `InfrahubVersions(previous, latest)` and `load_versions(path) -> InfrahubVersions`, which raises `ValueError` naming the file when a key is missing or `latest` is not greater than `previous` (compared with `packaging.version.Version`) (FR-006, data-model "Infrahub versions file")
- [X] T028 Create `demos/prerequisites.py` (FR-012, contract "Prerequisites check"): `check(api_url, credentials, versions_path) -> list[str]` returning the messages of the contract, in its order, for: `shutil.which("ffmpeg")`; the GraphQL endpoint answering and the admin login working; the `infrahub` and `semaphore` drivers loaded, the `local` cluster and a backup storage location present; `load_versions` succeeding
- [X] T029 Create `demos/__main__.py` (contract; FR-001, FR-010, FR-011): parse `--demo` (one of the catalog slugs; an unknown slug prints the four slugs and exits 2) and `--output-dir`; read the API URL and admin credentials from the environment variables the invoke task sets; run the prerequisites check and exit 2 with its message on failure; for each selected demo: delete leftovers (`stack.delete_environments`), launch Chromium headless with a 1920×1080 viewport and `base_url`, log in with `LoginPage`, run the demo with a `DemoRecorder`, encode to `<output-dir>/<number>-<slug>.mp4`, delete the demo's environments; on any exception record the failing step (`setup`, the recorder's current step, `post-processing` or `cleanup`), delete the raw and temporary files, keep the environments, and go on with the next demo. Print the summary table of the contract with `rich`, including the warning for videos over 3:00 and the memory note for kept environments (critique P3), and exit 0 or 1
- [X] T030 In `tasks/demo.py` add `SEMAPHORE_DEMO_IMAGE = "styrmin-demo/semaphore:v2.16.47"`, `build_semaphore_image(context)` (`docker build -t ... backend/tests/e2e/demos/semaphore`), and the task `record(context, demo="", output_dir="", build_image=False)` with help texts: builds the image when it is missing or `build_image` is set, then runs `python -m tests.e2e.demos` with `--demo`/`--output-dir` from `backend/` (`with context.cd("backend")`), passing the demo URL `http://styrmin.local.styrmin.io:8080` and the admin credentials from `_admin_credentials()` as environment variables, and lets the exit code through (`warn=True`, then `raise SystemExit(result.exited)` when it is not 0). The default output directory is `demo-videos/` at the repository root. Register it in `tasks/__init__.py` with `ns.add_task(demo.record, name="record")`
- [X] T031 Run `uv run pytest backend/tests/unit/demos backend/tests/unit/test_e2e_page_typing.py -q` and `uv run invoke format lint`; fix failures

**Checkpoint**: `uv run invoke record --demo <slug>` runs the prerequisites check and the run loop; no demo is registered yet, so the summary is empty.

---

## Phase 3: User Story 1 - Record the deploy and upgrade demo (Priority: P1) 🎯 MVP

**Goal**: demo 1 recorded as an MP4 with titles, cursor, typing and sped-up waits (FR-004 to FR-007).

**Independent Test**: on a demo stack that `uv run invoke start` just created, `uv run invoke record --demo deploy-upgrade` writes `demo-videos/1-deploy-upgrade.mp4`, and the video shows the deploy, the upgrade and the upgrade task's steps.

- [X] T032 [US1] Create `demos/infrahub_versions.yml` with `previous: "1.10.11"` and `latest: "1.11.7"` (or the version T009 chose) and a comment that someone updates it by hand and that a new Infrahub release may need a newer chart in the `infrahub` driver (FR-006). Until this file exists, the prerequisites check reports it as missing
- [X] T033 [US1] Create `demos/scenarios/deploy_upgrade.py` (plan demo table; data-model names): setup creates `network-lab-upgrade`; the recorded steps use `UiScenarioDriver(page=page, base_url=..., keystroke_delay_ms=45)` and `DeploymentDetailPage`:
  1. step "Deploy Infrahub <previous>": `create_deployment(driver="infrahub", version=previous, environment_id=..., name="infrahub")`, then `wait("Infrahub <previous> is starting")` around `wait_for_deployment_running(timeout=900)`;
  2. step "Upgrade to Infrahub <latest>": `read_task_ids()`, `upgrade_deployment(version=latest)`, `open_timeline()`, then `wait("Upgrade in progress")` around `wait_for_new_task("upgrade_instance", ...)`;
  3. step "The upgrade task and its steps": `open_timeline()` again and hold 3 s so the expanded task and its steps, including the driver's upgrade action, are on screen.

  Register the demo in `demos/catalog.py` with environment names `("network-lab-upgrade",)`

  Changed after the first recordings ([spike-notes.md](spike-notes.md#what-changed-after-watching-the-first-recording)): `read_task_ids()` moved to the end of chapter 1; `DeploymentDetailPage.show_timeline_entry(task_id)` was added to expand and show the upgrade task; the demo fails unless the step of the driver's upgrade action succeeded and the upgrade task's timeline entry shows the `latest` version.
- [X] T034 [US1] Record demo 1 alone on a demo stack that `uv run invoke start` just created: `uv run invoke record --demo deploy-upgrade`. Watch the video and check each item of quickstart §4 for demo 1; check `ffprobe` gives `h264,1920,1080,yuv420p` and a length of 3:00 or less; check the environment is gone. Fix the scenario or the page objects until it passes, and note the length in `specs/031-recorded-feature-demos/spike-notes.md`

**Checkpoint**: one demo works end to end; the presenter can use video 1.

---

## Phase 4: User Story 2 - Record the component overrides demo (Priority: P1)

**Goal**: demo 2 recorded (FR-003, FR-015).

**Independent Test**: `uv run invoke record --demo component-overrides` on a fresh demo stack writes `demo-videos/2-component-overrides.mp4` showing both overrides.

- [X] T035 [US2] Create `demos/scenarios/component_overrides.py`: setup creates `network-lab-overrides` and deploys `infrahub` at `latest` and `semaphore` with the default image, both named after their driver; recorded steps:
  1. step "Use an image with the Infrahub Ansible collection": `read_task_ids()`, `set_component_image(deployment_id=<semaphore>, component="server", image="styrmin-demo/semaphore:v2.16.47")`, then `wait("Semaphore restarts with the new image")` around `wait_for_new_task("update_instance", ...)`;
  2. step "Run two Infrahub servers": `read_task_ids()` on the Infrahub deployment, `set_component_replicas(deployment_id=<infrahub>, component="server", replicas=2)`, then `wait("A second Infrahub server starts")` around `wait_for_new_task("update_instance", ...)`.

  Register it with environment names `("network-lab-overrides",)`
- [X] T036 [US2] Record demo 2 alone on a fresh demo stack and check it as in T034, plus: the Semaphore pod runs `styrmin-demo/semaphore:v2.16.47` (`kubectl get pod -n styrmin-<id> -o jsonpath`) before the cleanup deletes it; note the length in `specs/031-recorded-feature-demos/spike-notes.md`

---

## Phase 5: User Story 3 - Record the environment backup and restore demo (Priority: P1)

**Goal**: demo 3 recorded; the device and the template are back after the restore (FR-002, FR-019).

**Independent Test**: `uv run invoke record --demo backup-restore` on a fresh demo stack writes `demo-videos/3-backup-restore.mp4`; this is also the FR-002 check.

- [X] T037 [US3] Create `demos/scenarios/backup_restore.py`: setup creates `network-lab-backup`, calls `stack.load_enterprise_driver`, deploys `infrahub-enterprise` at `latest` and `semaphore` with parameter `docker_image=styrmin-demo/semaphore` (so the template's local repository exists), loads devices `sw1` and `sw2` with `infrahub_setup.load_devices`, and runs `semaphore_setup.configure`. Before recording, log in to Infrahub (`admin`/`infrahub`) and Semaphore on `recorder.unrecorded()` pages or before `start`. Recorded steps:
  1. step "Back up the whole environment": `create_environment_backup`, `wait("Backup in progress")` around `wait_for_environment_backup`;
  2. step "Delete a device in Infrahub": `InfrahubDevicesPage.delete_device("sw2")`;
  3. step "Delete the task template in Semaphore": `SemaphoreTemplatesPage.delete_template()`;
  4. step "Restore the backup": `restore_environment_backup`, `wait("Restore in progress")` around `wait_for_environment_restore`, then `wait("Infrahub restarts")` around `infrahub_setup.wait_until_ready`;
  5. step "The device and the template are back": show the Infrahub device list and the Semaphore template list, and fail the demo unless `sw2` and "List network devices" are listed.

  Register it with environment names `("network-lab-backup",)`
- [X] T038 [US3] Record demo 3 alone on a fresh demo stack and check it as in T034, plus the acceptance scenario of User Story 3 (both items back); note the length in `specs/031-recorded-feature-demos/spike-notes.md`

---

## Phase 6: User Story 4 - Record the environment clone demo (Priority: P1)

**Goal**: demo 4 recorded; the clone's Semaphore lists the device added in the clone's Infrahub, and the source's does not (FR-013).

**Independent Test**: `uv run invoke record --demo clone` on a fresh demo stack writes `demo-videos/4-clone.mp4` with the counts 2, 3 and 2.

**Dependency**: T008. If the alias check failed, this phase starts only after the product fix lands and T006 and T007 pass. Met on 2026-10-20: PR #531 fixed #530 and adds its own alias check to `test_environment_clone_lifecycle`, which passed in both variants (see [e2e-evidence.md](e2e-evidence.md#the-defect-is-fixed-by-531-which-carries-its-own-alias-check)).

- [X] T039 [US4] Create `demos/scenarios/clone.py`: setup creates `network-lab`, loads the enterprise driver, deploys `infrahub-enterprise` at `latest` and `semaphore` with `docker_image=styrmin-demo/semaphore`, loads `sw1` and `sw2`, runs `semaphore_setup.configure`, and logs in to both applications before the recording. Recorded steps:
  1. step "Semaphore reads its inventory from Infrahub": run the template, `wait("Ansible reads the inventory")` around `wait_for_output`, and fail unless the output says 2 devices;
  2. step "Clone the environment": `clone_environment(environment_id=..., name="network-lab-clone", deployment_ids=None)`, `wait("Clone in progress")` around `wait_for_environment_clone`; read the clone's Infrahub and Semaphore URLs from the counterpart deployments with the SDK; log in to both on `recorder.unrecorded()` pages (research R-016);
  3. step "Add a device in the clone's Infrahub": `add_device("sw3")`;
  4. step "The clone's Semaphore lists the new device": run the same template in the clone's Semaphore with no setting changed, wait for its output, fail unless it says 3 devices;
  5. step "The source is unchanged": run the template in the source Semaphore again, fail unless it says 2 devices.

  Register it with environment names `("network-lab-clone", "network-lab")`, the clone first so cleanup deletes it first
- [X] T040 [US4] Record demo 4 alone on a fresh demo stack and check it as in T034, plus the acceptance scenario of User Story 4 (counts 2, 3, 2); note the length in `specs/031-recorded-feature-demos/spike-notes.md`

---

## Phase 7: User Story 5 - Record all four demos with one command (Priority: P1)

**Goal**: one command records every demo, isolates failures and lists the results (FR-001, FR-009, FR-011, FR-012; SC-001, SC-002, SC-005).

**Independent Test**: quickstart §3 and §6.

- [X] T041 [US5] Check the prerequisites messages (quickstart §6): run `uv run invoke record` with ffmpeg removed from the PATH and with the demo stack paused (`uv run invoke stop`), and confirm exit code 2 and the contract's messages before any setup; paste both outputs into `specs/031-recorded-feature-demos/full-run.log`. Restart with `uv run invoke start`
- [X] T042 [US5] Run all demos on a fresh demo stack: `uv run invoke reset`, then `uv run invoke record 2>&1 | tee specs/031-recorded-feature-demos/full-run.log`. Confirm exit code 0, four `recorded` lines, four videos of 3:00 or less, `ffprobe` values as in quickstart §3, and that only the `local` environment and no demo namespace remain (SC-001, SC-002, SC-005). If demo 4 waits for the product fix (T008), run the three other demos with `--demo` one after the other in the same session instead, and say so in the log. Done on 2026-10-20: the run of all four demos on a fresh demo stack passed, with exit code 0, four `recorded` lines, four videos of 3:00 or less and only the `local` environment left (see "T042, second run" in `full-run.log`). The first run, on 2026-10-18, recorded demos 2 and 3 only, because demos 1 and 4 were not registered then; `full-run.log` keeps it, marked as superseded

---

## Phase 8: User Story 6 - Re-record one demo after a failed run (Priority: P2)

**Goal**: a failed run never blocks the next one (FR-009, FR-010).

**Independent Test**: quickstart §5.

- [X] T043 [US6] Follow quickstart §5: make demo 3 fail during its backup by scaling `deploy/velero` in namespace `styrmin` to 0, run `uv run invoke record --demo backup-restore`, and confirm exit code 1, the failing step and error in the summary, `network-lab-backup` kept, and no new video. Scale Velero back to 1, run it again, and confirm the leftover environment was deleted before the setup and only `3-backup-restore.mp4` was written. Append both outputs to `specs/031-recorded-feature-demos/full-run.log`

---

## Phase 9: Polish and Verification

- [X] T044 [P] Add a "Recording the demos" section to `dev/guides/local-demo.md` (FR-017): prerequisites (ffmpeg, network access for the image build and Semaphore's start, memory for two environments during demo 4); the commands and the four slugs; the versions file and when to update it (including that a new Infrahub release may need a newer chart in the driver); the output directory; what the summary means; what to do after a failed demo (inspect the kept environments; they use memory until the next run of that demo deletes them); how long a full run takes (research R-017, marked as not measured until T042 measures it)
- [X] T045 [P] Add a paragraph to `dev/knowledge/backend/e2e-testing.md` (Constitution §VII, plan): page objects take `keystroke_delay_ms` (default `None`, which the E2E suite keeps), `enter_text` in `pages/_dom.py`, `DeploymentDetailPage.wait_for_new_task`, and that `backend/tests/e2e/demos/` reuses the page objects, so a page-object fix repairs both (SC-004)
- [X] T046 Run `uv run invoke format lint` and `uv run invoke test`; fix failures
- [ ] T047 Open one video in Keynote, PowerPoint and Google Slides (uploaded to Google Drive) and play it without conversion (SC-003). If no Mac or Windows machine is available to the implementer, ask the maintainer to do it and record who did it and the result in `specs/031-recorded-feature-demos/full-run.log`
- [X] T048 Prepare the pull request notes: link `e2e-evidence.md`, `spike-notes.md` and `full-run.log`; state the approved E2E exception and the governance gates crossed (Playwright 1.64 upgrade that changes the UI E2E browser, ffmpeg, the local Semaphore image); state the two research findings for the maintainer: demos 3 and 4 use `infrahub-enterprise` (research R-007, critique P2 asks the maintainer to confirm showing it), and the alias check outcome with the issue link if T008 filed one; name the UI E2E shards in CI as the check of the page-object change

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none. T002 before T010 and T011.
- **Foundational (Phase 2)**: blocks every story.
  - 2a: T005 → T006, T007 → T008. T009 and T010 need a demo stack and can run while T006 and T007 run on their own vcluster, if the host has the memory; otherwise in sequence. T011 after T002.
  - 2b: T012 → T013, T014 → T015; T016 after T014 (same file).
  - 2c: T017 → T018 → T019.
  - 2d: T020 after T018; T021, T022, T023, T024, T025, T026 in parallel; T027 → T028 → T029 → T030; T031 last.
- **US1 (Phase 3)**: after Phase 2.
- **US2 (Phase 4)**: after Phase 2.
- **US3 (Phase 5)**: after Phase 2.
- **US4 (Phase 6)**: after Phase 2 and after T008 allows it.
- **US5 (Phase 7)**: after the demos that are ready (all four, or demos 1 to 3 when US4 waits).
- **US6 (Phase 8)**: after US3.
- **Polish (Phase 9)**: T044 and T045 any time after Phase 2; T046 to T048 last.

### User Story Dependencies

- US1, US2, US3 and US4 need only Phase 2. US4 also needs the alias check to pass.
- US5 needs the stories whose demos it records.
- US6 needs US3, because it breaks demo 3 on purpose.

### Parallel Opportunities

- Phase 1: T003 and T004.
- Phase 2: T013 with T014; T017 with 2b; T022 to T026 together.
- Stories: US1 to US4 can be written in parallel by different people; recording them needs the one demo stack, so recordings run one after the other.
- Polish: T044 and T045.

## Parallel Example: Phase 2d

```text
T022 Infrahub schema and setup helper
T023 Semaphore image and Ansible files
T024 Semaphore API setup
T025 Infrahub page object
T026 Semaphore page object
```

## Implementation Strategy

1. Phase 1 and Phase 2a: dependencies and the checks that research expects to fail. If the alias check fails, the maintainer decides on the product fix while the rest goes on.
2. Phase 2b to 2d: the shared recorder, post-processor, stack helpers and page objects.
3. US1 (MVP): demo 1 recorded end to end. This proves the recorder, the typing, the waits and the encoding.
4. US2 and US3: demos 2 and 3.
5. US4: demo 4, after the alias check passes.
6. US5, US6 and Polish: the full run on a fresh demo stack, the failure and re-record check, the guide, and the PR notes.

## Phase 10: Review of PR #540 (2026-10-21)

**Purpose**: address the review of [PR #540](https://github.com/opsmill/styrmin/pull/540) (Clarifications, session 2026-10-21). The numbers in brackets are the review's item numbers.

- [X] T049 [4] Keep a caption that names the application and its environment (`DemoRecorder.caption`), hold each result for at least 5 s (`DemoRecorder.hold`, which also rests the cursor at the right edge), end each video on a closing card (`encode.render_closing_card`, `Demo.summary`), and reword the sped-up labels (`video.label_text`) (FR-020)
- [X] T050 [4] Find why demo 1 ends on steps marked "Superseded by Stop Components" and why "Stop Components" itself can end Superseded; write the cause in the spec and a note for the presenter of each video in the guide
- [X] T051 [5] Check the Chromium build, ffprobe, docker and the kube context `vcluster-docker_styrmin` before any setup, and name a rejected admin login as such (FR-012)
- [X] T052 [6] On Ctrl-C, print the summary so far with the kept environments and exit with code 130; unit test that the client and the browser are closed (FR-023)
- [X] T053 [7] Delete only the environments that the command created, recorded in `$XDG_STATE_HOME/styrmin/demo-environments.json`, or that the developer confirms (FR-009)
- [X] T054 [8] Call the `DeploymentDetailPage` methods of the demos from the `[ui-chromium]` variants of `test_override_then_clear` and `test_token_follows_upgrade_and_action_job`, and the new `PodsTabPage` methods from `test_pods_tab_copy_logs_command`; run them to a pass; give the command an owner and a schedule in the guide
- [X] T055 [9] Keep the raw recording and the plan of the video after a failed encoding, and add `--encode-again` (FR-024)
- [X] T056 [10] Test the encoding with a real ffmpeg on a short generated recording: duration, size, codec and pixel format (`test_encode.py`)
- [X] T057 [11] Name the commit the beta videos are recorded from and add numbered first-time steps to the guide; make the errors of demos 1 and 4 name the fixes to #372 and #530
- [X] T058 [13] Update the spec: status, FR-016, T005 to T007, assumptions; answer the three open questions of #518 on the issue
- [X] T059 [14] Print a line when each wait starts and every minute while it lasts, each sub-step of the setup, and how long each demo usually takes (FR-025)
- [X] T060 [16] Build the demo Semaphore image inside the command after the argument and prerequisites checks, with list arguments, every time from Docker's cache
- [X] T061 [17] State the lasting facts in the guide without links into the spec, start its section with numbered steps, renumber the spec from 029 to 031, and delete `full-run.log` and `pr-notes.md`
- [X] T062 [18] Mask the Infrahub token in the Semaphore task errors; write each output file under a temporary name, then `os.replace`; name the Semaphore version in the Dockerfile's `FROM` line only; remove `close_output` and `PodsTabPage._keystroke_delay_ms`; explain the Playwright pin; share one Infrahub admin token constant (`tests/e2e/helpers/infrahub.py`); pin the base image digest and `infrahub-sdk==1.23.2`; delete the environments while ffmpeg encodes
- [X] T063 [19] Accept several `--demo` values and add `--delete-environments`; give each failed summary row a next step; end each chapter of demo 2 on the Pods tab; cut the white page of Semaphore's load, rest the cursor before each result, open the Upgrade dialog from the Timeline tab; write a chapter file next to each MP4 (FR-021, FR-022)
- [ ] T064 Record the four demos on a fresh demo stack and watch each video

