# Implementation Plan: A Clone Writes Its Own Service Aliases and Restores None of the Source's

**Branch**: `fac/alias-clone-fix-l1vzt` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/030-clone-service-aliases/spec.md`

## Summary

After an environment clone, each counterpart's namespace holds the source's service aliases, which point to the source environment's namespaces ([#530](https://github.com/opsmill/styrmin/issues/530)). Three changes fix it:

- The cross-target restore's Velero Restore gets a label selector that leaves out every Service labelled `styrmin.io/service-alias=true`. In-place restores render as today (research R-001).
- After "Run the recovery" succeeds, the cross-target restore runs the step "Create and delete service aliases", the same step that the create, update and upgrade flows run. It reads the new environment's services from the server and writes the aliases in both directions between the counterpart and every other deployment of the new environment whose namespace exists. A failed alias write fails the restore with the error; the counterpart's status then follows its workloads (R-002 to R-004).
- The clone record reports the entry of a counterpart whose restore failed as `failed`, with the restore's error as the reason (FR-007, R-006).

## Technical Context

**Language/Version**: Python 3.14+

**Primary Dependencies**: Prefect (the INTERNAL and USER restore flows, the alias subflow), Velero 1.18.1 (Restore `spec.labelSelector`), `kubernetes_asyncio` (alias writes through the existing primitives), Strawberry GraphQL (the clone entry projection), Pydantic v2 (`GlobalContext` as a flow parameter)

**Storage**: N/A. No database, Alembic or GraphQL schema change.

**Testing**: pytest unit tests (builders, restore steps, alias step, clone status), one functional GraphQL test, and two existing E2E nodes extended on the session vcluster (`shard_env_backup`, both variants)

**Target Platform**: The Styrmin server (INTERNAL flows, GraphQL) and the agent's USER work pool (Kubernetes Jobs), on Kubernetes

**Project Type**: Web service backend

**Performance Goals**: A cross-target restore adds one GraphQL read and the alias writes of one deployment, a few Kubernetes calls per peer.

**Constraints**:

- At no point does a counterpart's namespace hold an alias to the source environment (FR-001).
- In-place and environment restores do not change (FR-006).
- The alias step's skip rules of #503 stay as they are (ADR-077, ADR-078).

**Scale/Scope**: About six source files and six test files change, plus seven documentation files and one changelog fragment.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative state reconciliation | Pass | The counterpart's aliases come from the server's records of the new environment, not from the source's cluster state. The alias write is idempotent (`apply_service`). |
| II. Driver-based deployment | Pass | No driver change. |
| III. Layered architecture | Pass | The entry fold is a service-layer function (`services/backup/clone.py`) that the GraphQL type calls. The flows reach the database through the unit of work, as today. |
| IV. Type safety and typed errors | Pass | No new error type. The alias step's error becomes the restore's error message. `counterpart_context` is typed `GlobalContext | None`. |
| V. Test-first development | Pass | Unit tests per changed module, one functional GraphQL test for FR-007, and two existing E2E nodes extended (no new node; "Reuse before you boot"). Local PASS evidence is recorded for both nodes in both variants. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit. |
| VII. Documentation accuracy | Pass | User docs, knowledge doc, ADR-056 amendment, `CONTEXT.md` and changelog in the same change (research R-010). |
| Governance gates | Pass | No schema, migration, GraphQL schema, dependency, CI, or authorization change (R-011). FR-007 changes what two existing fields return in one case; flagged in the spec's Clarifications. |

Post-design re-check: unchanged. The design adds one flow parameter and one service function, and moves one helper.

## Project Structure

### Documentation (this feature)

```text
specs/030-clone-service-aliases/
├── plan.md                         # This file
├── research.md                     # Phase 0 output
├── data-model.md                   # Phase 1 output
├── quickstart.md                   # Phase 1 output
├── contracts/
│   └── internal-interfaces.md      # Phase 1 output
├── checklists/requirements.md      # Spec quality checklist
└── tasks.md                        # Phase 2 output (speckit-tasks)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── agent/service/kubernetes/
│   ├── velero/resources.py                    # VeleroRestore.label_selector (new field)
│   └── resources/builders/backup.py           # cross-target label selector
├── agent/tasks/
│   ├── service_aliases.py                     # apply_service_aliases_step (moved here)
│   └── orchestration.py                       # callers use the moved step
├── workflows/templates/backup.py              # counterpart_context; alias step after recovery
├── services/backup/clone.py                   # resolve_deployment_result; derivation uses it
└── api/definitions/backup/environment_clone.py  # deployment_results applies the fold

backend/tests/
├── unit/agent/test_backup_builders.py
├── unit/agent/test_service_aliases.py
├── unit/workflows/test_restore_steps.py
├── unit/services/backup/test_environment_clone_status.py
├── functional/graphql/test_environment_clone.py
└── e2e/test_backup_restore.py                 # two existing nodes extended

docs/docs/concepts-and-architecture/
├── backups-and-restores.md
└── ingress-and-networking.md
dev/knowledge/backend/orchestration-flows.md
dev/adr/0056-environment-clone-record-and-cross-target-restore.md
CONTEXT.md
changelog/530.fixed.md
```

**Structure Decision**: Backend only. The frontend, the CLI and the SDK read the clone entry from the API and need no change (research R-006).

## Design

### Restore request (R-001)

`VeleroRestore` gets `label_selector: dict[str, Any] | None = None`, rendered as `spec.labelSelector` only when set. `build_velero_restore` sets it, in the branch where `source_namespace != target_namespace`, to a `matchExpressions` entry `styrmin.io/service-alias NotIn ["true"]`. The key comes from `SERVICE_ALIAS_LABEL` (`agent/service/kubernetes/service_alias_rules.py`), so the selector and the alias builder use one constant.

### Alias step at the end of a cross-target restore (R-002 to R-004)

- `execute_restore_workflow` (INTERNAL) loads the counterpart's active instance once, for a cross-target restore, and passes both the StyrminDeployment body and the instance's context to the USER flow. `_build_counterpart_crd_body` returns both, or a new helper wraps it.
- `execute_velero_restore_flow` (USER) gets `counterpart_context: GlobalContext | None = None`. After the recovery step succeeds and when `counterpart_context` is set, it calls `apply_service_aliases_step(reporter, counterpart_context)`.
  - On success, `recovery_status` stays `recovered: true`.
  - On an exception, the step is already recorded as failed. The flow sets `recovery_status` to `recovered: false` with `error: "Service alias step failed: <error>"`. It does not mark the StyrminDeployment failed (R-004, critique E1).
- The INTERNAL flow needs no other change: a `recovered: false` result already fails the restore with `recovery.error` and sets the counterpart to `FAILED`.
- `apply_service_aliases_step` moves from `orchestration.py` (`_apply_service_aliases_step`) to `service_aliases.py`. Its behaviour does not change.

### Clone entry of a failed restore (R-006)

- `failed_restore(restore_id, restores) -> Restore | None` in `services/backup/clone.py` returns the restore row when it is `FAILED`. `derive_environment_clone_status` calls it where it now tests the row inline; nothing else in the derivation changes.
- `resolve_deployment_result(result: CloneDeploymentResult, restores: Mapping[UUID, Restore]) -> CloneDeploymentResult`: when `result.outcome` is `cloned` and `failed_restore` returns a row, it returns a copy with outcome `failed` and reason `the restore failed: <error_message>` (or `the restore failed`). The counterpart and restore ids stay on the entry.
- `EnvironmentClone.deployment_results` passes each readable entry and `self.referenced_restores` through it. Unreadable entries keep their current projection.

### What stays the same

- In-place restores: no label selector, no `counterpart_context`, no alias step, the same three steps.
- Environment restores: one in-place restore per constituent.
- The alias step's rules of #503: departing namespaces, stale aliases, the second read, the fallback when the server cannot be read.
- The clone flow: it still sets an entry to `cloned` when it dispatches the restore.

## Testing

- `test_backup_builders.py`: a cross-target restore renders the label selector; an in-place restore renders none; the selector key is `SERVICE_ALIAS_LABEL`.
- `test_service_aliases.py`: with a counterpart's context and a server list that holds a cloned peer and a counterpart whose restore failed, `compute_service_aliases(with_current_peer_services(...))` writes aliases in both directions for both, names no source namespace, and has none for a source deployment without a counterpart.
- `test_restore_steps.py`:
  - a cross-target restore records "Create and delete service aliases" after "Run the recovery";
  - a refused alias write fails that step, does not call `mark_failed`, and returns `recovered: false` with the error;
  - the INTERNAL flow passes `counterpart_context` for a cross-target restore only, and a USER result with the alias error fails the restore with that `error_message` and sets the counterpart to `FAILED` (critique E4);
  - an in-place restore records the same three steps as today.
- `test_environment_clone_status.py`: `resolve_deployment_result` turns a `cloned` entry with a `FAILED` restore into `failed` with the reason, and leaves the other cases unchanged; for the same entries and restores, the entries read and `derive_environment_clone_status` agree (critique E2).
- `functional/graphql/test_environment_clone.py`: the case `a-cloned-entry-whose-restore-failed` also asserts the entry's `outcome` and `reason` through the resolver (FR-007).
- E2E (research R-009): `test_environment_clone_lifecycle` checks SC-001 right after the first clone reports `COMPLETED` and SC-002 on a re-clone of the primary only; `test_environment_backup_and_restore_lifecycle` checks SC-003. Each node runs in both variants, one variant per pytest session, with `--pdb`.

## Documentation

See research R-010. The `CONTEXT.md` change extends the existing "Service alias" entry with the sentence that an uncommitted draft on this branch held before it was rebased on `f4e60189`: "An **environment clone** writes the aliases of the new environment and never restores the source's aliases. See [issue #530](https://github.com/opsmill/styrmin/issues/530)."

## Complexity Tracking

No constitution violations.
