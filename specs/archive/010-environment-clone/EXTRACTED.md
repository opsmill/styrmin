# Extraction Record

**Extracted on**: 2026-10-13
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-056](../../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md) was
written during implementation and already records research.md D2–D10.

## ADRs Amended

- [dev/adr/0056-environment-clone-record-and-cross-target-restore.md](../../../dev/adr/0056-environment-clone-record-and-cross-target-restore.md)
  - §2: the `restore_pvs=False` constraint on the data path, and the `DeploymentSnapshot` fields `service_name_overrides` and `release_reference`.
  - §3: corrected the recovery order after commits `9023235b` and `59b664bb`.
  - §6: the deployment outcome is a closed enum on the wire.
  - §9: corrected. Deleting the created environment fails only a clone that has not finished.
  - Consequences: the reasons for a waiting INTERNAL flow (D4) and what happens when the capture poll times out.
  - Alternatives: the alternatives rejected in D1, D4 and D5.
  - `Source` points at `specs/archive/010-environment-clone/`.

## Knowledge Updated

- `dev/knowledge/backend/backup-restore.md`
  - Data Models, Restore: `target_instance_id` on a cross-target restore
  - Workflow Flows: cross-target restore
  - Restore Lifecycle, stage 4: corrected (kopf annotations are kept)
  - Environment-Level Backup & Restore introduction
  - Environment Clone: service functions, Flow, the new "How the clone flow fails and recovers", Derived status markers, "Concurrency and the discard cascades"
  - Velero builders: cross-target options
  - Typed errors: clone errors
- `dev/knowledge/backend/services.md`
  - Deployment table: `deploy_application` signature, `request_cluster_teardown`
  - Environments table: the clone guard on `update_environment`
  - New "Deleting an environment"
  - Environment-config fanout: `redeploy_for_environment_update` returns `Task | None`
- `dev/knowledge/backend/api.md` (Queries, Mutations, `Environment.clonedFrom`, Enums)
- `dev/knowledge/agent/operator.md` (new "Name of the CR and the release reference"; Manual safety-net: `styrmin.io/skip-teardown`)
- `dev/knowledge/backend/e2e-testing.md` (`api_only` audit discipline: clone methods)
- `dev/knowledge/frontend/environment-backups.md` (new file: Clones tab, discard label contract)
- `CONTEXT.md` (Environment clone: attribution entries; new term "Cross-target restore")

## Guidelines Updated

- `dev/guidelines/backend/python.md`
  - Calculate a status that several writers change; do not store it: rules for inputs that can be deleted
  - Check for an operation in progress against its unfinished rows
  - Expire an in-flight guard when the flow it protects stops waiting
  - Merge by key when you update entries of a JSON list that another writer created
  - Show one unreadable JSON entry as degraded instead of failing the query
  - Read the Helm release name from the active instance; never compute it from the deployment id
  - In a polling loop, reuse one unit of work and roll it back before each sleep

## Other Changes

- `driver/DRIVERS.md`: new "Credentials in a driver that can be cloned" (promised in research D2).
- `docs/docs/concepts-and-architecture/backups-and-restores.md`: corrected the discard rule; a finished clone keeps its outcome.
- `backend/styrmin_backend/api/definitions/environment/model.py` (`clonedFrom`) and `backend/styrmin_backend/api/definitions/backup/environment_clone.py` (`sourceEnvironment`): descriptions now say that a clone that created an environment survives its source. `schema.graphql` and `frontend/src/generated/graphql.ts` were regenerated.
- `frontend/src/components/environment/EnvironmentClonesSection.tsx`: header comment corrected the same way.

## Already Documented Before Extraction

- ADR-056
- `dev/knowledge/backend/backup-restore.md` ("Environment Clone", "Cross-target restore")
- `CONTEXT.md` (Environment clone, Counterpart deployment)
- `docs/docs/concepts-and-architecture/backups-and-restores.md`, `docs/docs/reference/styrminctl.md`

## spec.md Changes at Extraction

- `**Status**` set to `Extracted`.

## Archive

Spec directory moved to `specs/archive/010-environment-clone/` as a historical record.
