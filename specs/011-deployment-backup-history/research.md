# Research: Keep a Deployment's Backup History When It Gets a New Instance

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)
**Source PRD**: [issue #304, comment 6070292805](https://github.com/opsmill/styrmin/issues/304#issuecomment-6070292805). Its "Implementation decisions" and "Testing decisions" sections are authoritative. This file records how they map onto the code on this branch and the decisions the PRD left open.

All code references were checked on this branch (based on `a2a627d3`).

## R1. How a backup is linked to its deployment

**Finding**: `Backup.instance_id` is a foreign key to `applicationinstance.id` (`backend/styrmin_backend/db/models.py`, class `Backup`). `ApplicationInstance.deployment_id` is a non-null foreign key to `deployment.id` (class `ApplicationInstance`). No code deletes an `ApplicationInstance` row: a search for instance deletes in `backend/styrmin_backend` returns nothing. Every instance a deployment ever had therefore stays linked to that deployment.

**Decision**: Find a deployment's backup history with one query: `Backup` joined to `ApplicationInstance` on `Backup.instance_id == ApplicationInstance.id`, filtered by `ApplicationInstance.deployment_id`, with the existing optional `status` filter, ordered by `Backup.created_on` descending (the same order `get_by_instance_id` uses).

**Rationale**: The link already exists and is non-null on both hops. No new column, no backfill and no Alembic revision are needed, which matches the PRD ("no database change").

**Alternatives considered**:

- Move each backup's link from the instance to the deployment (`Backup.deployment_id`). Rejected by the PRD: it needs a schema change and a backfill, and the two-hop link is enough.
- Collect the deployment's instance ids first, then call `get_by_instance_id` for each. Rejected: N+1 queries and a merge-sort in Python for something one join does.

## R2. The four operations that create a new instance

**Finding** (`backend/styrmin_backend/services/deployment.py`):

| Operation | Service function | How an operator starts it today |
|-----------|------------------|---------------------------------|
| Upgrade | `update_deployment_version` | `updateDeploymentVersion` mutation, the upgrade dialog, `styrminctl` |
| Config edit | `update_deployment` | `updateDeployment` mutation, the Settings tab, `styrminctl` |
| Refresh | `refresh_deployment` | No caller on this branch. No GraphQL field, CLI command or flow calls it. |
| Environment config change | `redeploy_for_environment_update`, called from `update_environment` | `updateEnvironment` mutation, the environment Configuration tab |

Each one calls `generate_instance_from_deployment`, then `deployment.set_active_instance(...)`. The new instance keeps the same `deployment_id`.

**Decision**: The fix does not touch these four functions. Listing by deployment id covers all four, and any future operation that creates an instance the same way. The integration test (R8) drives `refresh_deployment` directly at the service layer, because nothing else can reach it.

**Rationale**: The PRD names all four. `refresh_deployment` having no caller is recorded here so that a reviewer is not surprised that the test calls a service function directly for it. Whether `refresh_deployment` should keep existing is not part of this fix.

## R3. Validation of the two arguments (exactly one of `deploymentId` or `instanceId`)

**Finding**: [ADR-031](../../dev/adr/0031-dual-identifier-resolution-service-layer.md) puts the "exactly one of two identifiers" rule in the service layer. `AmbiguousIdentifierError` (`backend/styrmin_backend/services/exceptions.py`) is the existing `ServiceError` subclass for it, with `error_code = "VALIDATION_ERROR"`. `resolve_cluster` (`services/clusters.py`) is the reference shape: it raises the error with a specific message for "both" and for "neither".

**Decision**: `get_backups(uow, *, deployment_id=None, instance_id=None, status=None)` in `services/backup/service.py` raises `AmbiguousIdentifierError` with a specific message when both or neither are passed. The resolver only forwards its arguments. No new exception class.

**Rationale**: Reusing the class keeps one error code for one rule, as ADR-031 asks. A new subclass would carry the same code and add nothing a client can branch on.

**Alternatives considered**: Validate in the resolver. Rejected by ADR-031 and Constitution §III. A Strawberry input type or a separate `deploymentBackups` field. Rejected by ADR-031 (API surface growth) and by the PRD (no `Deployment.backups`-style field).

## R4. An unknown `deploymentId`

**Finding**: The sibling list queries return an empty list for an id that matches nothing: `backups(instanceId:)` (via `get_by_instance_id`) and `backupSchedules(deploymentId:)` (via `get_backup_schedules`). Neither checks that the parent exists.

**Decision**: `backups(deploymentId:)` with an id that matches no deployment returns `[]`, with no error.

**Rationale**: Keeps the two arguments of one field consistent with each other and with `backupSchedules`. The CLI and the Backups tab always pass the id of a deployment they have already loaded, so an empty list never hides a typo there. The PRD does not specify this case.

## R5. Showing the application version of each backup

**Finding**: The GraphQL `Backup` type already exposes `instance: ApplicationInstance!`, resolved through the `application_instances` data loader (`resolve_related` in `api/definitions/backup/backup.py`). `ApplicationInstance.applicationVersion` is `String!`. A list of N backups therefore reads their instances with one batched query.

**Decision**: No change to the `Backup` type. The SDK operation `ListBackups` and the frontend operation `ListBackups` both add `instance { id applicationVersion }` to their selection. The CLI and the Backups tab read the version from there.

**Rationale**: Matches the PRD ("The `Backup` type does not change"). The data loader prevents an N+1 read.

**Alternatives considered**: A flattened `Backup.applicationVersion` field. Rejected: it duplicates a field that already exists one hop away and would need its own propagation test for no user benefit.

## R6. SDK binding shape

**Finding**: `BackupsResource.list_backups(self, instance_id, status=None)` in `python_sdk/src/styrmin_sdk/resources/backups.py` sends `{"instanceId": ...}` to the `ListBackups` operation (`python_sdk/src/styrmin_sdk/graphql/list_backups.graphql`), whose variable is `$instanceId: UUID!`. Its callers: the CLI (keyword `instance_id=`) and `python_sdk/tests/test_backups.py` (keyword `instance_id=`).

**Decision**: `list_backups(self, instance_id: str | UUID | None = None, status: BackupStatus | str | None = None, *, deployment_id: str | UUID | None = None)`. It sends only the variables that are set. The operation becomes `query ListBackups($deploymentId: UUID, $instanceId: UUID, $status: BackupStatus)`. The SDK does not check "exactly one" itself: per ADR-031 the server does, and the SDK raises the error the server returns.

**Rationale**: Positional and keyword calls that pass `instance_id` keep working (SC-004 for SDK users). `deployment_id` is keyword-only, so it cannot be passed by position by mistake.

## R7. CLI target resolution

**Finding**: `resolve_active_instance` (`cli/src/styrminctl/resolve.py`) resolves a name or `--id` to a deployment and then fails when the deployment has no active instance (`_active_instance_id`). `list_backups` and `_prepare_restore` (`cli/src/styrminctl/commands/backups.py`) both use it and then list by instance.

**Decisions**:

- `styrminctl backups list`:
  - with `--instance-id`: list that instance's backups, as today
  - with a name or `--id`: resolve the deployment id with a new helper `resolve_deployment_id` in `resolve.py` (same selector validation and `_resolve_by_name`, but no active-instance requirement), then list by `deployment_id`
  - adds an `application_version` column, read from `backup.instance.application_version`
- `styrminctl backups restore --last`:
  - with `--target-deployment` or `--target-deployment-id`: pick the newest completed backup from `list_backups(deployment_id=target.deployment_id, status="completed")`
  - with a raw `--target-instance-id`: no deployment is known, so keep listing by that instance, as today
  - the "nothing found" message names the deployment when the history was listed by deployment
- The restore target resolution itself does not change: it still needs an active instance to restore into.

**Rationale**: `list` must not fail for a deployment without an active instance when its history has backups. Restores do not change (spec FR-008).

## R8. Test placement

**Decisions**, following the PRD's "Testing decisions":

| Test | Location | What it proves |
|------|----------|----------------|
| Repository | `backend/tests/unit/repository/backup/test_backup_repository.py` (extend) | `get_by_deployment_id` returns backups of every instance of one deployment, newest first, honours `status`, and excludes another deployment's backups |
| Service | `backend/tests/unit/services/backup/test_backup_service.py` (extend) and `FakeBackupRepository` in `backend/tests/unit/services/fakes.py` | the exactly-one rule raises `AmbiguousIdentifierError`; each argument reaches the right repository method |
| GraphQL propagation | new `backend/tests/functional/graphql/test_backup_history_propagation.py`, operation file `operations/list_backup_history.graphql` | `deploymentId` reaches the repository and the result projects `instance.applicationVersion`; `instanceId` results are unchanged; both or neither give `VALIDATION_ERROR` |
| Integration (four operations) | same functional module | a backup taken before each of the four operations is still returned by `backups(deploymentId:)` with its application version |
| SDK | `python_sdk/tests/test_backups.py` (extend) | the variables sent for `deployment_id`, `instance_id` and both; the parsed `instance.application_version` |
| CLI | `cli/tests/test_backups.py` (extend) | `list <deployment>` lists by deployment and shows the version column; `--instance-id` lists by instance; `restore --last` picks from the deployment history |
| Frontend | `frontend/src/__tests__/deployment-detail/BackupExpiry.test.tsx` (extend) | the tab queries by `deploymentId`, and renders the version column |
| E2E | `backend/tests/e2e/test_backup_restore.py::test_backup_and_restore_lifecycle` (extend, both variants) | R9 |

For the integration test, the three operations that have a GraphQL mutation run through the HTTP endpoint with `prefect_manager_mock`, reusing the seed helpers and mutation operation files that `test_driver_version_reselection_propagation.py`, `test_deployment_noop_propagation.py` and `test_environment_update_propagation.py` already use. `refresh_deployment` runs through the service function with a real SQLModel unit of work over the same session (R2). Each case asserts that the active instance changed, so the test fails if an operation is a no-op.

The functional tier is used, not `backend/tests/integration/`: that directory holds Kubernetes-backed agent tests, while the four operations only need the database and a mocked Prefect manager.

## R9. E2E scenario

**Finding**:

- `test_backup_and_restore_lifecycle` uses the session-shared `deployed_simple_app` (simple-app 0.1.0; components `server` and `database`, where only `database` is backed up, as a Postgres dump).
- Step 0 sets `backup_ttl` on the environment, which redeploys the deployment with a new instance. The test then passes the fixture's original `instance_id` to `create_backup`, so the API variant backs up an instance that is no longer active. The UI driver ignores `instance_id` and backs up the active instance.
- `ScenarioDriver.set_component_env_vars` is a dual-entrypoint config edit that both drivers support. `ScenarioDriver.update_deployment` is limited to `scheduling` in the UI driver.
- The Backups tab rows carry `data-backup-id`, `data-backup-name` and `data-backup-status`, which the UI driver's page object reads.

**Decisions**:

1. After the step-0 fanout settles, re-read the deployment's active instance id and pass that to `create_backup`, so both variants back up the active instance.
2. After the backup completes and its existing checks pass, edit the deployment's config with `set_component_env_vars(component="server", env_vars={...one marker variable...})`, then wait for the deployment to run and its pods to be ready. Assert the active instance id changed.
3. Add a dual-entrypoint driver method `list_backups(*, deployment_id) -> tuple[BackupRef, ...]`, and an `application_version: str | None = None` field on `BackupRef`. API driver: `client.backups.list_backups(deployment_id=...)`. UI driver: open the Backups tab and read every `backup-row`, including a new `data-backup-application-version` attribute.
4. Assert the backup is in that list with application version `0.1.0`. The existing restore (step 4) and delete (step 6) then run against a backup of an earlier instance, which the UI driver can only reach if the Backups tab lists the history.
5. In `finally`, set the `server` component's env vars back to what they were before the edit. Run this revert in its own `try`/`finally` around the existing `backup_ttl` revert, so a failure in one revert cannot skip the other or hide the test's own failure (critique E5).

**Rationale**: Reuses the deployed stack (Constitution §V, "Reuse before you boot"). A config edit on `server` does not touch the Postgres data that the restore assertions check. The PRD chose a config edit over an upgrade because the deployment is shared by every test in the session.

**Risk**: An in-place restore runs Velero with `existingResourcePolicy: update` and includes the HelmRelease, so step 4 may put the pre-edit `server` spec back in the cluster until the `finally` revert re-converges it. The restore assertions read the counter from Postgres, so they should not depend on the `server` env var. If the restore step becomes unstable because of the edit, move the config edit and the history check to after step 5 (restore verified) and before step 6 (delete), and record the move in the implementation report.

## R10. Third-party dependency gaps

**Finding**: None. The change needs:

- an optional argument on an existing Strawberry field (`UUID | None = None`), which Strawberry supports
- a join with a filter and an order in SQLModel/SQLAlchemy, which both support
- an optional GraphQL variable in ariadne-codegen (SDK) and graphql-codegen (frontend), which both generate as optional parameters

**Decision**: No extension mechanism or upstream contribution is needed. No new dependency.

## R11. Documentation and agent context

**Decision**: The same change updates:

- `docs/docs/concepts-and-architecture/backups-and-restores.md`: a "Backup history" passage. The history lists backups of every instance of the deployment and shows each one's application version, and the four operations that create a new instance.
- `docs/docs/reference/styrminctl.md`: the sentence saying `backups` options are instance-scoped.
- `cli/README.md` ("Backups and restores"), and the help text of `styrminctl backups list` and `restore --last`.
- `dev/knowledge/backend/backup-restore.md`: the service table row for `get_backups` and the `backups(...)` signature in "GraphQL API → Queries".
- `CONTEXT.md`: a **Backup history** entry next to the backup entries in "Infrastructure entities".
- `changelog/304.fixed.md`.

No ADR: the fix applies ADR-031 and ADR-008 and adds no new pattern.

The `<!-- SPECKIT START -->` block in `CLAUDE.md` and `AGENTS.md` is left empty, as the other specs on this branch left it. The constitution forbids running `update-agent-context.sh`, and the block is maintained outside these workflows.
