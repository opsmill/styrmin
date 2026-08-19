# Research: Environment Clone

**Feature**: 010-environment-clone | **Date**: 2026-08-19

All decisions below are grounded in the merged environment backup/restore foundation
(`specs/001-env-backup-restore/`, ADR-055) and a full read of the restore execution
path. File references are to the current branch.

## D1 — Cross-target restore rides Velero's native `namespaceMapping` (no dependency gap)

**Decision**: Restore a constituent backup into the counterpart deployment's namespace
using Velero's built-in `spec.namespaceMapping` — no Velero fork, plugin, or upstream
contribution is needed.

**Rationale** (constrained-third-party-dependency evaluation, as directed):

- Velero natively supports restoring a backup into a different namespace via
  `namespaceMapping` on the Restore CR (velero.io restore reference). PVs are handled
  (existing PVs are renamed `velero-clone-<uuid>` with the original name kept as an
  annotation; PVC binding fields are stripped so dynamic binding re-binds), and
  `existingResourcePolicy`, `labelSelector`, and `includedNamespaces` provide
  filtering.
- Our wrapper already supports it end to end: `VeleroRestore.namespace_mapping`
  renders `spec.namespaceMapping`
  (`backend/styrmin_backend/agent/service/kubernetes/velero/resources.py:197-239`),
  and `build_velero_restore` computes the mapping whenever
  `source_namespace != target_namespace`
  (`backend/styrmin_backend/agent/service/kubernetes/resources/builders/backup.py:53-55`).
  The dependency was designed for this; there is nothing to extend.
- The one thing Velero does **not** do is rename resources: `namespaceMapping`
  rewrites namespaces but keeps object names (only PVs are renamed). That is handled
  in code we own (D5), not by extending Velero.

**Alternatives considered and rejected**:

- *Velero plugin / RestoreItemAction to rewrite identity during restore*: possible
  extension mechanism, but the identity rewrite we need (StyrminDeployment CR spec,
  FQDNs, release references) is Styrmin domain logic that already lives in our
  post-restore recovery step; pushing it into a Velero plugin would split one concern
  across two codebases and add a new deployable artifact.
- *Upstream contribution (resource renaming)*: unnecessary — object-name collisions
  do not arise because each deployment lives in its own namespace
  (`styrmin-<deployment_id>`), so preserved names inside a remapped namespace are
  exactly what makes chart-derived PVC/Secret names line up in the counterpart.
- *Data-only copy pipelines (pg_dump/rsync jobs outside Velero)*: would bypass the
  shipped backup strategies and duplicate the hook machinery per strategy; rejected.

## D2 — Where the in-place restore contract actually breaks (change surface)

The shipped restore contract is in-place by construction, not by Velero limitation.
The concrete coupling points, ranked by depth (each becomes plan work):

1. `create_restore` resolves the deployment **from the backup** (`backup.instance_id
   → instance.deployment_id`), guards `internal`/`RESTORING` on it, and flips **that**
   deployment to `RESTORING` (`backend/styrmin_backend/services/backup/service.py:339-437`,
   esp. `:372-377`, `:385-396`, `:427-428`). For a clone this would mutate the
   **source** deployment (violating SC-002) and never touch the counterpart.
   → `create_restore` gains an explicit optional `target_deployment_id`; when set,
   all guards and the `RESTORING` flip apply to the target. The persisted-but-unread
   `Restore.target_instance_id` (`db/models.py:589-612`) finally gets honoured for
   attribution.
2. `execute_restore_workflow` derives `source_namespace = f"styrmin-{deployment_id}"`
   **and** writes terminal deployment status to the same `deployment_id`
   (`backend/styrmin_backend/workflows/templates/backup.py:676` vs `:757/:777`).
   → the flow signature splits source identity from status-write target: it gains
   `source_deployment_id` (namespace derivation) while `deployment_id` stays the
   status-write target (the counterpart, for clones; same value for in-place).
3. The USER flow's post-restore recovery assumes `crd_name = target_namespace`
   (`workflows/templates/backup.py:278`). Under `namespaceMapping` Velero preserves
   the CR *name* (`styrmin-<source_deployment_id>`) while moving its namespace, so
   the lookup 404s. → recovery receives the restored CR name explicitly.
4. `reapply_and_finalize` replays the **restored (source) CR spec** into the target
   namespace (`backend/styrmin_backend/operator/restore_recovery.py:124-202`). The
   restored spec carries the source's `deploymentId`, `instanceId`,
   `releaseReference`, and full resolved context (FQDNs embed `deployment_id` and
   environment name — `backend/styrmin_backend/context/fqdn.py:58-99`). → for
   cross-target restores, recovery replaces the restored CR with the **counterpart's
   own CR body** (built from the counterpart's active instance context via the
   existing CR builder, `backend/styrmin_backend/operator/crd/builder.py:22-78`) and
   deletes the restored source-named CR. Data (PVC contents) survives; identity
   objects (Ingress, HelmRelease, CR) are re-rendered with counterpart identity.
5. The USER flow deletes the target namespace and waits for 404 before restoring
   (`workflows/templates/backup.py:213-246`). Benign for clones **if and only if**
   counterpart deployments are not reconciled before their restore runs (D6).
6. Restore CR labels carry the source `instance_id`
   (`builders/backup.py:62-65`) — harmless but misattributing; the clone path labels
   with the counterpart instance id.

Data-layer hooks (postgres `pg_restore`, neo4j, mariadb, mongodb —
`agent/service/kubernetes/velero/hooks.py`) already exec inside the restored pods
with `included_namespaces=[target_namespace]` selectors and read credentials from the
restored Secrets, so they are target-agnostic and expected to work unchanged. Known
risk class: role/db-name mismatches (`hooks.py:261-264` FIXME) — same exposure as
in-place restore, not clone-specific.

## D3 — Clone record: new `EnvironmentClone` table, derived status (ADR-055 pattern)

**Decision**: A new `EnvironmentClone` table linking `source_environment_id`,
`environment_backup_id` (nullable until capture registers), and
`created_environment_id` (nullable until the environment materialises), carrying the
requested name, deployment selection, config override, and a per-source-deployment
outcome list. **No stored status column** — status is derived on every read from the
backing environment backup's derived status, the created environment's existence, the
constituent `Restore` rows, and recorded errors (FR-009).

**Rationale**: ADR-055's convention test ("add an umbrella record when the grouping is
itself a user-facing artifact with its own lifecycle") is met exactly. Neither
existing parent's shape fits (an `EnvironmentRestore` reaches its environment through
the backup; a clone spans **two** environments), so a new table is required — with an
Alembic revision per ADR-001.

**Alternatives rejected**: reusing `EnvironmentRestore` with a nullable
"target environment" (overloads the in-place contract and its status vocabulary);
stored status column (contradicts FR-009 and ADR-055 decision 2).

## D4 — Orchestration: a new INTERNAL Prefect flow, because clone must *wait*

**Decision**: The `cloneEnvironment` mutation validates upfront (name free, selection
valid, source exists), creates the `EnvironmentClone` record plus the environment
backup capture **in one transaction** (reusing `_SharedTransaction`,
`services/backup/environment.py:308-342`), commits, dispatches the constituent backup
flows exactly as `create_environment_backup` does, then dispatches one new INTERNAL
Prefect flow `EXECUTE_ENVIRONMENT_CLONE(clone_id)` and returns the clone record. The
flow: polls the capture's derived status to terminal → creates the environment (with
merged config, D7) → creates counterpart deployments (D6) → dispatches one
cross-target restore per usable constituent → exits (restores report their own
status; clone status stays derived).

**Rationale**: ADR-055 deliberately shipped **no** environment-backup flow because its
fan-out needed no waiting — every existing dispatch is fire-and-forget. Clone is the
first operation that must *sequence* on an async outcome (FR-002: nothing
materialises unless capture succeeds), and Prefect is the platform's only sanctioned
async executor (Constitution §III). The INTERNAL/USER split and direct DB status
writes mirror `execute_restore_workflow` (`workflows/templates/backup.py:628-814`).

**Alternatives rejected**: synchronous mutation (holds a GraphQL request for the
whole capture — minutes); service-side background task outside Prefect (violates
§III); chaining via Prefect flow-of-flows for the whole clone including restores
(restores already self-report; wrapping them adds a second status channel).

## D5 — Counterpart creation: reuse `deploy_application` with a pinned driver version, defer reconciliation

**Decision**: Each counterpart deployment is created through the existing
`deploy_application` service (`services/deployment.py:1071-1322`) with
`driver_version_id` pinned to the row resolved from the snapshot's
`driver_name`/`driver_version`/`driver_fingerprint` (ADR-053 identity;
`DeploymentSnapshot` carries all of it — `services/backup/environment.py:126-142`;
ADR-055 captured the fingerprint *explicitly for clone*). Counterpart creation
**skips the initial `apply_state`** — the cross-target restore rebuilds the namespace
from the capture and the recovery step (D2.4) reconciles with counterpart identity;
reconciling first would only create resources the restore flow immediately deletes
(D2.5).

**Rationale**: Constitution §II — counterparts bind to captured driver versions
through the ordinary driver path, no ad-hoc deploy logic. If the pinned version row
no longer exists (fingerprint unresolvable), that deployment is attributed `failed`
and the rest proceed (spec edge case; clone ends `PARTIAL`).

**Alternatives rejected**: deploy-then-inject (fully reconcile the counterpart, then
restore data over it) — collides with the restore flow's namespace delete-and-wait
and would restore source PVC objects over live pods; raw row cloning without
`deploy_application` — bypasses validation, services, instance generation.

## D6 — Selection: capture takes an optional deployment filter (service-level)

**Decision**: `create_environment_backup` gains an optional
`deployment_ids: list[UUID] | None` filter (service signature only; the existing
`createEnvironmentBackup` GraphQL mutation is unchanged). The clone mutation
validates the selection upfront: unknown/foreign ids → typed validation error;
selected-but-ineligible deployments → attributed `skipped` (FR-004). Omitted
selection = all eligible (`is_eligible_for_environment_backup`,
`services/backup/environment.py:213-226`).

**Rationale**: FR-002 says the capture is *of the selected deployments*; filtering at
capture avoids backing up excluded heavyweight deployments (the stated point of
selection). Not exposing the filter on the standalone backup mutation keeps this
feature's GraphQL surface additive-only.

## D7 — Config override: top-level-key overlay over the captured config

**Decision**: The clone's environment config = captured `environment_config` with the
override applied as a **top-level-field replacement merge**: each field present in
the override replaces the captured field wholesale; absent fields keep captured
values. Both sides are canonicalised through `EnvironmentConfig` validation first
(mirroring `_deployment_already_at_config`'s canonicalisation,
`services/environments.py:127-136`). The override is expressed with the existing
`UpdateEnvironmentInput` shape (`api/definitions/environment/inputs.py:69`), reusing
`update_environment_input_to_dict`. The merged result is validated with
`validate_environment_config` before the environment is created, and capabilities are
recomputed (never copied — ADR-027).

**Rationale**: ADR-012 rejected deep/PATCH merge for `updateEnvironment`; per-field
replacement is the platform's established granularity, so the clone override adopts
the same semantics one level up (override a field → you own that whole field). It is
predictable, testable, and reuses the existing input type on all four surfaces.

**Alternatives rejected**: deep recursive merge (no platform precedent, ambiguous
for lists like tolerations); full replacement of the whole config (fails the PRD's
"merged over the copied config" — an operator overriding one env var would silently
drop everything else).

## D8 — Concurrency: capture serialises on the source; clones are otherwise independent

**Decision**: Clone registers as an environment-level operation on the **source**
while its capture is non-terminal — the existing one-op-per-environment guard
(`_guard_no_environment_operation_in_progress`,
`services/backup/environment.py:277-305`) applies, extended to also see non-terminal
clones of that environment. A second clone of the same source started during the
first's **capture window** is rejected upfront with the existing typed
`EnvironmentOperationInProgressError`. Once the capture is terminal, the clone stops
occupying the source, and further clones (or backups/restores) may start while the
first clone is still building its new environment. Clones of *different* sources
never interact.

**Rationale**: the idea brief's "concurrent clones, independent backups, no lock" is
achievable after capture but not during it: the per-instance
`BackupAlreadyInProgressError` guard means two overlapping captures of the same
deployments would degrade both clones to `PARTIAL` anyway, and ADR-055 decision 5
deliberately enforces one environment-level operation per environment. Serialising
only the capture window preserves the brief's intent (independent artefacts, no
long-lived lock spanning the whole clone) without weakening shipped invariants. The
spec's edge case is updated to say exactly this.

## D9 — FR-008 delete guard: `IN_USE` typed error, narrowly scoped, escape hatch preserved

**Decision**: `delete_environment_backup` gains one guard: if a **non-terminal**
`EnvironmentClone` references the backup, raise a new
`EnvironmentBackupInUseByCloneError` (`error_code="IN_USE"`, metadata: clone id/name)
— precedent `BackupStorageLocationInUseError`
(`services/exceptions.py:443-459`). Terminal clones never block deletion.

**Rationale**: ADR-055 decision 6 made unguarded deletion the escape hatch for
operations pinned non-terminal, so this guard is a deliberate, documented deviation
(FR-008) and must not create an un-deletable backup: the escape remains, because
deleting the clone's created environment (or the capture itself failing) drives the
clone terminal, which releases the guard. `created_environment_id` is `ON DELETE SET
NULL`; a clone whose created environment vanished derives `FAILED` (terminal).

## D10 — GraphQL surface

**Decision** (details in `contracts/graphql.md`): one mutation
`cloneEnvironment(...) → EnvironmentClone!` gated `ADMIN`
(`_requires(Role.ADMIN)`, `mutation.py:152-154`; rationale mirrors
`restoreEnvironmentBackup` — clone strictly supersets the config-writing footprint,
ADR-055 decision 7). Read surface: `environmentClone(environmentCloneId)`,
`environmentClones(environmentId)` (by source), plain non-null lists, no pagination —
matching the environment-backup query conventions (`query.py:339-387`). The
`EnvironmentClone` type follows the `db_model: strawberry.Private[...]` +
computed-`status()` pattern (`api/definitions/backup/environment_backup.py:109-232`),
with its own hand-mirrored status enum (strawberry binds one GraphQL name per Python
class — same reason `EnvironmentRestoreStatus` is mirrored).

## D11 — Surface parity (SDK, CLI, frontend)

- **SDK**: `EnvironmentCloneResource` (`create/get/list/wait_for_clone`) following
  the outer-wrapper + facade pattern (ADR-037,
  `python_sdk/src/styrmin_sdk/resources/environment_backups.py`); one named operation
  per `.graphql` file; regenerate via `uv run invoke generate`.
- **CLI**: new Cyclopts sub-app `env-clones` (`create/get/list`) mirroring
  `cli/src/styrminctl/commands/environment_backups.py` — `create <source-env> --name
  <new-name> [--deployment ...]* [--config-override <json|@file>] [--wait]`, terminal
  status reporting via the `_report_terminal_status` pattern (exit 1 on
  FAILED/PARTIAL).
- **Frontend**: a Clone action on the environment detail page opening a dialog
  (name, per-deployment include checkboxes, optional config override), plus a Clones
  list section beside the Backups tab content, polling the derived status via
  TanStack Query with the tab-scoped `refetchInterval` pattern
  (`EnvironmentBackupsTab.tsx:47`); invalidation in `onSuccess`.

## D12 — Test strategy

- **Propagation tests** (Constitution §V): every new GraphQL field/argument/mutation
  covered under `backend/tests/functional/graphql/` with named operations in
  `operations/*.graphql`, asserting through the real repository — recipe of
  `dev/guides/graphql-propagation-tests.md`; model file
  `test_environment_backup.py`.
- **Unit**: derived clone status matrix (mirroring
  `test_environment_backup_projects_derived_status_from_the_database`), merge
  utility, selection validation, D9 delete guard, cross-target `create_restore`
  guard/flip behaviour.
- **E2E** (heavy, `shard_backup`): extend `backend/tests/e2e/test_backup_restore.py`
  with one dual-entrypoint `@pytest.mark.ci` node
  `test_environment_clone_lifecycle`, reusing `scenario_environment_id`,
  `deployed_simple_app`, `velero_ready` (reuse-before-you-boot: same stack the
  environment backup E2E already deploys). Flow: write data marker (existing
  `portforward_simple_app` + `/count` recipe) → clone with the marker present →
  mutate source post-capture → assert clone data = capture point (SC-004), source
  unchanged (SC-002), all deployments attributed (SC-003), clone reaches terminal →
  delete cloned environment, re-clone same name succeeds (SC-005). Scenario-driver
  protocol gains `clone_environment` / `get_environment_clone` /
  `wait_for_environment_clone` implemented by both API and UI drivers (ADR-038).
- **Local PASS evidence** recorded per Constitution §V (node id, command, timestamp,
  cluster id, verbatim PASSED line).

## Resolved unknowns

| Unknown (from Technical Context) | Resolution |
|---|---|
| Can Velero restore into a different namespace? | Yes — native `namespaceMapping`; already wired in our builder (D1). |
| Can constituent restores target a different deployment? | Not today — `create_restore` + flow + recovery are in-place-coupled at six identified points (D2); all in code we own. |
| Do backup strategies survive cross-target? | Hook selectors and credential reads are target-namespace-relative; expected to work unchanged (D2). |
| How does a clone wait for its capture? | New INTERNAL Prefect flow — first sanctioned waiting orchestration (D4). |
| How are counterpart driver versions bound? | `deploy_application(driver_version_id=...)` pin resolved from the snapshot fingerprint (D5). |
| What does "merge override" mean? | Top-level-field replacement over canonicalised configs (D7). |
| Concurrent clones? | Serialised during capture via the existing guard, independent after (D8). |
| FR-008 vs the no-guard escape hatch? | Narrow `IN_USE` guard on non-terminal clones only; escape preserved (D9). |
