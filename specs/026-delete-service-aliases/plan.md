# Implementation Plan: Deleting a Deployment Deletes Its Service Aliases

**Branch**: `fac/services-cleanup-zk1ti` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/026-delete-service-aliases/spec.md`

## Summary

When a user deletes a deployment, its service aliases stay in the other deployments' namespaces ([#503](https://github.com/opsmill/styrmin/issues/503)). Two changes fix it:

- The operator's teardown gets a first step that lists the aliases in all namespaces and deletes those of the deployment, found by the `styrmin.io/deployment-id` label or, without the label, by the namespace that `spec.externalName` points into. The step is best-effort, runs on both deletion paths, and is skipped with the rest of the teardown for a CR annotated `styrmin.io/skip-teardown` (research R-001, R-002). It deletes no alias when the CR has no deletion request and its namespace is being deleted, as a restore does, because that deployment keeps running (R-011).
- The "Apply service aliases" flow reads, at write time, whether each namespace it writes into or points into is departing: the Namespace is missing or `Terminating`, or its StyrminDeployment has `spec.deletionRequested` or a `deletionTimestamp`. It skips those aliases, writes the others, reads again, and deletes any alias it wrote whose owner became departing in between. It no longer creates namespaces (R-003 to R-005).

The context that the server builds does not change, so driver templates still see a `DELETING` deployment's services (R-006).

## Technical Context

**Language/Version**: Python 3.14+

**Primary Dependencies**: kopf (operator handlers), Prefect (alias flow and tasks), `kubernetes_asyncio` (API calls through the injected primitives), Pydantic v2 (`WrittenAlias`)

**Storage**: N/A. No database, GraphQL or Alembic change.

**Testing**: pytest unit tests with mocked Kubernetes primitives; one E2E test on the session vcluster (`shard_general`, `api_only`)

**Target Platform**: The agent: the kopf operator and the Prefect worker in one process (`entrypoint/combined.py`), on Kubernetes

**Project Type**: Web service backend (agent side)

**Performance Goals**: The teardown adds one cluster-wide `list` of Services by label and one `delete` per alias. The alias flow adds two `get` calls (Namespace and StyrminDeployment) per distinct namespace, twice per flow run; an environment has a few deployments.

**Constraints**:

- Best-effort teardown: no new failure mode for a deletion (FR-004).
- The flow must never create a namespace it does not own (FR-008).
- Errors that today fail the alias step, such as RBAC or API errors, still fail it.

**Scale/Scope**: About five source files and four test files change, plus five documentation files and one changelog fragment.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
| --- | --- | --- |
| I. Declarative reconciliation | Pass | The teardown and the flow stay idempotent: a 404 counts as deleted, and a re-run writes or deletes the same objects. |
| II. Driver-based deployment | Pass | No driver change. |
| III. Layered architecture | Pass | Agent-side change only; the server's service layer is unchanged. |
| IV. Type safety | Pass | Typed signatures and a Pydantic `WrittenAlias`; `ty` and `ruff` run before each commit. |
| V. Tests, E2E definition of done | Pass | Unit tests for every FR-014 item; one new E2E test that reuses `discovery_deployments` and boots no deployment; local PASS evidence required before the work is done. No GraphQL change, so no propagation test. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit. |
| VII. Documentation accuracy | Pass | `CONTEXT.md`, `operator.md`, `orchestration-flows.md`, `generic-app.md` and ADR-073 change in the same branch. |
| Governance gates | None triggered | No schema, GraphQL, dependency, CI or authorization change; the existing ClusterRole allows the reads and deletes (R-009). |

Post-design re-check: still passes. The design adds no component and no shared state.

## Project Structure

### Documentation (this feature)

```text
specs/026-delete-service-aliases/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── internal-interfaces.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── agent/
│   ├── service/kubernetes/primitives.py   # get_namespace, apply_service, is_namespace_gone_error
│   └── tasks/
│       ├── service_aliases.py             # departing check, WrittenAlias, flow changes
│       └── orchestration.py               # call sites drop namespace_labels
└── operator/handlers/styrmin_deployment.py # _delete_service_aliases, teardown signature

backend/tests/
├── unit/
│   ├── agent/test_service_aliases.py               # flow guard, re-read, no namespace creation
│   ├── agent/test_apply_service.py                 # new: create-then-replace, namespace-gone errors
│   ├── test_deployment_deletion_operator.py        # teardown alias step, skip-teardown
│   └── services/test_context_deleting_peer_services.py  # new: context lists a DELETING peer's services
└── e2e/test_service_discovery.py                    # new last test

CONTEXT.md
dev/knowledge/agent/operator.md
dev/knowledge/backend/orchestration-flows.md
dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md
docs/docs/drivers/generic-app.md
changelog/503.fixed.md
```

**Structure Decision**: The fix stays in the two places that own aliases today: `agent/tasks/service_aliases.py` for writing and `operator/handlers/styrmin_deployment.py` for the teardown. New Kubernetes calls go into `primitives.py`, next to `list_services_in_all_namespaces` and `delete_service`, which #506 added there.

## Design

### Teardown (operator)

1. `_teardown_owned_resources` takes `deployment_id` and runs `_delete_service_aliases` as its first step, logged as "Teardown step 1: service aliases of `<id>` in all namespaces". The existing steps become 2 to 4.
2. `_delete_service_aliases` checks that the namespace is `styrmin-<deployment_id>` (R-001). Without `spec.deletionRequested`, it also reads the Namespace and stops when it is `Terminating`, gone or unreadable (R-011). It then lists `styrmin.io/service-alias=true` in all namespaces, filters with `is_alias_of_deployment`, and deletes each alias with `delete_service`. It logs and continues on every error and never raises (R-002).
3. `kopf_on_styrmin_deployment_deletion_requested` and `kopf_on_styrmin_deployment_delete` pass `spec.get("deploymentId", "")` and `spec.get("deletionRequested", False)`. The skip-teardown branch of the delete handler returns before the teardown, as today.

### Alias flow (agent)

1. `apply_service_aliases(aliases, stale_aliases)` loses `namespace_labels` and its `apply_namespace` calls.
2. It computes the namespaces involved, calls `find_departing_namespaces` (reads run concurrently), and drops aliases whose holder or owner namespace is departing and stale aliases in a departing namespace. It logs each dropped alias.
3. `apply_single_alias` writes with `apply_service` and returns a `WrittenAlias`, or `None` when the namespace is gone or terminating (R-005).
4. After the stale deletions, it calls `find_departing_namespaces` on the owners of the written aliases and deletes, with the write's `resourceVersion`, each written alias whose owner became departing and whose holder did not (R-004).
   - Changed on 2026-10-17, after the code review: the second read uses `find_deleted_deployment_namespaces`, the operator teardown's rule, so a restore's namespace deletion does not count, and the flow deletes a written alias whatever namespace holds it (research R-004).

### Ordering argument

The teardown lists the aliases only after the CR's `spec.deletionRequested` is set, and the flow's second read happens after its write. So every alias written before the second read either is in the teardown's list or is deleted by the flow (research R-004).

Changed on 2026-10-17, after the code review: one case remains. When the StyrminDeployment is already removed at the second read, the read does not count it, so an alias written after the delete handler's teardown listed the aliases, and before the removal, can remain (research R-004).

### What stays the same

- The context builder and the `DeployedService` lifecycle (R-006).
- The stale-alias deletion of #506, apart from skipping departing namespaces.
- The step `resource:service-aliases` that the CRD flows report.

## Testing

| Spec item | Test |
| --- | --- |
| FR-001 to FR-003, FR-014 item 1 | `test_deployment_deletion_operator.py`: labelled and unlabelled aliases of the deployment are deleted; aliases of another deployment, including one in another environment, are not; the step runs before the namespace deletion request |
| FR-004, FR-014 item 2 | same file: 404 counts as deleted; a delete error and a list error are logged and the namespace deletion still runs; a namespace that is not `styrmin-<deploymentId>` deletes nothing |
| FR-005 | same file: the `kubectl delete` handler runs the alias step |
| FR-006, FR-014 item 5 | same file: the skip-teardown annotation makes no list or delete call |
| FR-017, SC-006 | same file: the delete handler with `deletionRequested: false` and a `Terminating` or missing namespace deletes no alias; a failed namespace read deletes none; with `deletionRequested: true` and a `Terminating` namespace it deletes them |
| FR-007, FR-008, FR-014 item 3 | `test_service_aliases.py`: (a) a context that lists a peer whose CR has `deletionRequested`: no alias of the peer and nothing into its namespace; (b) the flag appears between the two reads: the written alias of the peer is deleted with its `resourceVersion`; (c) a missing or `Terminating` namespace: skipped, no `apply_namespace` call; (d) a 403 `NamespaceTerminating` or 404 on write: skipped, the flow succeeds; (e) an RBAC 403 still fails |
| FR-009 | `test_service_aliases.py`: with no departing namespace, the flow writes the same aliases as today |
| FR-010, FR-014 item 4 | `test_context_deleting_peer_services.py`: a context built while a peer is `DELETING` lists the peer's service in `services` and `deployed_services` |
| FR-014 item 6 | `test_apply_service.py`: a 409 on create replaces with the `ClusterIP` manifest; `apply_kubernetes_resource` for a `Service` delegates to it |
| FR-007 race, SC-002 | `test_service_aliases.py`: the deletion flag appears between the flow's two reads; the alias of that deployment that the flow wrote is deleted |
| FR-015 | `test_service_discovery.py::test_deleted_deployment_leaves_no_alias` (R-008). Before writing it, check that no later `shard_general` module uses `intent` or counts the scenario environment's deployments |

## Documentation

- `CONTEXT.md`: the "Service alias" entry from the brief, right after the **Service** (deployed service) entry; `CONTEXT.md` groups entries by topic.
- `dev/knowledge/agent/operator.md`, "Deletion": the teardown order with the new first step, the namespace check, that the step is best-effort, and that a restore's namespace deletion deletes no alias.
- `dev/knowledge/backend/orchestration-flows.md`, "Service aliases": the departing rule, the second read, and that the flow never creates a namespace.
- `docs/docs/drivers/generic-app.md`, "Networking": deleting a deployment deletes its aliases in the other namespaces.
- ADR-073, "More information": remove the known case for deployment deletion and state that the teardown finds aliases by the owner's id.
- `changelog/503.fixed.md`: what the brief asks (FR-012).

## Complexity Tracking

No constitution violation to justify.
