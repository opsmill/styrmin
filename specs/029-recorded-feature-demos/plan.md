# Implementation Plan: Recorded Demos of Four Styrmin Features

**Branch**: `fac/demo-beta-presentation-bhshh` | **Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/029-recorded-feature-demos/spec.md` (PRD: [#518 comment](https://github.com/opsmill/styrmin/issues/518#issuecomment-6240009049))

## Summary

A developer starts the local demo stack and runs `uv run invoke record`. The command records four demos of Styrmin features for the beta presentation and writes one MP4 video for each. Each demo creates its environment and deployments through the SDK without recording, then performs its feature in the Styrmin UI through the E2E page objects while Playwright records the page, and finally deletes what it created. The videos show a title at the start of each step, a cursor and a highlight on each action, text typed one key at a time, and each wait for the cluster sped up with a label that gives its real duration.

Technical approach (details in [research.md](research.md)):

- Check first what research found likely to fail: add the FR-016 alias check to `test_environment_clone_lifecycle` and run it (R-013), and check on the demo stack that Infrahub 1.10.11 runs on chart 4.33.2 and that `infrahub-enterprise` runs 1.11.7 and takes an environment backup (R-007, R-015). Stop for a maintainer decision if the alias check fails.
- Upgrade Playwright to 1.64 and use its Screencast API: `start` at 1920×1080, `show_actions` with a cursor, `show_chapter` for step titles (R-001).
- Give the E2E page objects a `keystroke_delay_ms` setting, passed by `UiScenarioDriver`, that types text with `press_sequentially`; the E2E suite keeps `fill` (R-006).
- Record the start and end of each wait and each login cut; after the recording, a pure planning function turns them into segments, and ffmpeg cuts, speeds up and joins them with PNG labels rendered by the browser, into H.264 MP4 (R-002 to R-005, R-016).
- Put the recorder, the demo scripts, the setup helpers and the page objects for Infrahub and Semaphore in `backend/tests/e2e/demos/`, run as `python -m tests.e2e.demos` from `backend/` by a new `record` task in `tasks/demo.py` (R-012).
- Deploy `infrahub-enterprise` in demos 3 and 4, because the `infrahub` driver cannot take an environment backup (R-007).
- Build a demo Semaphore image locally with the `opsmill.infrahub` collection 1.8.3, `infrahub-sdk`, and the playbook and inventory file used as a local repository (R-009). Configure Semaphore through its API in the setup (R-010).
- Add a "Recording the demos" section to the local demo guide.

## Technical Context

**Language/Version**: Python 3.14+ (recorder, demo scripts, invoke task, E2E page objects); YAML (Infrahub schema, versions file, Ansible playbook and inventory); a Dockerfile for the demo Semaphore image.

**Primary Dependencies**:

- Playwright 1.58.0 → 1.64.0 (`playwright>=1.64,<1.65` added to the root dev group; approved in the grilling session).
- ffmpeg on the developer's PATH, any build with libx264 (approved). `drawtext` is not needed (R-003).
- The demo Semaphore image `styrmin-demo/semaphore:v2.16.47`, built locally from `semaphoreui/semaphore:v2.16.47` with `opsmill.infrahub` 1.8.3 and `infrahub-sdk` (approved).
- Existing: `styrmin-sdk`, `infrahub-sdk>=0.16`, `kr8s`, `httpx` (through the SDK), `invoke`, `rich`, PyYAML.

**Storage**: N/A. No database, GraphQL, SDK, `styrminctl` or frontend change (FR-018). Videos go to `demo-videos/`, ignored by git.

**Testing**:

- Unit tests for the post-processor's planning and ffmpeg arguments in `backend/tests/unit/demos/` (the CI unit job runs them).
- The FR-016 read-only check added to `test_environment_clone_lifecycle` (`shard_env_backup`), run locally in both variants with recorded PASS evidence.
- The UI E2E suite in CI after the Playwright upgrade and the page-object change.
- One run of all four demos on a demo stack that `uv run invoke start` just created, with the output attached to the PR (the approved E2E exception).

**Target Platform**: A developer laptop (Linux or macOS) running the local demo stack on vCluster with Docker.

**Project Type**: Development tooling inside the Styrmin repository (invoke task plus a Python package under `backend/tests/e2e/`).

**Performance Goals**: Each video lasts 3 minutes or less (SC-002). A full run is expected to take 60 to 90 minutes, mostly waiting for Infrahub deployments (R-017); not a requirement.

**Constraints**:

- The demo scripts contain no selector for a Styrmin page (FR-003). Missing Styrmin actions are added to the E2E page objects, not to the demos.
- The E2E suite keeps filling fields in one step (FR-004): `keystroke_delay_ms` defaults to `None` everywhere the E2E fixtures build page objects.
- No CI workflow change (Governance gate). CI installs the browser with `uv run playwright install chromium`, which follows the lock file.
- The Semaphore image is not pushed to a registry (FR-015).
- No product code change. If the alias check fails, the fix is a separate change (R-013).

**Scale/Scope**: 1 new package (about 12 modules, 2 page objects, 4 demo scripts), 3 data files and an image directory; the ten page-object files and the UI driver changed for the typing setting; 1 E2E test extended; 1 unit test module; 1 invoke task; 1 guide section; 1 knowledge-page paragraph; `pyproject.toml`, `uv.lock` and `.gitignore`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
| --- | --- | --- |
| I. Declarative state reconciliation | Pass | No product change. The demos use Styrmin's normal create, upgrade, override, backup, restore and clone actions. |
| II. Driver-based deployment | Pass | No driver change. Demos 3 and 4 use the existing `infrahub-enterprise` driver (R-007); the Semaphore image is selected with the `semaphore` driver's existing `docker_image` parameter and with an image override. |
| III. Layered architecture | Pass | No API, service or repository change. The demos act through the UI (page objects) and the public SDK. |
| IV. Type safety and typed errors | Pass | New code is typed and checked by `ty`. No product error types. |
| V. Test-first development | Pass, with the approved exception | No E2E test for the demo scripts, approved in the grilling session; the proof is one full run on a fresh demo stack. The read-only FR-016 check extends `test_environment_clone_lifecycle` instead of adding a node ("reuse before you boot"); its local PASS evidence is recorded for both variants. Research predicts it fails on the current code (R-013); the plan then stops for a maintainer decision instead of weakening the check. Unit tests cover the post-processor. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit. |
| VII. Documentation accuracy | Pass | "Recording the demos" in `dev/guides/local-demo.md`; a paragraph in `dev/knowledge/backend/e2e-testing.md` on the page objects' `keystroke_delay_ms` and their reuse by the demos. No `docs/`, towncrier or `CONTEXT.md` change, as agreed in the grilling session. If R-013 is confirmed, the wrong statement in `docs/.../ingress-and-networking.md` is part of the bug issue, not of this change. |
| Governance gates | Pass | New dependencies approved in the grilling session (Playwright upgrade, ffmpeg, Semaphore image). No schema, GraphQL, CI workflow or auth change. Skipping E2E coverage for the demos approved in the grilling session. |

Post-design re-check (after Phase 1): unchanged. The design adds no product code and no new E2E node. The two findings (R-007, R-013) are recorded in the spec's Clarifications and flagged for the maintainer.

## Project Structure

### Documentation (this feature)

```text
specs/029-recorded-feature-demos/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0: R-001 to R-017
├── data-model.md        # Phase 1: demo, step, wait, cut, segment, result, files
├── quickstart.md        # Phase 1: how to verify the feature
├── contracts/
│   └── record-command.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (speckit-tasks)
```

### Source Code (repository root)

```text
backend/tests/e2e/
├── pages/
│   ├── _dom.py                        # + enter_text(locator, text, *, keystroke_delay_ms)
│   ├── deploy_form.py                 # constructors take keystroke_delay_ms; .fill → enter_text
│   ├── deployment_detail.py           #   (same in every page-object file) + open_timeline() for demo 1
│   ├── environments.py
│   └── ...
├── drivers/
│   └── ui_driver.py                   # UiScenarioDriver(..., keystroke_delay_ms=None) passes it on
├── test_backup_restore.py             # FR-016: alias check in test_environment_clone_lifecycle
└── demos/
    ├── __init__.py
    ├── __main__.py                    # argument parsing, prerequisites, run loop, summary, exit code
    ├── catalog.py                     # the four Demo definitions (slug, number, environment names)
    ├── prerequisites.py               # ffmpeg, demo stack, drivers, BSL, versions file (FR-012)
    ├── recorder.py                    # screencast, steps, waits, cuts, unrecorded page, failure handling
    ├── video.py                       # pure: plan_segments, label_text, ffmpeg_arguments (unit tested)
    ├── encode.py                      # renders label PNGs, runs ffmpeg
    ├── stack.py                       # SDK: environments, BSL, drivers, deployments, cleanup, namespaces
    ├── infrahub_setup.py              # schema and devices through infrahub-sdk
    ├── semaphore_setup.py             # project, repository, inventory, environment, template via API
    ├── infrahub_versions.yml          # previous / latest (FR-006)
    ├── infrahub/
    │   └── schema.yml                 # InfraDevice
    ├── semaphore/
    │   ├── Dockerfile                 # styrmin-demo/semaphore:v2.16.47
    │   └── ansible/
    │       ├── list_hosts.yml
    │       └── inventory/infrahub.yml
    ├── pages/
    │   ├── __init__.py
    │   ├── infrahub.py                # InfrahubDevicesPage (FR-014)
    │   └── semaphore.py               # SemaphoreTemplatesPage (FR-014)
    └── scenarios/
        ├── __init__.py
        ├── deploy_upgrade.py          # demo 1
        ├── component_overrides.py     # demo 2
        ├── backup_restore.py          # demo 3
        └── clone.py                   # demo 4

backend/tests/unit/demos/
├── __init__.py
└── test_video.py

tasks/demo.py                          # + record task, + Semaphore image build
pyproject.toml, uv.lock                # playwright>=1.64,<1.65
.gitignore                             # demo-videos/
dev/guides/local-demo.md               # "Recording the demos"
dev/knowledge/backend/e2e-testing.md   # keystroke_delay_ms, demos reuse the page objects
```

**Structure Decision**: The demos live next to the E2E page objects they reuse, in `backend/tests/e2e/demos/`, so a fix to a page object repairs the demos and the E2E tests in one place (SC-004) and the demos import `tests.e2e.*` the same way the E2E suite does (R-012). Page objects for Infrahub and Semaphore stay inside `demos/pages/`, because only the demos use them (FR-014). pytest does not collect the demo modules, because none is named `test_*.py`.

## Design

### Recorder flow for one demo

1. **Leftovers** (FR-009): delete every environment with one of the demo's names, the clone first, and wait for their namespaces to go (R-014).
2. **Setup** (FR-002, not recorded): create the environment on the `local` cluster, assign the demo stack's backup storage location, load `infrahub-enterprise` when the demo needs it, deploy and wait through the SDK, load the schema and devices into Infrahub, configure Semaphore through its API.
3. **Browser**: launch Chromium headless with a 1920×1080 viewport and the demo URL as `base_url`. Log in to Styrmin with `LoginPage`, and to Infrahub and Semaphore on a second page of the same context (R-016).
4. **Recording**: `screencast.start(path, size=1920×1080)`, `show_actions(cursor="pointer")`, then the demo's `record` function. It uses:
   - `async with recorder.step(title)`: shows the chapter and names the step for failure reports;
   - `async with recorder.wait(label)`: records a wait;
   - `async with recorder.unrecorded() as page`: a second page whose time is cut from the video;
   - `UiScenarioDriver(page=..., base_url=..., keystroke_delay_ms=45)` for every Styrmin action, and the Infrahub and Semaphore page objects for the rest.
5. **Post-processing**: `stop()`, `plan_segments`, label PNGs, ffmpeg to `<output>/<n>-<slug>.mp4` through a temporary file that is renamed only when ffmpeg succeeds.
6. **Deletion** (FR-009): delete the demo's environments and wait for their namespaces.
7. **Failure** (FR-010): any exception in steps 2 to 5 stops the demo, deletes the raw and temporary files, keeps the environments and records the failing step and error. The run loop goes on with the next demo (FR-011).

### The four demo scripts

| Demo | Setup (SDK and APIs, not recorded) | Recorded steps (page objects) | Waits |
| --- | --- | --- | --- |
| 1 `deploy-upgrade` | Environment `network-lab-upgrade` | Deploy Infrahub `previous` with the `infrahub` driver version chosen in the form; open the deployment; upgrade to `latest`; open the timeline, where the running upgrade task is expanded and shows its steps, including the driver's upgrade action | Deployment running; upgrade task finished |
| 2 `component-overrides` | Environment `network-lab-overrides` with `infrahub` (`latest`) and `semaphore` | Set the Semaphore `server` image override to `styrmin-demo/semaphore:v2.16.47`; set a replica override of 2 on the Infrahub `server` component | Each update task finished |
| 3 `backup-restore` | Environment `network-lab-backup` with `infrahub-enterprise` (`latest`) and `semaphore`; schema, two devices; Semaphore project and template | Create an environment backup; delete a device in Infrahub; delete the template in Semaphore; restore the backup; list the devices and the templates again | Backup finished; restore finished; Infrahub answering again |
| 4 `clone` | Environment `network-lab` with `infrahub-enterprise` (`latest`) and `semaphore` (`docker_image: styrmin-demo/semaphore`); schema, two devices; Semaphore project, inventory, environment and template | Run the template in the source Semaphore (2 devices); clone the environment as `network-lab-clone`; add a third device in the clone's Infrahub; run the template in the clone's Semaphore (3 devices); run it in the source again (2 devices) | Each Semaphore task; clone finished |

Each demo checks what it shows, so a demo that shows a wrong result fails instead of producing a misleading video: demo 3 checks the device and the template are back; demo 4 checks the device counts 2, 3 and 2 in the task outputs.

### Phases for implementation

Detailed tasks come from `speckit-tasks`. The order:

1. **Checks first** (blocking):
   - FR-016 alias check added and run in both variants (R-013). If it fails: file the bug issue, stop, and ask the maintainer how to proceed.
   - On a fresh demo stack, with a throwaway SDK script: Infrahub `previous` on chart 4.33.2 and its upgrade to `latest` (R-015); `infrahub-enterprise` at `latest`, an environment backup and restore of it (R-007); the demo Semaphore image runs the inventory against Infrahub through the `infrahub` alias (R-008, R-009).
   - Playwright 1.64 upgrade with the UI smoke E2E test run locally; a screencast that crosses origins keeps recording (R-001).
2. **Foundation**: `enter_text` and `keystroke_delay_ms` through the page objects and `UiScenarioDriver`; `video.py` with its unit tests; `encode.py`; `recorder.py`; `prerequisites.py`; `stack.py`; `catalog.py`; `__main__.py`; the `record` invoke task; `.gitignore`.
3. **Demo 1** (User Story 1, P1): versions file, `open_timeline()`, the demo script; record it alone.
4. **Demo 2** (User Story 2): the Semaphore image and its build in `tasks/demo.py`; the demo script; record it alone.
5. **Demo 3** (User Story 3): `infrahub_setup.py`, `semaphore_setup.py`, the two page objects; the demo script; record it alone.
6. **Demo 4** (User Story 4): the demo script; record it alone. Blocked if the alias check failed.
7. **All demos and re-recording** (User Stories 5 and 6): failure isolation and the summary; leftover cleanup checked by making demo 3 fail once.
8. **Documentation and evidence**: the guide section, the knowledge paragraph, the full run on a fresh demo stack with its output for the PR, and the three presentation applications opening one video each (SC-003).

## Complexity Tracking

| Exception | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| No E2E test for the demo scripts (Constitution §V) | Approved in the grilling session: the demos are development tooling, proved by one full run on a fresh demo stack. | An E2E test that records videos would need ffmpeg and the full Infrahub and Semaphore stack in CI, which is a CI workflow change the PRD keeps out of scope. |
| A cut range in the post-processor next to the waits (R-016) | The clone's Infrahub and Semaphore exist only after a recorded step, so logging in to them happens during the recording. | Logging in on the recorded page adds about 10 seconds of login forms to demo 4, which is not part of the feature shown. |
