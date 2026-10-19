# Feature Specification: An In-Place Restore Always Restores Into the Deployment Its Backup Was Taken Of

**Feature Branch**: `fac/remove-targetnamespace-restore-8n884`

**Created**: 2026-10-19

**Status**: Draft

**Input**: PRD "An in-place restore always restores into the deployment its backup was taken of" — [opsmill/styrmin#532 (comment)](https://github.com/opsmill/styrmin/issues/532#issuecomment-6267704797). Seed issue: [#532](https://github.com/opsmill/styrmin/issues/532), found in the review of [#531](https://github.com/opsmill/styrmin/pull/531), which fixes [#530](https://github.com/opsmill/styrmin/issues/530). The PRD's links point to `develop` at [`a5ec9446`](https://github.com/opsmill/styrmin/tree/a5ec944687e5479abd824342d557a28b4e97af9e). This spec is written against `develop` at `7f0455be`, which adds the fix for #530 (spec [030](../030-clone-service-aliases/spec.md)).

## Context

Each deployment runs in its own namespace, `styrmin-<deployment id>`. A **backup** is taken of one **instance** of a deployment, and the deployment's **backup history** holds the backups of its current and earlier instances ([ADR-062](../../dev/adr/0062-backup-history-derived-through-instances.md)). An **in-place restore** puts a backup back into the deployment it was taken of. A **cross-target restore** puts a backup into another deployment; only an **environment clone** starts one ([ADR-056](../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md)).

From the code on `develop`:

- The `createRestore` mutation takes `targetNamespace` (required) and `targetInstanceId` (optional) from the client, and passes both unchanged to the restore service and the namespace to the restore flow ([`mutation.py`](../../backend/styrmin_backend/api/schema/mutation.py), `create_restore`).
- For an in-place restore, the restore service resolves the deployment from the backup's instance. It stores the namespace and the instance it receives on the `Restore` row without comparing them with that deployment ([`service.py`](../../backend/styrmin_backend/services/backup/service.py), `create_restore`).
- The restore flow deletes the namespace it receives and restores the backup into it ([`workflows/templates/backup.py`](../../backend/styrmin_backend/workflows/templates/backup.py), `execute_velero_restore` and `execute_restore_workflow`).
- `styrminctl backups restore` builds the namespace from the deployment named with `--target-deployment` or `--target-deployment-id`, unless `--target-namespace` is given. It checks that the backup belongs to that deployment only with `--last` ([`backups.py`](../../cli/src/styrminctl/commands/backups.py), `_prepare_restore`). So `styrminctl backups restore <backup of Y> --target-deployment X` sets deployment Y to `RESTORING`, deletes deployment X's namespace and restores Y's backup into it. This follows from the code; it was not run.
- The flow uses `targetInstanceId` only for a cross-target restore, which `createRestore` never starts. So a `Restore` row can name an instance of another deployment. The Backups tab never sends `targetInstanceId`, so the rows it creates leave it empty.
- The Velero Restore and the restore flow decide in different ways whether a restore is cross-target. The Velero Restore compares namespaces: when they differ, it maps the source namespace to the target namespace and leaves out the HelmRelease and, since #531, the service aliases ([`builders/backup.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py), `build_velero_restore`). The restore flow compares deployment ids, and only a restore whose deployment ids differ writes the aliases after its recovery. So an in-place restore into another namespace ends with no service aliases in that namespace, and reports no error.
- The Backups tab always sends `styrmin-<deployment id>` ([`DeploymentDetailPage.tsx`](../../frontend/src/pages/deployments/DeploymentDetailPage.tsx)). The environment restore and the environment clone build the namespace themselves from the deployment id ([`environment.py`](../../backend/styrmin_backend/services/backup/environment.py), [`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py)).
- The user documentation says a restore starts when "you pick a backup and a target deployment (the same one or a different one)" ([`backups-and-restores.md`](../../docs/docs/concepts-and-architecture/backups-and-restores.md), "What happens when you restore"). `cli/README.md` shows `styrminctl backups restore <backup-id> --target-deployment my-app` as an example.

## Clarifications

### Session 2026-10-19 (maintainer decisions, from the PRD)

The PRD records these decisions, made with the maintainer in a grilling session on #532. They are listed here so that later phases do not reopen them.

- Q: Where does an in-place restore land? → A: In `styrmin-<deployment id>` of the deployment that the backup's instance belongs to, from every client. The caller names only the backup.
- Q: What happens to `targetNamespace` and `targetInstanceId` on `createRestore`? → A: Both arguments are removed, with no deprecation period, as #472 did for other input fields before version 1.0. GraphQL validation refuses a request that still sends them. The `Restore` type keeps both fields readable.
- Q: Which instance does the `Restore` row record? → A: The active instance of the backup's deployment, for every in-place restore, including those started from the Backups tab.
- Q: What does `styrminctl backups restore` do with the target options? → A: It drops `--target-namespace`. It refuses a backup id combined with `--target-deployment`, `--target-deployment-id` or `--target-instance-id` before it calls the server, with an error that says these options work only with `--last`. With `--last`, they keep choosing whose backup history the newest backup comes from.
- Q: Is there a replacement for restoring into another deployment? → A: Not in this fix. Restoring an existing backup into a new deployment, "deployment clone", is a separate feature that ships after this fix and has no issue yet. The changelog says so.
- Q: Which tests cover the fix? → A: Unit tests for the restore target resolution and for `styrminctl backups restore`; the functional GraphQL test for `createRestore` as the propagation test; and new assertions in the existing E2E test `test_backup_and_restore_lifecycle`, in `shard_backup`, with no new E2E test node. The maintainer agreed to ship the fix without a new E2E test, as AGENTS.md "Ask First" requires.

### Session 2026-10-19 (autonomous, while writing this spec)

These answers were not in the PRD. They are flagged for the maintainer to confirm.

- Q: `develop` moved from `a5ec9446` to `7f0455be` after the PRD was written, with the fix for #530 (#531). Does that change the fix? → A: No. #531 is the change in which the PRD's "second effect" (an in-place restore into another namespace ends with no service aliases) was found. After this fix the namespaces of a restore differ exactly when its deployment ids differ, so that effect cannot occur.
- Q: `styrminctl backups restore` also takes `--environment`, which only tells `--target-deployment` which environment a deployment name belongs to. Is it refused with a backup id? → A: No. The PRD names three target options. `--environment` selects no target on its own, so it keeps its current meaning and has no effect with a backup id alone.
- Q: What does the `Restore` row record when the backup's deployment has no active instance? → A: No target instance, as a cross-target restore into a counterpart without an active instance already does. The restore itself proceeds as today.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Restore a backup into its own deployment, from any client (Priority: P1)

A user with the `READ_WRITE` role restores a backup of deployment Y from the Backups tab, `styrminctl`, the Python SDK or GraphQL. The data lands in Y's namespace, and no namespace of another deployment is deleted or written to. A developer who calls the API passes only the backup id, and the restore record shows where the data went.

**Why this priority**: This is the defect of #532. Today a restore can delete the namespace of a deployment that the backup does not belong to, and overwrite it with another deployment's data.

**Independent Test**: Deploy an application, take a backup, and restore it through the API. Read the `Restore` row: it records `styrmin-<deployment id>` and the deployment's active instance. Send `createRestore` with `targetNamespace` or `targetInstanceId`, and receive a GraphQL validation error.

**Acceptance Scenarios**:

1. **Given** deployment Y and a completed backup of it, **When** the user restores the backup from the Backups tab, `styrminctl`, the SDK or GraphQL, **Then** the `Restore` row records `styrmin-<Y id>` as its target namespace and Y's active instance as its target instance, and no other namespace is deleted or written to.
2. **Given** a client that sends `createRestore` with `targetNamespace` or with `targetInstanceId`, **When** the server receives it, **Then** GraphQL validation refuses the request, and no restore is created.
3. **Given** a backup of an earlier instance of deployment Y, **When** the user restores it, **Then** it is restored into Y's namespace, Y keeps its active instance, and the row records Y's active instance ([ADR-063](../../dev/adr/0063-restore-of-earlier-instance-backup.md)).
4. **Given** a completed in-place restore, **When** the user runs `styrminctl backups restore-get` or reads the restore through the API, **Then** the target namespace and target instance shown are the deployment's namespace and active instance; `styrminctl backups restore-list` shows the same namespace.

---

### User Story 2 - styrminctl refuses a backup id combined with a target deployment (Priority: P2)

A `styrminctl` user who passes a backup id together with `--target-deployment`, `--target-deployment-id` or `--target-instance-id` gets an error before anything is sent to the server, so they do not believe they restored deployment X when Styrmin restored deployment Y.

**Why this priority**: After User Story 1, the server always restores into the backup's own deployment, so this request can no longer damage another deployment. It can still mislead the user about which deployment was restored.

**Independent Test**: Run `styrminctl backups restore <backup id> --target-deployment X` against a mocked SDK, and check that the command exits with the error and that the SDK is never called.

**Acceptance Scenarios**:

1. **Given** a backup of deployment Y, **When** the user runs `styrminctl backups restore <backup id> --target-deployment X`, **Then** `styrminctl` refuses the request before it calls the server, the error says that the target options work only with `--last`, and nothing is restored.
2. **Given** a backup of deployment X, **When** the user runs `styrminctl backups restore <backup id> --target-deployment X`, **Then** `styrminctl` refuses it in the same way. The user must drop the target option.
3. **Given** any backup, **When** the user runs `styrminctl backups restore <backup id> --target-deployment-id <id>` or `--target-instance-id <id>`, **Then** `styrminctl` refuses it in the same way.
4. **Given** any backup, **When** the user runs `styrminctl backups restore <backup id> --target-namespace <namespace>`, **Then** `styrminctl` rejects the unknown option.

---

### User Story 3 - `--last` keeps choosing the newest backup of the named deployment (Priority: P2)

A `styrminctl` user who runs `styrminctl backups restore --last --target-deployment X` keeps restoring the newest completed backup from X's backup history into X, so scripts that use `--last` keep working.

**Why this priority**: Scripts that restore the newest backup depend on this form. It must keep working after the target options are refused with a backup id.

**Independent Test**: Run the existing CLI tests for `--last`, and run `--last --target-deployment X` against a mocked SDK that returns X's backup history.

**Acceptance Scenarios**:

1. **Given** deployment X with completed backups, **When** the user runs `styrminctl backups restore --last --target-deployment X`, **Then** `styrminctl` restores the newest completed backup from X's backup history that has not expired, into X.
2. **Given** an instance id, **When** the user runs `styrminctl backups restore --last --target-instance-id <id>`, **Then** `styrminctl` restores the newest completed backup of that instance into the instance's deployment, without a namespace option.
3. **Given** the newest backup belongs to an earlier instance of X, **When** the user runs `--last --target-deployment X` without `--yes`, **Then** `styrminctl` asks for confirmation as it does today.

---

### User Story 4 - An environment restore and an environment clone follow the same rule (Priority: P3)

A user who restores an environment, or clones one, gets the same placement as a single restore: each constituent restore of an environment restore lands in its own deployment's namespace, and each restore of a clone lands in its counterpart deployment's namespace.

**Why this priority**: Every restore path should compute the target the same way. These paths already build the right namespace today, so the user sees no change; the risk is a regression.

**Independent Test**: Run the existing environment restore and environment clone tests.

**Acceptance Scenarios**:

1. **Given** an environment backup, **When** the user restores the environment, **Then** each constituent restore records its deployment's namespace and that deployment's active instance.
2. **Given** an environment, **When** the user clones it, **Then** each counterpart's restore records the counterpart's namespace and the counterpart's active instance, as it does today.

### Edge Cases

- A backup of an earlier instance of the deployment: Styrmin restores it into the same deployment, which keeps its active instance ([ADR-063](../../dev/adr/0063-restore-of-earlier-instance-backup.md)).
- A script that passes `--target-namespace`, or a client that sends `targetNamespace` or `targetInstanceId`: it fails until it stops passing the value. The changelog states this.
- A script that passes a backup id together with `--target-deployment`, even when the backup belongs to that deployment: `styrminctl` refuses it. The script must drop the target option.
- A raw `--target-instance-id` with a backup id: today it needs `--target-namespace`. After the fix, `styrminctl` refuses it like the other target options. With `--last`, it still chooses the newest backup of that instance.
- A restore that an earlier release created with another namespace: its row keeps the namespace it recorded. The in-flight restore guard does not change, so it still finds such a restore while it is pending or in progress ([`service.py`](../../backend/styrmin_backend/services/backup/service.py), `find_in_flight_restore`).
- The backup's deployment has no active instance: the row records no target instance, and the restore proceeds as today.
- The backup's deployment is internal or deleted: the restore is refused with the existing errors, as today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Styrmin MUST restore every in-place restore into `styrmin-<deployment id>` of the deployment that the backup's instance belongs to. This applies to restores started from the Backups tab, `styrminctl`, the Python SDK, GraphQL and an environment restore.
  - Verify with the functional GraphQL test and an E2E assertion on `Restore.targetNamespace`.
- **FR-002**: `createRestore` MUST NOT accept `targetNamespace` or `targetInstanceId`.
  - Verify with a functional test that sends each argument and receives a GraphQL validation error.
- **FR-003**: `create_restore()` in the Python SDK MUST NOT accept a target namespace or a target instance.
  - Verify with an SDK unit test.
- **FR-004**: For an in-place restore, Styrmin MUST record the active instance of the backup's deployment as `Restore.targetInstanceId`.
  - Verify with the functional GraphQL test and the E2E assertion.
- **FR-005**: `Restore.targetNamespace` and `Restore.targetInstanceId` MUST stay readable fields.
  - Verify with the existing restore query tests.
- **FR-006**: `styrminctl backups restore` MUST NOT accept `--target-namespace`.
  - Verify with a CLI unit test.
- **FR-007**: `styrminctl backups restore` MUST refuse a backup id combined with `--target-deployment`, `--target-deployment-id` or `--target-instance-id`, before it calls the server. The error MUST say that these options work only with `--last`.
  - Verify with a CLI unit test that asserts the SDK is never called.
- **FR-008**: With `--last`, the three target options MUST keep choosing whose backup history the newest backup comes from.
  - Verify with the existing CLI tests for `--last`.
- **FR-009**: An environment clone MUST keep restoring each constituent backup into its counterpart deployment's namespace, now computed by the same rule as an in-place restore.
  - Verify with the existing environment clone tests.
- **FR-010**: The documentation MUST describe the new behaviour in the same change: `cli/README.md`, the `styrminctl` reference and the "Backups and restores" page under `docs/`, `dev/knowledge/backend/api.md`, `dev/knowledge/backend/backup-restore.md`, and the "In-place restore" entry in `CONTEXT.md`. No page MUST still say that a user can restore a backup into another deployment or name a namespace.
- **FR-011**: The change MUST ship changelog fragments for #532: one of type `removed` for the two GraphQL arguments, the SDK parameters and the CLI option, which states that Styrmin offers no replacement until deployment clone ships; and one of type `fixed` for the bug.

### Key Entities

- **Restore**: the record of one restore. Its stored columns stay, so there is no database change.
  - `target_namespace` is always the namespace of the deployment that receives the data, and Styrmin sets it.
  - `target_instance_id` is set for every in-place restore whose deployment has an active instance. Before the fix, restores started from the Backups tab left it empty.
- **In-place restore**: a restore of a backup into the deployment that the backup was taken of, from any of its instances. This change adds a `CONTEXT.md` entry for the term, which the glossary used but did not define.
- **Cross-target restore**: unchanged. Only an environment clone starts one, and the clone does not go through `createRestore` ([`clone.py`](../../backend/styrmin_backend/workflows/templates/clone.py)).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of in-place restores, from every client, the data lands in the namespace of the backup's own deployment. No request can name another namespace or another instance.
- **SC-002**: `styrminctl` refuses 100% of requests that combine a backup id with a target option, without a call to the server.
- **SC-003**: No page of the user documentation, the developer documentation or the CLI help describes restoring a backup into another deployment's namespace or naming a target namespace.

## Assumptions

- It is not known whether any user restores into another namespace on purpose. The changelog states the removal, and states that Styrmin offers no replacement until deployment clone ships.
- Removing GraphQL arguments without a deprecation period is acceptable before version 1.0, as it was for #472 ([CHANGELOG.md](../../CHANGELOG.md)).
- No restore that names another namespace is in progress during the upgrade. `Restore` rows from before the upgrade are not migrated.
- The Backups tab shows no visible change; its restore operation only stops sending the namespace.
- No new server error code is needed: GraphQL validation refuses the removed arguments, and `styrminctl` gets one new refusal message.

## Out of Scope

- Restoring an existing backup into a new deployment ("deployment clone"). It was agreed as a separate feature that ships after this fix, and has no issue yet.
- Restoring into a namespace that no deployment owns. This is not planned.
- Removing namespaces that earlier restores into another namespace left behind.
- Simplifying the in-flight restore guard.
