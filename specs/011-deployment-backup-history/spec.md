# Feature Specification: Keep a Deployment's Backup History When It Gets a New Instance

**Feature Branch**: `fac/fix-backup-history-disappears-f8kjf`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Fix issue #304 (opsmill/styrmin): backup history disappears after a deployment gets a new instance." Source PRD: [issue #304, comment 6070292805](https://github.com/opsmill/styrmin/issues/304#issuecomment-6070292805), confirmed in a review session on 2026-10-08. Code references in the PRD point to commit `a2a627d3` on `develop`.

## Problem

An operator who takes a backup of a deployment and then changes the deployment can no longer view that backup on the deployment's Backups tab. The same backup is also missing from `styrminctl backups list`, and `styrminctl backups restore --last` fails with "No completed backups found". The backup still exists and can still be restored by its id.

The backup drops out of view because each backup belongs to one instance, and the Backups tab, the CLI and the `backups` query list only the backups of the deployment's active instance. Four operations each create a new instance and make it the active instance, so any of them hides the earlier backups:

- an upgrade to a new driver version
- a config edit of the deployment
- a refresh of the deployment
- an environment config change, which redeploys every deployment in the environment

[ADR-008](../../dev/adr/0008-deployment-soft-delete-tombstoning.md) already treats the deployment as the stable id that its backups are kept under.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View and restore a backup taken before the deployment got a new instance (Priority: P1)

An operator takes a backup of a deployment, then upgrades it, edits its config, refreshes it, or changes the config of its environment. The operator opens the deployment's Backups tab, finds the earlier backup with the application version it was taken at, and restores it. The CLI and the API list the same backups.

**Why this priority**: This is the bug in issue #304. Without it, an operator cannot find the backup they need to recover data from before an upgrade or a config change.

**Independent Test**: Take a backup of a deployment, run one of the four operations, then list the deployment's backups on the Backups tab, with `styrminctl backups list <deployment>` and with `backups(deploymentId:)`. Each list contains the earlier backup with its application version.

**Acceptance Scenarios**:

1. **Given** a deployment with a completed backup taken at application version 1.2, **When** the deployment is upgraded to application version 1.3, **Then** the backup is listed with application version 1.2 on the Backups tab, in `styrminctl backups list <deployment>` and in `backups(deploymentId:)`.
2. **Given** a deployment with a completed backup, **When** its config is edited, **Then** the backup is still listed in all three places with the application version it was taken at.
3. **Given** a deployment with a completed backup, **When** the deployment is refreshed, **Then** the backup is still listed in all three places.
4. **Given** a deployment with a completed backup, **When** a config change on its environment redeploys it, **Then** the backup is still listed in all three places.
5. **Given** a deployment with backups taken of several of its instances, **When** the operator lists its backup history, **Then** every backup is listed once, newest first.
6. **Given** a backup taken of an earlier instance and listed in the deployment's history, **When** the operator restores it from the Backups tab, **Then** the restore starts as it does today for a backup of the active instance.

---

### User Story 2 - Restore the latest backup from the CLI after a config edit (Priority: P2)

An operator edits a deployment's config and then restores the deployment's newest completed backup with one CLI command, without looking up a backup id or an instance id.

**Why this priority**: `styrminctl backups restore --last` is the shortest recovery path. It fails today after any of the four operations, which is when an operator is most likely to need it.

**Independent Test**: Take a backup, edit the deployment's config, then run `styrminctl backups restore --last --target-deployment <name>`. A restore of the newest completed backup in the deployment's history starts.

**Acceptance Scenarios**:

1. **Given** a deployment with at least one completed backup, **When** its config is edited and the operator runs `styrminctl backups restore --last --target-deployment <name>`, **Then** a restore of the newest completed backup in the deployment's history starts.
2. **Given** a deployment that was upgraded, **When** the operator runs `styrminctl backups restore --last --target-deployment <name>`, **Then** the CLI chooses the newest completed backup in the whole history, whichever instance it was taken of.
3. **Given** a deployment with no completed backup in its history, **When** the operator runs `styrminctl backups restore --last --target-deployment <name>`, **Then** the CLI fails with a message that no completed backup was found for the deployment.

---

### User Story 3 - List a deployment's backups by deployment id from the API and SDK (Priority: P2)

An API or SDK user lists a deployment's backup history by deployment id, without collecting the ids of all its instances. A user who lists backups by instance id keeps getting the same results as before.

**Why this priority**: The Backups tab and the CLI depend on this way of listing. Integrations that list by instance id must keep working.

**Independent Test**: Call `backups(deploymentId:)` for a deployment with backups of several instances and check that every backup is returned. Call `backups(instanceId:)` for one instance and check that only that instance's backups are returned. Call `backups` with both arguments and with neither, and check that each call fails with `VALIDATION_ERROR`.

**Acceptance Scenarios**:

1. **Given** a deployment with backups of two instances, **When** an API user calls `backups(deploymentId:)`, **Then** the backups of both instances are returned, newest first.
2. **Given** the same deployment, **When** an API user calls `backups(instanceId:)` with the id of one instance, **Then** only the backups of that instance are returned, as before this change.
3. **Given** any deployment, **When** an API user calls `backups` with both `deploymentId` and `instanceId`, or with neither, **Then** the call fails with `VALIDATION_ERROR`.
4. **Given** a deployment, **When** an SDK user lists its backups by deployment id, **Then** the SDK returns the same backups as `backups(deploymentId:)`.
5. **Given** a status filter, **When** an API user calls `backups(deploymentId:, status:)`, **Then** only the backups in the history with that status are returned.

---

### User Story 4 - View the backup history of a deleted deployment (Priority: P3)

An operator opens a deployment that was deleted and views its backup history, to review it or restore from it, as ADR-008 describes.

**Why this priority**: ADR-008 keeps backups with a deleted deployment. Listing by deployment id keeps that history visible. This story is less frequent than the first three.

**Independent Test**: Take a backup of a deployment, delete the deployment, then open its page and list its backups through the API. The backup is listed.

**Acceptance Scenarios**:

1. **Given** a deleted deployment with backups, **When** the operator opens its page, **Then** the Backups tab lists its backup history.
2. **Given** a deleted deployment and a new deployment that reuses its name, **When** the operator lists the new deployment's backup history, **Then** the history is empty, because the history is listed by deployment id, not by name.

---

### Edge Cases

- A deployment that gets a new instance on each of several operations lists the backups of every instance it ever had, newest first.
- A new deployment that reuses a deleted deployment's name starts with an empty history.
- A counterpart deployment created by an environment clone does not list the source deployment's backups, because those backups belong to instances of the source deployment.
- Constituent backups of an environment backup appear in the history, as they do today, because each one is a backup of one instance.
- `styrminctl backups restore --last` chooses a backup taken at an older application version only when no backup was taken after the version changed. Styrmin does not warn about this, because restores do not change in this fix.
- `backups(instanceId:)` called with an instance that is no longer active still returns that instance's backups.
- A deployment that has never had a backup lists an empty history on the Backups tab, in the CLI and through the API.
- `styrminctl backups list --instance-id <id>` keeps listing the backups of that one instance.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Styrmin MUST list, as a deployment's backup history, every backup taken of any of the deployment's instances, newest first, whichever of the four operations created each instance.
- **FR-002**: The Backups tab and `styrminctl backups list` MUST show, for each backup, the application version of the instance the backup was taken of.
- **FR-003**: API users MUST be able to list a deployment's backup history with `backups(deploymentId:)`.
  - A call MUST pass exactly one of `deploymentId` or `instanceId`. A call that passes both or neither MUST fail with `VALIDATION_ERROR`, as [ADR-031](../../dev/adr/0031-dual-identifier-resolution-service-layer.md) describes.
  - `backups(instanceId:)` MUST keep returning the backups of that one instance.
  - The existing `status` filter MUST apply to either argument.
- **FR-004**: SDK users MUST be able to list a deployment's backup history by deployment id. `styrminctl backups list <deployment>` and `styrminctl backups restore --last` MUST use the deployment's backup history. `--instance-id` MUST keep listing the backups of one instance.
- **FR-005**: The Backups tab MUST list the deployment's backup history by deployment id.
- **FR-006**: The backup history of a deleted deployment MUST stay listable by its deployment id.
- **FR-007**: A deployment's backup history MUST NOT include backups of instances that belong to another deployment, including a counterpart deployment in a cloned environment and a new deployment that reuses a deleted deployment's name.
- **FR-008**: Restores MUST behave as they do today. A backup taken at another application version restores with no check and no confirmation.
- **FR-009**: New backups MUST still be taken of the deployment's active instance.

### Key Entities

- **Deployment** (existing): owns the backup history. No change to the record.
- **Instance** (existing): each backup still belongs to one instance. A deployment gets a new instance on each of the four operations listed under Problem.
- **Backup** (existing): no new fields. The history is found from the deployment through its instances. The application version shown for each backup is the version of its instance.
- **Backup history** (new term, not a new entity): every backup taken of any instance of one deployment, newest first. Not yet in `CONTEXT.md`. This fix adds an entry for it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After each of the four operations, 100% of the backups taken before the operation are still listed on the Backups tab, in `styrminctl backups list <deployment>` and in `backups(deploymentId:)`.
- **SC-002**: Every backup in a deployment's history shows the application version it was taken at.
- **SC-003**: After an upgrade or a config edit, `styrminctl backups restore --last --target-deployment <name>` starts a restore without an instance id when the deployment has at least one completed backup.
- **SC-004**: Calls to `backups(instanceId:)` return the same results as before the change.
- **SC-005**: The Backups tab, `styrminctl backups list <deployment>` and `backups(deploymentId:)` list the same backups for the same deployment.

## Assumptions

- It is not known whether any deployment has enough backups to need pagination. The existing `backups` query has none, and this fix does not add it.
- It is not known what a restore of a backup taken at an older application version does to a deployment that now runs a newer version. An in-place restore runs Velero with `existingResourcePolicy: update` and includes the HelmRelease. No test covers this case. This fix does not change restores.
- The `backups` query has no field-level role check today. The new argument is on the same field, so access rules do not change.
- The `Backup` type already exposes the application version of its instance, so the API type does not change.
- No database change is needed. Each backup keeps its link to one instance, and the history is found through the deployment's instances.

## Out of Scope

- Any check, confirmation or defined behaviour for restoring a backup taken at another application version.
- Moving each backup's link from the instance to the deployment, or any other database change.
- A `Deployment.backups` field.
- The driver version in the backup list. The driver version stays available on the backup's detail.
- Pagination of the backup history.
- Which instance a new backup is taken of. New backups are still taken of the active instance.

## Documentation

The same change updates these pages, as Constitution §VII requires:

- `docs/docs/concepts-and-architecture/backups-and-restores.md`: the history lists backups from every instance and shows each one's application version.
- `docs/docs/reference/styrminctl.md`: the statement that `backups` options are instance-scoped.
- The help text of `styrminctl backups list` and `styrminctl backups restore --last`, and `cli/README.md`.
- `CONTEXT.md`: a new entry for backup history.
- A changelog fragment for #304.

## Open Questions Carried From the PRD

These do not block this fix. They are recorded so the person who reviews it can decide on them.

- Whether a follow-up issue should define what a restore of a backup taken at another application version should do: change the deployment back to that version, refuse, or migrate the data. [CLAUDE RECOMMENDED – based on the unverified restore outcome described under Assumptions] Open the follow-up issue, because this fix makes such backups visible on the Backups tab.
- Whether issue #304's title should name all four operations instead of upgrades only. [CLAUDE RECOMMENDED – based on the four operations listed under Problem] Rename it to "fix(backend): backup history disappears after a deployment gets a new instance (upgrade, config edit, refresh, environment config change)".
