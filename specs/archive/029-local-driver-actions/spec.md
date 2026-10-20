# Feature Specification: Run the Actions of Driver Versions Loaded from a Local Directory

**Feature Branch**: `fac/actions-local-drivers-qlmex`

**Created**: 2026-10-19

**Status**: Extracted

**Input**: PRD "Run the actions of drivers loaded from a local directory" — [opsmill/styrmin#372 (comment)](https://github.com/opsmill/styrmin/issues/372#issuecomment-6262219647). Seed issue: [#372](https://github.com/opsmill/styrmin/issues/372). Builds on [ADR-053](../../dev/adr/0053-driver-version-provenance-fingerprint.md) (provenance fingerprint), [ADR-059](../../dev/adr/0059-driver-action-api-tokens.md) (action token), [ADR-060](../../dev/adr/0060-steps-and-derived-task-result.md) (steps and derived task result), [ADR-079](../../dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md) and [ADR-080](../../dev/adr/0080-action-deployments-keyed-by-driver-directory.md) (action registration of git driver versions, spec 028).

## Context

An operator loads an **application driver version** either from git (`styrminctl drivers load-version`) or from a local directory on the server (`styrminctl drivers load-local-version`). The user documentation tells operators to load the bundled drivers from `/styrmin/drivers/<name>` with `load-local-version` ([`loading-drivers.md`](../../docs/docs/drivers/loading-drivers.md)). The Styrmin image holds them at that path ([`docker/Dockerfile`](../../docker/Dockerfile), `COPY driver/examples /styrmin/drivers`).

When a driver version is loaded, Styrmin stores its declared **actions** as `Action` rows. It registers a Prefect flow for each action only when the driver comes from git: the registration is gated on `isinstance(driver_object.source, GitSource)` in `load_application_driver_from_object` ([`services/applications.py`](../../backend/styrmin_backend/services/applications.py)), and `ActionsWorkflowBuilder` accepts only a `GitSource`, because the flow clones the repository when it runs ([`services/user.py`](../../backend/styrmin_backend/services/user.py)).

When a **hook** runs, Styrmin looks up the registered flow of each **mode** in seven places: two in `instantiate_application` ([`services/applications.py`](../../backend/styrmin_backend/services/applications.py)) and five in the create and upgrade remediations ([`services/reconciliation/remediation.py`](../../backend/styrmin_backend/services/reconciliation/remediation.py)). A lookup that finds nothing returns `None`, and the hook is skipped without an error. For an upgrade, a missing `upgrade`/`core` flow makes the remediation fall back to a plain update.

The bundled drivers `infrahub`, `infrahub-enterprise`, `semaphore`, `simple-app` and `slurpit` each declare three actions: `pre_setup` (`setup`/`pre`), `post_setup` (`setup`/`post`) and `upgrade` (`upgrade`/`core`). Loaded from a local directory, none of them runs. A new deployment reaches `running` without its setup actions, and an Infrahub upgrade does not stop the components, run `infrahub upgrade` and restart them, while the task reports `success` ([#372](https://github.com/opsmill/styrmin/issues/372), steps 1 to 4).

The **provenance fingerprint** of a local driver version, `content_hash`, is the SHA-256 of `driver.styrmin.yml`, the values template and, when the driver declares actions, `actions.py` ([`services/driver/hash.py`](../../backend/styrmin_backend/services/driver/hash.py)). It and the version's `source_path` are already stored.

This feature registers the actions of local driver versions, runs each action from the version's `source_path` in the Styrmin agent pod, where the agent's Prefect process worker runs every action, checks before the action runs that the files at that path still have the version's provenance fingerprint, and makes a hook fail instead of being skipped when its declared action has no registered flow.

## Clarifications

### Session 2026-10-19 (autonomous, from the PRD and the code on `develop` at `a5ec9446`)

The PRD leaves one question open and some points that the code answers. These answers were taken without the user so that later phases do not reopen them.

- Q: Where is "spec 029 demo 1" defined (PRD open question; SC-004 and assumption A-4 depend on it)? → A: Outside this repository, as the PRD states. This spec's directory number, 029, is the next free number in `specs/` and has no relation to it. SC-004 is checked by the owners of spec 029 demo 1 and of INFP-726 after this change ships. Inside this repository, the evidence for SC-004 is SC-001 for the `infrahub` driver and the E2E test of user story 1. SC-004 is not a condition for merging this change.
- Q: Which hook and mode pairs does FR-005 cover? → A: Every pair that a hook looks up today: `setup`/`pre`, `setup`/`post`, `upgrade`/`pre`, `upgrade`/`core` and `upgrade`/`post`. Styrmin looks up the `upgrade`/`pre` and `upgrade`/`post` flows only when the target version declares an `upgrade`/`core` action, and this feature keeps that rule (see Edge Cases).
- Q: After an upgrade fails because the target version's action is not registered, how does the operator "run the upgrade again" (PRD journey P3, SC-003)? → A: Today they cannot. After a failed upgrade, the new **instance** stays the deployment's active instance, so a second `updateDeploymentVersion` call with the same target finds no change (`_update_is_noop` in [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py)) and starts no task. P3 and SC-003 require that the same request starts the upgrade again, so FR-007 states it. The plan chooses how.
- Q: Two local driver versions loaded from two paths can have the same files, and so the same provenance fingerprint. Whose `actions.py` does each one run? → A: Each version runs the `actions.py` at its own `source_path` (FR-002). The registration of one must not replace the registration of the other, as ADR-080 already ensures for git driver directories.
- Q: Which image does an error name when the action sets no `image:`? → A: The image that runs the action's Job: the action's `image:` when it sets one, and otherwise the default image of the work pool that runs actions (`user-work-pool`). Amended after implementation: actions run in the agent pod, so the action's `image:` has no effect (see the implementation session below). The error still names the action's `image:` when it sets one, and otherwise the work pool's default image. In a standard install, that default image is the image the agent runs.
- Q: Does the check of FR-003 also run for driver versions loaded from git? → A: No. A git driver version's flow clones the repository at the version's commit, so its files cannot differ from the loaded version. Git driver versions change only through FR-005 and FR-006.
- Q: Can `load-local-version` check, when the driver is loaded, that the action's image holds the driver? → A: No. The server cannot read the image of a Job that does not exist yet. The check happens when the action runs (FR-003, FR-004), and `load-local-version` keeps its arguments and output. Amended after implementation: actions run in the agent pod, and the server cannot read the files in that pod either.

### Session 2026-10-19 (implementation)

These answers come from the implementation, its E2E runs and its review. The user made the decisions marked as theirs.

- Q: Where does an action run? → A: As a process in the Styrmin agent pod, for driver versions loaded from git and from a local directory. The agent runs a Prefect `ProcessWorker` on `user-work-pool` ([`entrypoint/combined.py`](../../backend/styrmin_backend/entrypoint/combined.py), [`helm/agent/values.yaml`](../../helm/agent/values.yaml)), so an action's `image:` has no effect today. The E2E tests of user story 2 confirmed it. The user decided to keep the image text in the errors of FR-003 and FR-004 and to correct the documentation. Running an action in its `image:` is a follow-up ([follow-ups.md](follow-ups.md)).
- Q: Can an operator delete a deployment whose create failed at `hook:setup:pre`, as the edge cases advise? → A: Not before this change. `deleteDeployment` failed with an internal error, because such a create never writes its `StyrminDeployment`. The user asked to fix it in this change (FR-011, task T052).
- Q: How does a client learn that an upgrade request failed the request check of FR-007? → A: The request returns a failed task. The review found that the SDK's `apply` and the CLI reported it as a success. FR-010 makes them report the failure.
- Q: What happens when an action calls `execute_commands` a second time on the same deployment? → A: Before this change, the second call failed, because the Job of the first call was never deleted. Local actions now run, so the second upgrade of an `infrahub`, `infrahub-enterprise` or `simple-app` deployment would fail. The review found it, and FR-012 fixes it.

## User Scenarios & Testing *(mandatory)*

The PRD defines three user journeys. Each story below is one of them and can be tested on its own. All three ship in one change.

### User Story 1 - Deploy and upgrade an application from a bundled driver loaded from a local directory (Priority: P1)

An operator loads `/styrmin/drivers/infrahub` with `styrminctl drivers load-local-version`, creates a deployment, then upgrades it to a newer application version, whose driver version was also loaded from a local directory. Every declared action runs: `pre_setup` and `post_setup` at creation, and `upgrade` at the upgrade. Every action runs as a process in the Styrmin agent pod, as for a driver version loaded from git, and an action's `image:` has no effect.

**Why this priority**: This is the defect of [#372](https://github.com/opsmill/styrmin/issues/372). The documented way to load the bundled drivers produces deployments whose setup and upgrade actions never run, and nothing reports it. The INFP-726 sandbox rebuild relies on the Infrahub driver's seeding at setup and on its upgrade action.

**Independent Test**: Load a driver from a local directory whose `pre_setup`, `post_setup` and `upgrade` actions each log a marker, deploy it, then upgrade the deployment. Each marker appears in the logs of its action, and each action is part of a hook step of the task.

**Acceptance Scenarios**:

1. **Given** a Styrmin installation whose agent image holds `/styrmin/drivers/infrahub`, **When** the operator loads the driver with `load-local-version` and creates a deployment, **Then** the `pre_setup` and `post_setup` actions run as hook steps of the task, and the deployment reaches `running` only after they succeed.
2. **Given** that deployment, **When** the operator upgrades it to a newer application version whose driver version was loaded from a local directory, **Then** the `upgrade` action runs as a hook step, and the upgrade is not applied as a plain update. A change of driver version alone, at the same application version, is an update and runs no upgrade action, as today.
3. **Given** the bundled Semaphore driver, **When** the operator loads it with `load-local-version /styrmin/drivers/semaphore`, **Then** Prefect holds three `User Action:` flows registered for this driver version, one for each declared action.
4. **Given** a local driver whose action sets `image:`, **When** that action runs, **Then** it runs in the agent pod like every other action, and its `image:` has no effect.
5. **Given** a deployment whose upgrade action calls `execute_commands`, **When** the operator upgrades it a second time, **Then** the action replaces the Job of the earlier call and the upgrade succeeds (FR-012).

---

### User Story 2 - A driver author who changes a local driver gets an error instead of old code (Priority: P2)

A driver author edits a driver in a local directory and loads it again. When a hook runs, either the edited code runs, or the action fails with an error that says what is wrong and how to fix it. The same check protects an operator who upgrades Styrmin: when the bundled driver at a path is no longer the version that was loaded, its action fails instead of running the code of another driver version.

**Why this priority**: Without this check, an action would run whatever `actions.py` is at the path in the agent pod. When the agent's image was built before an edit, or a Styrmin upgrade ships a newer bundled driver at the same path, that file is not the one the author or operator loaded, and they would run other code without knowing it.

**Independent Test**: Load a local driver, change its `actions.py` at the path in the agent pod so that it differs from the loaded version, and run a hook. The hook step and the task fail, and the error names the path, the image and both provenance fingerprints.

**Acceptance Scenarios**:

1. **Given** an author who loads a driver from a path that the server and the agent both hold, and whose `actions.py` at that path in the agent pod differs from the loaded file (for example, the agent's image was built before the edit), **When** a hook runs, **Then** the action, the hook step and the task fail. The error names the path, the image and both provenance fingerprints, and tells the author to rebuild the image and load the driver again.
2. **Given** an author on the dev stack, where the server and the agent bind-mount `driver/examples`, **When** they edit `actions.py`, load the driver again and deploy it, **Then** the edited action runs without an image rebuild.
3. **Given** a driver copied only into the server pod, so that the agent pod does not hold it, **When** a hook runs, **Then** the action, the hook step and the task fail, and the error names the missing path and the image.
4. **Given** an operator who loaded `/styrmin/drivers/infrahub`, then upgraded Styrmin to a release that ships a newer Infrahub driver at the same path, **When** they create a deployment from the version they loaded before the Styrmin upgrade, **Then** its setup action fails with the error of scenario 1 and runs no code of the newer driver.

---

### User Story 3 - A hook whose action is not registered fails, and loading the driver again repairs it (Priority: P3)

A driver version loaded before this fix, or one whose Prefect registration was deleted or failed, declares actions that have no registered flow. A hook of that version fails with an error that tells the operator to load the driver again. After they load it again, the hook runs.

**Why this priority**: Without it, a version loaded before the fix keeps skipping its hooks without an error, and an operator has no way to repair it short of changing the driver's files.

**Independent Test**: Load a driver, delete its registered action flows in Prefect, and upgrade a deployment of it. The task fails with an error that names the version, the hook, the mode and the action. Load the driver again and run the same upgrade again: the upgrade action runs.

**Acceptance Scenarios**:

1. **Given** a local driver version loaded before the fix and a deployment created from it, **When** the operator upgrades the deployment, **Then** the hook step and the task fail. The error names the driver version, the hook, the mode and the missing action, and tells the operator to load the driver again.
2. **Given** the operator who then loads the same driver again, **When** they request the same upgrade again, **Then** a new task starts and the upgrade action runs.
3. **Given** a driver version loaded from git whose action flows were deleted in Prefect, **When** a deployment of it is created or upgraded, **Then** the hook step and the task fail with the same error, and loading the driver again from the same commit repairs it.
4. **Given** a driver version whose declared actions all have a registered flow, **When** the operator loads the driver again, **Then** Styrmin changes no registration.
5. **Given** the operator of scenario 1, who requests the upgrade with `styrminctl deployments update-version` or `styrminctl deployments apply`, **When** the request returns the failed task, **Then** the CLI prints the task message and exits with status 1, and the SDK's `apply` reports the deployment as failed (FR-010).
6. **Given** a deployment whose create failed at `hook:setup:pre`, before its `StyrminDeployment` was written, **When** the operator deletes it, **Then** the deployment is deleted, and the operator can create it again (FR-011).

---

### Edge Cases

- The files at the path change after the version was loaded: someone edits a file, a Styrmin upgrade ships a newer bundled driver at the same path, or the agent's image was built before an edit. The action fails (FR-003). An upgrade runs the actions of the target version, which was just loaded, so a Styrmin upgrade followed by a driver load does not break deployment upgrades.
- Only the values template changes. The action still fails, because the provenance fingerprint covers `driver.styrmin.yml`, the values template and `actions.py`. This is intended: the files at the path are no longer the loaded version.
- An action sets `image:`. The setting has no effect, because the agent runs every action in its own pod. When the check fails, the error names that `image:` value although the action did not run in it. The user decided to keep this text, and running actions in their `image:` is a follow-up.
- The agent pod does not hold the driver at the path, for example because the driver was copied only into the server pod. The action fails (FR-004).
- A version was loaded before the fix, or its registration was deleted or failed. Its hooks fail (FR-005), and loading the driver again repairs it (FR-006).
- A version was loaded before the fix and its files at the path have changed since, for example after a Styrmin upgrade. Loading the driver again creates a new version with the new fingerprint and registers its actions; it does not repair the old version. A hook of the old version keeps failing with the FR-005 error, and the operator uses the new version instead.
- A deployment was created before the fix and its setup actions never ran. Styrmin does not run them now. The release note tells operators about it (FR-008).
- A create whose setup action is not registered fails, and the deployment does not reach `running`. After loading the driver again, the operator deletes the deployment and creates it again, as for any failed create (FR-011). While such a deployment is `PENDING` or `DEPLOYING`, the delete is refused with `DeploymentRolloutInProgressError`, because its change can still write the `StyrminDeployment`.
- A create made the deployment's namespace, but writing its `StyrminDeployment` failed. A delete marks the deployment deleted and leaves the namespace. This is recorded as a follow-up.
- A driver is loaded from a relative local path. Styrmin neither makes the path absolute nor refuses it. Its actions are expected to fail the check, and its registration key can equal the key of a git driver directory with the same text. This is recorded as a follow-up.
- An action calls `execute_commands` on a deployment whose earlier call left its Job. Styrmin deletes the earlier Job and its pods, then creates the new one (FR-012).
- Two local versions loaded from two paths with the same files have the same provenance fingerprint. Each runs the `actions.py` at its own path (FR-002).
- A target version declares `upgrade`/`pre` or `upgrade`/`post` actions and no `upgrade`/`core` action. Styrmin keeps today's behaviour: the upgrade is applied as a plain update and those actions do not run. No driver in this repository declares this combination. It is out of scope and is recorded as a follow-up.
- An action's registration is deleted between the request and the moment the task plans its work. The hook step and the task fail with the FR-005 error.
- A local driver that declares actions is loaded from a path that contains `{` or `}`. The load is refused (FR-001), because Prefect would replace `{{ ... }}` in that path with values such as the action token before the check of FR-003 reads it. A driver without actions loads from such a path as today.
- The check of FR-003 or FR-004 fails during an upgrade. The task fails, and the new instance stays the deployment's active instance, as after any failed upgrade. A second request for the same upgrade is then a no-op, and a request for another driver version at the same application version runs as an update, so the upgrade action does not run. This is true of every failed upgrade today. This feature documents the recovery and does not change it; a follow-up issue records it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When an application driver version is loaded from a local directory and declares actions, Styrmin MUST register a flow for each action, as it does for a version loaded from git.
  - Styrmin MUST refuse such a load when its path contains `{` or `}`, with an error that names the path, because Prefect replaces `{{ ... }}` in the inputs of the step that checks the files ([research R-005](research.md#r-005-prefect-templates-in-pull-step-inputs)).
  - Verification: load `/styrmin/drivers/semaphore` locally. Prefect then holds three `User Action:` deployments tagged with the version's provenance fingerprint. A copy of a driver with actions at a path that contains `{` is refused.
- **FR-002**: When an action of a locally loaded version runs, Styrmin MUST run the `actions.py` that is at the version's `source_path` in the Styrmin agent pod, where the agent's Prefect process worker runs every action. An action's `image:` has no effect today (see Clarifications, implementation session). Each local version MUST run the `actions.py` at its own `source_path`, also when another version loaded from another path has the same files.
  - Verification: E2E with a local driver whose `post_setup` action logs a marker. The marker appears in the action's logs.
- **FR-003**: Before an action of a locally loaded version runs, Styrmin MUST compute the provenance fingerprint of the driver files at the `source_path` where the action runs (the agent pod): `driver.styrmin.yml`, the values template and `actions.py`. If it differs from the version's stored provenance fingerprint, Styrmin MUST fail the action, the hook step and the task, without importing or running the `actions.py` at the path. The error MUST name the path, the image (the action's `image:` when it sets one, otherwise the work pool's default image) and both provenance fingerprints, and tell the user to rebuild the image or load the driver again.
  - Verification: E2E for user story 2. Copy a driver into the server pod and load it, put an edited copy at the same path in the agent pod, and deploy it. The hook step fails with this error.
- **FR-004**: When the driver files are not at the `source_path` in the agent pod, Styrmin MUST fail the action, the hook step and the task. The error MUST name the path and the image.
  - Verification: unit test with a `source_path` that does not exist; E2E for user story 2 with a driver copied only into the server pod.
- **FR-005**: When a driver version declares an action for a hook and mode and no registered flow exists for it, Styrmin MUST fail the hook step and the task instead of skipping the hook. When the missing flow is found while the task plans its work, before the hook step would start, Styrmin MUST still record the error on a failed hook step of the task. An upgrade MUST NOT fall back to a plain update when the target version declares an `upgrade`/`core` action. This applies to versions loaded from git and from a local directory. The error MUST name the driver version, the hook, the mode and the action, and tell the operator to load the driver again.
  - Verification: delete a version's Prefect deployments, then upgrade a deployment of it. The task fails, and its error names the version, the hook, the mode and the action.
- **FR-006**: Loading a driver again MUST register any of its declared actions that have no registered flow, both when the load creates a new version and when it finds an existing one. Styrmin MUST decide that a flow is missing with the same lookup that hooks use, so it does not change a registration that hooks already find.
  - Verification: load a driver, delete its Prefect deployments and load it again. The registrations exist again, and an upgrade runs the upgrade action.
- **FR-007**: After an upgrade fails under FR-005, a request for the same upgrade MUST start a new task once the driver has been loaded again, without the operator first changing the deployment in another way.
  - Verification: the E2E or functional test of user story 3, scenarios 1 and 2.
- **FR-008**: The release note of this change MUST tell operators to load their local drivers again, and that deployments created from local driver versions before the fix never ran their setup actions.
  - Verification: a towncrier fragment for #372 in `changelog/`.
- **FR-009**: The same change MUST update the documentation (Constitution §VII):
  - [`loading-drivers.md`](../../docs/docs/drivers/loading-drivers.md): the driver must be at the same path in the agent pod as on the server, an action's `image:` has no effect, and the page lists the errors of FR-003, FR-004 and FR-005 with how to fix each one;
  - the dev-stack guide [`driver-iteration.md`](../../dev/guides/driver-iteration.md): after editing an action, the author loads the driver again; the dev stack bind-mounts the drivers into the server and the agent, so no image rebuild is needed;
  - a new ADR for the actions of local driver versions, which records the decisions below and the rejected alternatives;
  - an amendment note in [ADR-053](../../dev/adr/0053-driver-version-provenance-fingerprint.md), which today states that a repeated load does not register actions again and that a historical deployment resolves its actions to the bytes it shipped with;
  - [`CONTEXT.md`](../../CONTEXT.md), entries **Action** and **Provenance fingerprint**.
  - Verification: review of the changed pages.
- **FR-010**: When an upgrade request returns a failed task under FR-005, the SDK's `apply` MUST report the deployment as failed with the task message, and MUST NOT wait on the deployment's status. `styrminctl deployments apply` and `styrminctl deployments update-version` MUST print the task message and exit with a non-zero status. The SDK's `update_version` keeps returning the task. Added after the review.
  - Verification: SDK and CLI unit tests in `python_sdk/tests/test_deployments.py` and `cli/tests/test_deployments.py`.
- **FR-011**: Styrmin MUST delete a deployment whose create failed before its `StyrminDeployment` was written. While such a deployment is `PENDING` or `DEPLOYING`, Styrmin MUST refuse the delete with a typed error. Added at the user's request during implementation (task T052).
  - Verification: `backend/tests/unit/services/test_delete_deployment_without_styrmin_deployment.py`, `backend/tests/functional/graphql/test_delete_deployment.py`, and the E2E tests of user stories 2 and 3, which delete their failed deployments.
- **FR-012**: An action MUST be able to call `execute_commands` more than once on the same deployment. Before it creates the Job, Styrmin deletes a Job of an earlier call and its pods, and it keeps the Job name that is built from the record id ([ADR-073](../../dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md)). Added after the review.
  - Verification: `backend/tests/unit/agent/test_run_job_replaces_earlier_job.py`, and the E2E test of user story 3, whose second upgrade runs a new Job.

### Constraints

- No change to the GraphQL schema: the errors use the existing errors list of the step ([ADR-060](../../dev/adr/0060-steps-and-derived-task-result.md)).
- No change to the database schema: the provenance fingerprint, the `source_path` and the declared actions are already stored.
- No change to the Helm charts or to the work pool's job template.
- No change to the frontend. `load-local-version` keeps its arguments. The SDK and the CLI change only in how they report a failed upgrade task (FR-010, added after the review).
- No new dependency.
- Actions keep using the action token ([ADR-059](../../dev/adr/0059-driver-action-api-tokens.md)).

### Key Entities

All of these entities exist today. The change adds no entity and no column.

- **Application driver version**: its `source_path` and provenance fingerprint (`content_hash` for a local version) are already stored. Styrmin now also uses them when an action of a local version runs.
- **Action**: the declared actions are already stored with the version. Styrmin now compares them with the registered flows to find a missing registration.
- **Hook** and **mode**: the lifecycle slot and the phase in which an action runs. Unchanged.
- **Step**: the hook step records the new errors in its existing errors list.
- **Task**: ends as failed when its hook step fails, because its **task result** is derived from its steps.
- **Provenance fingerprint**: Styrmin now also computes it when a local action runs, in the agent pod, before the action's code is imported, not only when a driver is loaded ([ADR-053](../../dev/adr/0053-driver-version-provenance-fingerprint.md)).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the five bundled drivers loaded from a local directory (`infrahub`, `infrahub-enterprise`, `semaphore`, `simple-app`, `slurpit`), every declared `pre_setup`, `post_setup` and `upgrade` action runs and appears as part of a step of the task. Target: 5 of 5 drivers.
- **SC-002**: No hook is skipped without an error. Every time a declared action does not run, the task ends as failed and its error names the action. Target: no skipped hooks in the reproduction steps of [#372](https://github.com/opsmill/styrmin/issues/372) or in the E2E suite.
- **SC-003**: In the scenarios of user stories 2 and 3, a user who follows the instruction in the error alone, without reading the docs or the code, gets a task that succeeds on the next run.
- **SC-004**: Spec 029 demo 1 and the INFP-726 sandbox rebuild run without a workaround, including Infrahub seeding at setup and the Infrahub upgrade action. Checked outside this repository (see Clarifications).

## Assumptions

- A-1: The Styrmin image, which the agent runs, contains the bundled drivers at `/styrmin/drivers/<name>`, the same path the server reads.
- A-2: In a Helm install, the server and the agent run images of the same Styrmin release.
- A-3: A driver's `actions.py` imports only modules that are in the agent's image. This is true for the five bundled drivers, which import only `styrmin_backend.actions` and `prefect`.
- A-4: Spec 029 demo 1 and INFP-726 load drivers only from paths in the Styrmin image, and their actions set no `image:`.

## Out of Scope

- Storing action code with the driver version.
- A shared driver volume for the agent, for drivers mounted only into the server. This becomes a follow-up issue.
- Running an action in the image that its `image:` sets. This becomes a follow-up issue.
- Running missed setup actions on deployments created before the fix, and listing those deployments. A follow-up issue is opened only if an operator asks for it.
- Any change for git driver versions other than FR-005 and FR-006.
- Validating actions offline before a driver is loaded ([#23](https://github.com/opsmill/styrmin/issues/23)).
- Running an upgrade again after its action failed (see Edge Cases).
- Running `upgrade`/`pre` and `upgrade`/`post` actions of a target version that declares no `upgrade`/`core` action (see Edge Cases).

## Decisions and Rejected Alternatives

These decisions come from the PRD, which records a grilling session with the maintainer on 2026-10-18 and 2026-10-19.

- Styrmin runs the actions of local driver versions. Refusing or flagging a local driver that declares actions was rejected, because it would block the documented way to load the bundled drivers.
- The action reads `actions.py` from the driver's path in the agent pod when it runs. Storing the action code with the driver version was rejected.
- The agent reads the path from its own pod: its image, or a volume mounted at that path. A Helm value that mounts a shared driver volume into the server and into the agent was rejected for this change and becomes a follow-up issue.
- The errors of FR-003 and FR-004 keep naming the action's `image:` or the work pool's default image, although actions run in the agent pod. This is the user's decision during implementation (2026-10-19). Changing the error text was rejected for this change.
- When the files at the path differ from the loaded version, the action fails. Running the file without a check, or with a warning, was rejected. The check compares the full provenance fingerprint, so no new data is stored.
- A declared action with no registered flow fails the hook, for git and local versions. Skipping the hook, or skipping it with a warning, was rejected.
- Loading a driver again registers its missing actions. Registering them automatically at server start was rejected, because server start would then depend on Prefect and on the driver paths being readable.
- Styrmin does not run missed setup actions on deployments created before the fix. Setup actions are written to run once on a new deployment, and Styrmin does not record which hooks were skipped.

## Sources

- Issue: [#372](https://github.com/opsmill/styrmin/issues/372); PRD: [#372 (comment)](https://github.com/opsmill/styrmin/issues/372#issuecomment-6262219647).
- Related issues: [#10](https://github.com/opsmill/styrmin/issues/10) keeps the git-only path for actions "unless user actions are also migrated to local sources"; this change does that for local versions, so #10 needs a note after it ships. [#23](https://github.com/opsmill/styrmin/issues/23) covers local driver validation.
- ADRs: [ADR-053](../../dev/adr/0053-driver-version-provenance-fingerprint.md), [ADR-059](../../dev/adr/0059-driver-action-api-tokens.md), [ADR-060](../../dev/adr/0060-steps-and-derived-task-result.md), [ADR-079](../../dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md), [ADR-080](../../dev/adr/0080-action-deployments-keyed-by-driver-directory.md).
- Prior art: [`test_driver_reload_identity.py`](../../backend/tests/e2e/test_driver_reload_identity.py) loads drivers from a local directory.
- INFP-726: the link is not known.

### Revision: Implementation Sync 2026-10-19

- Reason: the implementation showed that every driver action runs as a process in the Styrmin agent pod, and that an action's `image:` has no effect. The user decided to keep the image text in the errors and to correct the documents. The spec now says where actions run, and its dev-stack scenario says that the agent bind-mounts the drivers there.
- Added FR-010 (the SDK and the CLI report a failed upgrade task), FR-011 (delete a deployment whose create failed before its `StyrminDeployment` was written; task T052) and FR-012 (`execute_commands` called more than once on a deployment), with their scenarios and edge cases. The constraint on the SDK and the CLI is amended.
- Evidence: [e2e-evidence.md](e2e-evidence.md) and [opsmill-implement-report.md](opsmill-implement-report.md).
