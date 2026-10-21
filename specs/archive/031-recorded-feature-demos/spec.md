# Feature Specification: Recorded Demos of Four Styrmin Features

**Feature Branch**: `fac/demo-beta-presentation-bhshh`

**Created**: 2026-10-17

**Status**: Extracted on 2026-10-21 ([EXTRACTED.md](EXTRACTED.md)). The feature was implemented before that. The review of [PR #540](https://github.com/opsmill/styrmin/pull/540) was addressed on 2026-10-21 (Clarifications, session 2026-10-21). The spec number was 029 until that review; it changed to 031 because `specs/archive/029-local-driver-actions` already uses 029.

**Input**: PRD "Recorded demos of four Styrmin features for the beta presentation" — [opsmill/styrmin#518 (comment)](https://github.com/opsmill/styrmin/issues/518#issuecomment-6240009049). Seed issue: [#518](https://github.com/opsmill/styrmin/issues/518). The PRD's links point to `develop` at [ce8cb7d8](https://github.com/opsmill/styrmin/tree/ce8cb7d8d3ef8aee655e31aca8e77e02cc539409).

## Context

OpsMill wants to show Styrmin's main features in the beta presentation. Today a presenter performs each feature in the Styrmin UI by hand, live or while recording the screen ([#518](https://github.com/opsmill/styrmin/issues/518)). Some steps wait for the cluster for minutes: the E2E suite allows up to 300 seconds for a backup and 600 seconds for a restore ([`protocol.py`](../../backend/tests/e2e/drivers/protocol.py)). A recording made by hand shows the UI as it was on the day of the recording, so it has to be made again after each UI change.

The local demo stack gives a running Styrmin to demo against, but it does not show any feature by itself ([`local-demo.md`](../../dev/guides/local-demo.md), [`tasks/demo.py`](../../tasks/demo.py)). `uv run invoke start` creates a vCluster, installs Styrmin, and creates a cluster, an environment and a backup storage location. It loads the `infrahub` and `semaphore` drivers ([`tasks/dev.py`](../../tasks/dev.py), `bootstrap` and `BUNDLED_DRIVERS`).

The E2E suite already performs Styrmin actions in the UI through page objects under [`backend/tests/e2e/pages/`](../../backend/tests/e2e/pages/). The UI scenario driver composes them, and each action ends on a deterministic success signal ([`ui_driver.py`](../../backend/tests/e2e/drivers/ui_driver.py)).

This feature adds one command that records a video of each of four demos. Each demo creates what it needs through the SDK without recording, then performs its feature in the Styrmin UI through the E2E page objects while the browser is recorded. The videos are for a presenter to play and speak over. The feature changes no Styrmin product code: no GraphQL, SDK, `styrminctl`, frontend, database or driver change.

## Clarifications

### Session 2026-10-17 (autonomous, from the PRD)

The PRD's decisions were taken in a grilling session on 2026-10-17 that started from [#518](https://github.com/opsmill/styrmin/issues/518). They are recorded here so later phases do not reopen them.

- Q: Who watches the demos (#518's first open question)? → A: The audience of the beta presentation. A presenter plays the videos and speaks over them. Videos for the website and screenshots for the docs are out of scope.
- Q: Which features count as the main features (#518's second open question)? → A: Four: deploy and upgrade, component overrides, environment backup and restore, and environment clone.
- Q: What form does a demo take (#518's third open question)? → A: A video file for each demo, with no recorded voice and no captions over the page.
- Q: Which applications do the demos deploy? → A: Infrahub and Semaphore in every demo. In the demo environment, Semaphore runs an Ansible playbook that reads its inventory from Infrahub.
- Q: Is a new E2E test required for the demo scripts? → A: No. This exception to Constitution §V was approved in the grilling session. The proof is one run of all four demos on a demo stack that `uv run invoke start` just created, with the command output attached to the pull request. `test_environment_clone_lifecycle` was to get one read-only check instead (FR-016). That check was dropped on 2026-10-20, because [PR #531](https://github.com/opsmill/styrmin/pull/531) adds its own alias check to the same test ([E2E evidence](e2e-evidence.md#the-defect-is-fixed-by-531-which-carries-its-own-alias-check)).
- Q: Which new dependencies are approved? → A: An upgrade of Playwright from 1.58.0 to 1.61 or later, which also changes the browser the UI E2E tests run in, locally and in CI; ffmpeg on the developer's PATH; and a Semaphore image built locally that contains the `opsmill.infrahub` Ansible collection and the `infrahub-sdk` Python package.
- Q: Which documentation changes? → A: A "Recording the demos" section in the [local demo guide](../../dev/guides/local-demo.md). No `docs/` page, no towncrier fragment and no `CONTEXT.md` entry, because nothing changes for Styrmin users and a demo is not a Styrmin domain concept.

### Session 2026-10-17 (autonomous answers to the PRD's open questions)

The PRD left two questions open. They are answered here with the most direct option, so that planning can start. A maintainer can reverse either answer before implementation.

- Q: Where do the playbook and the inventory file live? → A: Inside the demo Semaphore image, which Semaphore uses as a local repository. The PRD proposed this option. The Styrmin repository is private, so a Semaphore in the vCluster would need credentials to clone the playbook from it.
- Q: Which Infrahub schema defines the devices that the inventory lists? → A: A small schema kept with the demos, which defines one device kind with a name. The demo setup loads it into each Infrahub it creates, before the recording starts. The PRD names no existing schema, and a schema kept with the demos does not depend on the schema library or on demo data that the `infrahub` driver turns off (`infrahubDemoData.enabled: false` in [`values.j2.yml`](../../driver/examples/infrahub/values.j2.yml)).

### Session 2026-10-17 (planning research, [research.md](research.md))

Two findings change what the PRD assumed. Both are flagged for the maintainer.

- Q: Can the `infrahub` driver take the environment backup that demos 3 and 4 need? → A: No. Its Neo4j backup runs `neo4j-admin database backup`, an online backup that only Neo4j Enterprise has, and the `infrahub` driver deploys the community chart. Its backup E2E test is skipped with the reason "backup/restore not supported with community" (R-007). Demos 3 and 4 therefore deploy Infrahub with the existing `infrahub-enterprise` driver, which the Styrmin image already contains and whose backup test runs in CI. Demos 1 and 2 keep the `infrahub` driver.
- Q: Does a clone's Semaphore reach the clone's Infrahub today? → A: Probably not. *(Confirmed, then fixed: the defect is [#530](https://github.com/opsmill/styrmin/issues/530), fixed by [PR #531](https://github.com/opsmill/styrmin/pull/531) on `develop`.)* A clone restores each source namespace, including the `ExternalName` alias Services that point to the source's namespaces, and no step of the clone writes the clone's own aliases afterwards (R-013, from reading the code; not run). The FR-016 check is therefore the first implementation task. If it fails, the implementer reports the defect as a separate issue and stops for a maintainer decision, because a fix changes Styrmin's restore or clone flow, which the PRD keeps out of scope. Demo 4 cannot show three devices in the clone until the defect is fixed. The recorder and demos 1 to 3 do not depend on the aliases and go on; the FR-016 check and demo 4 land once the check passes (critique X1).
- Q: Which Playwright version? → A: 1.64.0, the first version whose cursor stays visible after the page loads a new URL (R-001). The PRD asked for 1.61 or later.
- Q: Which Infrahub versions does the versions file start with? → A: `1.10.11` and `1.11.7`. No document says chart 4.33.2 runs 1.10.x, so the first demo task checks it; if it does not, the developer sets the earlier version to the newest 1.11 release below 1.11.7 (R-015).
- Q: How does the inventory read Infrahub? → A: With the admin token that both Infrahub charts preset, which Semaphore passes to Ansible as a secret of its environment. The inventory plugin requires a token even when Infrahub allows anonymous reads (R-008).
- Q: Which version of the `opsmill.infrahub` collection? → A: 1.8.3. Version 1.9.0 requires ansible-core 2.19, and the Semaphore 2.16.47 image has 2.18.12 (R-009).

### Session 2026-10-21 (review of PR #540)

The review of [PR #540](https://github.com/opsmill/styrmin/pull/540) found that a viewer cannot follow the videos without someone who explains them, and that the command misses several problems. The maintainer answered the open questions of the review.

- Q: Do the videos keep the decision "no captions over the page"? → A: No. Demo 4 shows two Semaphore pages that look the same, and both show "Task #2". Each video now keeps a caption in its bottom left corner that names the application on screen and its environment, for example "Semaphore in network-lab-clone (clone)" (FR-020). Other captions stay out of scope.
- Q: How does a video end? → A: On a closing card that gives the demo's title and what the video showed (FR-020). Each result stays on screen for at least 5 s, because a video played inside a slide is smaller than the screen. The guide holds a short note for the presenter for each video.
- Q: Why does the upgrade task of demo 1 end with steps marked "Superseded by Stop Components"? → A: The driver's upgrade action starts the tasks "Stop Components" and "Start Components". Each of them writes the StyrminDeployment resource, which supersedes the rollout steps of the older tasks of the deployment that are still open ([`supersede_operator_steps`](../../backend/styrmin_backend/services/steps/recorder.py)). A step superseded by a task of the same family counts as done, so the upgrade task's result stays Succeeded ([`results.py`](../../backend/styrmin_backend/services/steps/results.py)). "Stop Components" is a sibling of "Start Components", not its starter, so its own result is Superseded when "Start Components" writes the resource before the operator reports the end of the "Stop Components" rollout. This cause comes from reading the code and was not reproduced on purpose; it fits the two runs of 2026-10-20, in which "Stop Components" ended Succeeded once and Superseded once ([spike notes](spike-notes.md#since-the-fix-2026-10-20), [implement report](opsmill-implement-report.md)). Whether the product should show these steps differently is not decided; the presenter note of demo 1 explains them.
- Q: Which Styrmin commit are the beta videos recorded from? → A: The `develop` commit that merges PR #540, or a later one. The first `develop` commit that holds both fixes the demos need, from #531 and [#535](https://github.com/opsmill/styrmin/pull/535), is `bb56eac9`.
- Q: Who owns the record command, and when are the demos recorded again? → A: Fatih Acar owns it. The demos are recorded again before each presentation that uses the videos, after a change to a UI page that a demo uses, and after a change to `infrahub_versions.yml`. CI does not run the demos, so these recordings are the test of the Infrahub and Semaphore page objects. The `[ui-chromium]` variants of two tests in `test_deployment_image_override.py` and `test_pods_tab_copy_logs_command` in `test_ui_smoke.py` call the Styrmin page-object methods that the demos added (SC-004).
- Q: Does PR #540 close #518? → A: Yes. The answers to the three open questions of #518 are posted on the issue.
- Q: Which environments may the command delete? → A: Only the environments with a demo's names that the command created, which it records in a file outside the repository, and environments that the developer confirms on the terminal. Without a terminal, the command stops before any change (FR-009).
- Q: What happens on Ctrl-C? → A: The command prints the summary of the demos so far, with the environments it keeps, and exits with code 130. The client and the browser are closed (FR-023).
- Q: What happens when the encoding fails? → A: The command keeps the raw recording and the plan of the video, and can encode them again without recording again (FR-024).

## User Scenarios & Testing *(mandatory)*

Two people use this feature:

- A **presenter**, who plays the videos in the beta presentation and speaks over them.
- A **developer**, who records the videos before each presentation and repairs a demo that a UI change broke.

The user needs from the PRD, numbered as there:

1. As a presenter, I want a recorded video of each demo, so that I can show a feature without performing its steps live and without waiting for the cluster in front of the audience.
2. As a presenter, I want each step to start with a title, so that the audience can follow what the demo shows while I speak.
3. As a presenter, I want the video to show where the script clicks and what it types, so that the audience can follow the actions on the page.
4. As a presenter, I want each wait for the cluster sped up and labelled with its real duration, so that the video stays short without suggesting that the operation is faster than it is.
5. As a presenter, I want the videos as MP4 files at 1920×1080, so that I can play them in Keynote, PowerPoint and Google Slides.
6. As a developer, I want to record all four demos with one command, so that the videos match the current UI before each presentation.
7. As a developer, I want to re-record one demo without recording the others, so that I can fix a demo that a UI change broke without waiting for the other three.
8. As a developer, I want each demo to create and delete its own environments, so that the demos run in any order and do not fill the local vCluster.
9. As a developer, I want a failed demo to report the failing step and keep its environments, so that I can inspect what went wrong.
10. As a developer, I want a failed earlier run to never block the next one, so that re-recording does not fail because a name is already in use.
11. As a developer, I want the Infrahub versions of the deploy and upgrade demo set in one file that I update by hand, so that I decide when the demo moves to a new Infrahub release.

The PRD defines two journeys: P1, record the four demo videos, and P2, re-record one demo. The stories below split P1 into one story for each demo and one for the command that records all four, so that each demo can be checked on its own. User Story 1 also carries the parts every video shares (needs 2 to 5), because the first demo cannot be recorded without them.

### User Story 1 - Record the deploy and upgrade demo (Priority: P1)

The developer records demo 1 by naming it. The setup, which is not recorded, creates an empty environment. The recording then shows, in the Styrmin UI:

- the deployment of Infrahub at the version before the latest one, for example 1.10.0, with a chosen application driver version;
- the upgrade of that deployment to the latest version, currently 1.11.7;
- the steps of the upgrade task, including the driver's upgrade action.

The two Infrahub versions come from one file that the developer updates by hand. Each step starts with a title. A cursor and a highlight show each element the script clicks or types into, and text is typed one key at a time. Each wait for the cluster is sped up, with a label that gives its real duration and the speed-up factor. Covers needs 1 to 5 and 11.

**Why this priority**: deploying and upgrading an application is the first thing the beta audience needs to see. This demo also proves the parts every video shares.

**Independent Test**: on a demo stack that `uv run invoke start` just created, record demo 1 alone and play the video.

**Acceptance Scenarios**:

1. **Given** a demo stack that `uv run invoke start` just created and ffmpeg on the PATH, **When** the developer records demo 1, **Then** the output directory contains one MP4 file for demo 1 that shows the deployment of the older Infrahub version, the upgrade to the newer one and the steps of the upgrade task, including the driver's upgrade action.
2. **Given** the versions file names two Infrahub versions, **When** demo 1 is recorded, **Then** the video deploys the first version and upgrades to the second.
3. **Given** a recorded video, **When** the presenter plays it, **Then** each step starts with a title, each click and each text field shows a cursor and a highlight, and text appears one key at a time.
4. **Given** a recorded video, **When** a wait for the cluster plays, **Then** it is sped up and a label gives its real duration and the speed-up factor.
5. **Given** a recorded video, **When** it is opened in Keynote, PowerPoint and Google Slides, **Then** it plays without conversion and lasts 3 minutes or less.

---

### User Story 2 - Record the component overrides demo (Priority: P1)

The developer records demo 2. The setup creates an environment that contains Infrahub and Semaphore. The recording shows, in the Styrmin UI:

- an image override on the Semaphore deployment, to the demo Semaphore image that contains the Infrahub Ansible collection, without a change to the driver;
- a replica override of 2 on the Infrahub server component.

Covers need 1 for this demo.

**Why this priority**: component overrides let an operator change an application without changing its driver, which the beta audience needs to see.

**Independent Test**: on a demo stack that `uv run invoke start` just created, record demo 2 alone and play the video.

**Acceptance Scenarios**:

1. **Given** a demo stack and the demo Semaphore image loaded into the vCluster, **When** the developer records demo 2, **Then** the video shows the image override set on the Semaphore deployment and the replica override of 2 set on the Infrahub server component, and the output directory contains one MP4 file for demo 2.

---

### User Story 3 - Record the environment backup and restore demo (Priority: P1)

The developer records demo 3. The setup creates an environment that contains Infrahub with devices and Semaphore with a task template. Infrahub is deployed with the `infrahub-enterprise` driver (see Clarifications). The recording shows:

- the creation of an environment backup, in the Styrmin UI;
- the deletion of a device in Infrahub and of the task template in Semaphore, in their own web pages;
- the restore of the backup, in the Styrmin UI;
- the device back in Infrahub and the task template back in Semaphore.

Covers need 1 for this demo.

**Why this priority**: backing up and restoring a whole environment is one of the features the beta audience needs to see, and its waits are the longest of the four demos.

**Independent Test**: on a demo stack that `uv run invoke start` just created, record demo 3 alone and play the video. This is also the check for FR-002.

**Acceptance Scenarios**:

1. **Given** an environment backup of the environment, **When** a device and the Semaphore task template are deleted and the backup is restored, **Then** both are back.
2. **Given** demo 3 recorded successfully, **When** the developer checks the output directory, **Then** it contains one MP4 file for demo 3.

---

### User Story 4 - Record the environment clone demo (Priority: P1)

The developer records demo 4. The setup, which is not recorded, creates an environment with Infrahub, deployed with the `infrahub-enterprise` driver, and Semaphore, loads two devices into Infrahub, and creates a Semaphore task template that runs a playbook listing the hosts in the Infrahub inventory. The playbook only reads the inventory and connects to no device. The recording shows:

1. The template run in the source Semaphore. The output lists two devices.
2. The environment cloned, in the Styrmin UI.
3. A third device added in the clone's Infrahub.
4. The same template run in the clone's Semaphore, without a change to any setting. The output lists three devices.
5. The template run in the source Semaphore again. The output still lists two devices.

Semaphore reaches Infrahub by the short name of Infrahub's service, so Semaphore's settings name no specific deployment. Styrmin creates `ExternalName` aliases so that deployments in the same environment reach each other by short service name ([`service_aliases.py`](../../backend/styrmin_backend/agent/tasks/service_aliases.py)). Covers need 1 for this demo.

**Why this priority**: the clone demo shows that a cloned environment works on its own, with no change to its applications' settings.

**Independent Test**: on a demo stack that `uv run invoke start` just created, record demo 4 alone and play the video.

**Acceptance Scenarios**:

1. **Given** an environment where Semaphore reads its inventory from Infrahub, **When** the environment is cloned and a device is added in the clone's Infrahub, **Then** the clone's Semaphore lists the new device without any change to its settings, and the source Semaphore does not list it.

---

### User Story 5 - Record all four demos with one command (Priority: P1)

A developer starts the demo stack and runs one command. Each demo creates its own environment and deployments through the SDK, records its feature in the UI, then deletes what it created. The developer receives one video for each demo. When one demo fails, the others still run, and the command lists the result of each demo. Covers needs 6, 8 and 9.

**Why this priority**: this is the PRD's P1 journey. The developer runs it before each presentation, so that the videos match the current UI.

**Independent Test**: on a demo stack that `uv run invoke start` just created, run the record command for all demos and check the output directory and the environments left on the cluster.

**Acceptance Scenarios**:

1. **Given** a demo stack that `uv run invoke start` just created and ffmpeg on the PATH, **When** the developer runs the record command, **Then** the output directory contains four MP4 files of 3 minutes or less, and none of the environments that the demos created remain.
2. **Given** a step of one demo fails, **When** the command records all demos, **Then** the other demos still run, the command lists the result of each demo and names the failing step and its error, the failed demo leaves no video and keeps its environments, and the command exits with an error.
3. **Given** ffmpeg is not on the PATH or the demo stack does not respond, **When** the developer runs the record command, **Then** the command stops before any setup with a message that names what is missing.

---

### User Story 6 - Re-record one demo after a failed run (Priority: P2)

After a UI change, the developer runs the command for one demo and receives a new video for that demo only. An earlier failed run of that demo does not block it. Covers needs 7 and 10.

**Why this priority**: this is the PRD's P2 journey. It saves the time of recording the other three demos when only one is broken.

**Independent Test**: make demo 3 fail once so that it leaves its environment, then record demo 3 alone.

**Acceptance Scenarios**:

1. **Given** demo 3 failed in an earlier run and left its environment, **When** the developer records demo 3 only, **Then** the command deletes the leftover environment, records demo 3 and writes only its video.

---

### Edge Cases

- **A new Infrahub release needs a newer Helm chart**: the `infrahub` driver pins the Infrahub Helm chart 4.33.2 ([`driver.styrmin.yml`](../../driver/examples/infrahub/driver.styrmin.yml)). After someone updates the versions file, demo 1 fails until the driver is updated.
- **Nobody updates the versions file**: demo 1 keeps recording the older versions.
- **An earlier run failed and left its environments**: the next run of that demo deletes them before its setup (FR-009).
- **An environment has a demo's name, and the command did not create it**: the command asks before it deletes it, and stops before any change without a yes (FR-009).
- **The developer presses Ctrl-C**: the command prints the summary so far and the environments it keeps (FR-023).
- **The encoding fails after a recording of up to 10 minutes**: the raw recording stays, and the command can encode it again (FR-024).
- **ffmpeg is missing or the demo stack does not respond**: the command stops before any setup (FR-012).
- **A step fails during a recording**: the demo keeps no partial video, so a video in the output directory is always complete (FR-010).
- **Environment names are unique on a cluster** ([`models.py`](../../backend/styrmin_backend/db/models.py)): a demo cannot create its environment while an earlier run's environment with the same name exists, which is why FR-009 deletes leftovers first.
- **Two environments at once**: during demo 4, the source and the clone both run Infrahub and Semaphore. On a Linux host with 31,465 MiB of memory, the memory in use rose to at most 26,993 MiB during demo 4 ([spike notes](spike-notes.md#memory-during-the-run)). Since the review, the command deletes the environments while ffmpeg encodes, so that the two do not add up.
- **A clone's aliases point to the source**: a clone restored the source's alias Services, which point to the source's namespaces (research R-013). This was the defect [#530](https://github.com/opsmill/styrmin/issues/530), fixed by [PR #531](https://github.com/opsmill/styrmin/pull/531). With a Styrmin image built before that fix, demo 4 shows two devices in the clone instead of three, and its error names the fix.
- **A demo stack where the developer changed things by hand**: the demos create their own environments and deployments on top of what `uv run invoke start` creates, and touch nothing else. Environments with other names are left as they are.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to record all four demos with one command, or one demo by naming it.
- **FR-002**: Each demo MUST create what it needs through the SDK before the recording starts, on top of what `uv run invoke start` creates, and MUST NOT depend on another demo.
  - Verification: record demo 3 alone on a demo stack that `uv run invoke start` just created.
- **FR-003**: Each demo MUST perform every step in the Styrmin UI through the E2E page objects.
  - Verification: the demo scripts contain no selector for a Styrmin page.
- **FR-004**: Each video MUST show a title at the start of each step, and a cursor and a highlight on each element that the script clicks or types into. The demos MUST type text one key at a time. The E2E suite MUST keep filling fields in one step.
- **FR-005**: The video MUST speed up each wait for the cluster and show a label during the sped-up part that gives the real duration and the speed-up factor.
- **FR-006**: The two Infrahub versions of demo 1 MUST be set in one file that someone updates by hand.
- **FR-007**: The command MUST write each video as an MP4 file with H.264 at 1920×1080, to a directory that git ignores.
- **FR-008**: Each demo MUST use fixed, readable names for its environments and deployments, for example `network-lab`, `network-lab-clone`, `infrahub` and `semaphore`.
- **FR-009**: After a successful recording, a demo MUST delete the environments it created. Before its setup, a demo MUST delete any environment with its names that an earlier run left behind. The command MUST NOT delete an environment with a demo's name that it did not create, unless the developer confirms it on the terminal.
- **FR-010**: When a step fails, the demo MUST stop, report the step and the error, keep no partial video and keep the environments it created.
- **FR-011**: When the command records all demos, a failure in one demo MUST NOT stop the others. The command MUST list the result of each demo and exit with an error if any demo failed.
- **FR-012**: Before any setup, the command MUST check that ffmpeg and ffprobe are on the PATH, that the Chromium build of the installed Playwright exists, that docker is on the PATH when a demo needs the demo Semaphore image, that the kube context `vcluster-docker_styrmin` reaches the demo stack, that the demo stack responds and accepts the admin login, and what FR-001 to FR-019 need from the stack, and stop with a message that names what is missing. A rejected login MUST be named as such.
- **FR-013**: In demo 4, Semaphore MUST reach Infrahub by the short name of Infrahub's service, so that Semaphore's settings name no specific deployment.
  - Verification: the clone's Semaphore lists the device added in the clone's Infrahub.
- **FR-014**: The steps in Infrahub's and Semaphore's own web pages MUST be performed through page objects for those pages, used by the demos only: in Infrahub, add, delete and list devices; in Semaphore, run a task template, read its output and delete a task template.
- **FR-015**: The demo Semaphore image MUST contain the `opsmill.infrahub` Ansible collection and the `infrahub-sdk` Python package, and the playbook and inventory file that demo 4 runs. It MUST be built locally and loaded into the vCluster, and MUST NOT be published to a registry.
- **FR-016**: *Dropped on 2026-10-20.* It asked `test_environment_clone_lifecycle` to check that each `ExternalName` alias in the clone points to a namespace of the clone. [PR #531](https://github.com/opsmill/styrmin/pull/531) adds that check to the same test on `develop`, so this branch does not change the test ([E2E evidence](e2e-evidence.md#the-defect-is-fixed-by-531-which-carries-its-own-alias-check)).
- **FR-017**: The [local demo guide](../../dev/guides/local-demo.md) MUST gain a "Recording the demos" section that covers the prerequisites, the commands, the versions file, the output directory and what to do after a failed demo.
- **FR-018**: The GraphQL API, SDK, `styrminctl`, frontend, database schema, drivers and error types MUST NOT change.
- **FR-019**: Demos 3 and 4 MUST deploy Infrahub with the `infrahub-enterprise` driver, which their setup loads from the drivers that the Styrmin image contains, because the `infrahub` driver cannot take an environment backup (Clarifications, planning session).
- **FR-020**: Each video MUST keep a caption that names the application on screen and its environment, MUST show each result for at least 5 s, and MUST end on a closing card that gives the demo's title and what it showed. A sped-up label MUST read as the wait, its real duration and the speed-up factor, for example "The upgrade runs (2 min 55 s, shown 44× faster)".
- **FR-021**: The command MUST write a file of chapter start times next to each MP4, for example `1-deploy-upgrade.chapters.txt`.
- **FR-022**: The command MUST accept several demos, and MUST offer to only delete the demos' environments.
- **FR-023**: On Ctrl-C, the command MUST print the summary of the demos so far with the environments it keeps, close the Styrmin client and the browser, and exit with code 130.
- **FR-024**: When the encoding fails, the command MUST keep the raw recording and the plan of the video, and MUST be able to encode them again without recording again.
- **FR-025**: The command MUST print a line when each wait starts, a line every minute while it lasts, the sub-steps of each setup, and how long each demo usually takes. Each failed line of the summary MUST give a next step.

### Key Entities

All the entities are existing ones. The demos add no Styrmin entity.

- **Environment**: each demo creates its own, with a fixed name, and deletes it after a successful recording. Environment names are unique on a cluster.
- **Deployment**: each demo environment contains one Infrahub deployment and one Semaphore deployment. Demos 1 and 2 use the `infrahub` and `semaphore` drivers that the demo stack loads; demos 3 and 4 use the `infrahub-enterprise` driver, which their setup loads (FR-019).
- **Service**: Semaphore reaches Infrahub's `infrahub` service on port 8000 ([`infrahub driver`](../../driver/examples/infrahub/driver.styrmin.yml)). Each deployment has its own namespace, and Styrmin creates `ExternalName` aliases so that deployments in the same environment reach each other by short service name. The docs say that applications in a clone reach each other in the clone and not in the source ([`ingress-and-networking.md`](../../docs/docs/concepts-and-architecture/ingress-and-networking.md#networking-between-applications)).
- **Application version and application driver version**: the `infrahub` driver accepts Infrahub versions `>=1.5,<2.0` and pins the Infrahub Helm chart 4.33.2. The process for choosing a driver version is described in [Selecting a driver version](../../docs/docs/drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading).
- **Image override and replica override**: used in demo 2 ([`image-overrides.md`](../../docs/docs/concepts-and-architecture/image-overrides.md), [`replica-overrides.md`](../../docs/docs/concepts-and-architecture/replica-overrides.md)).
- **Task and step**: shown in demo 1 ([`status-reporting.md`](../../docs/docs/concepts-and-architecture/status-reporting.md#steps-from-status-reports)).
- **Environment backup and environment restore**: used in demo 3. The Infrahub drivers back up their Neo4j database and their storage disk, and the `semaphore` driver backs up its Postgres database. The Neo4j backup needs Neo4j Enterprise, which only the `infrahub-enterprise` driver deploys (research R-007) ([`backups-and-restores.md`](../../docs/docs/concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment)).
- **Environment clone and counterpart deployment**: used in demo 4 ([`backups-and-restores.md`](../../docs/docs/concepts-and-architecture/backups-and-restores.md#cloning-an-environment)).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Starting from a demo stack that `uv run invoke start` just created, one command produces all four videos, with no step performed in a browser by hand.
- **SC-002**: Each video lasts 3 minutes or less, including the sped-up waits.
- **SC-003**: Each video plays in Keynote, PowerPoint and Google Slides without conversion.
- **SC-004**: A fix for a change to a Styrmin page is made in one place only, and it also repairs the E2E tests that use the same page. Since the review, E2E tests call the Styrmin page-object methods that the demos added, so a UI change that breaks one of them fails an E2E test.
- **SC-005**: After a successful run of all four demos, none of the environments the demos created remain on the cluster.

## Assumptions

- The beta audience knows Infrahub.
- A laptop that runs the demo stack has enough memory for two environments with Infrahub and Semaphore at the same time, which demo 4 needs during the clone. Measured on one Linux host with 31,465 MiB and no swap: the memory in use rose to at most 26,993 MiB, and the available memory fell to 4,472 MiB ([spike notes](spike-notes.md#memory-during-the-run)). How much a laptop with less memory can run is not known.
- The Infrahub Helm chart 4.33.2 that the `infrahub` driver pins runs Infrahub 1.10.11 and 1.11.7. Its own default is 1.11.2. Verified on 2026-10-18 (research R-015, [spike notes](spike-notes.md)).
- The Infrahub Enterprise Helm chart 4.19.2 that the `infrahub-enterprise` driver pins runs Infrahub 1.11.7. Its own default is 1.11.2. Verified on 2026-10-18 (research R-007, [spike notes](spike-notes.md#infrahub-enterprise-1117-backs-up-and-restores)).
- Semaphore can use the `opsmill.infrahub` inventory plugin once its image contains the collection and `infrahub-sdk`. Verified: demo 4 reads 2, 3 and 2 devices from the inventory ([spike notes](spike-notes.md#demo-4-recorded-tasks-t039-and-t040)).
- The vCluster can run a locally built Semaphore image the same way it runs the locally built Styrmin image. Verified: demos 2 to 4 run `styrmin-demo/semaphore:v2.16.47` ([spike notes](spike-notes.md)).

## Out of Scope

- Videos for the website and screenshots for the docs.
- A CI job that records the demos for each release, because that would be a CI change.
- Terminal demos, such as `styrminctl deployments apply`.
- Demos of editing a cluster's config, of the `infrahub-mcp` driver, which needs a running Infrahub instance, and of user and group administration.
- Recorded voice, and captions over the page other than the one that names the application and its environment (FR-020).
- Publishing the Semaphore image to a registry.
- Finding the latest Infrahub version automatically.

## Related Decisions

- [ADR-055](../../dev/adr/0055-environment-backup-parent-records.md): environment backup records.
- [ADR-056](../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md): environment clone and cross-target restore.
- [ADR-057](../../dev/adr/0057-post-render-component-overrides.md) and [ADR-070](../../dev/adr/0070-replica-overrides-and-retired-parameters.md): component overrides.
