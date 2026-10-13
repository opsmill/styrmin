# Implementation Plan: Update a Cluster's Config in Place

**Branch**: `fac/cluster-settings-9vkqq` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/021-cluster-config-update/spec.md`

## Summary

Administrators can set a cluster's config only at creation time. This feature adds an `updateCluster` mutation with a typed `UpdateClusterInput`, an SDK `clusters.update` method and a `styrminctl clusters update` command. The update replaces the whole cluster config, recomputes the cluster capabilities and saves the row, then runs a **cluster config fan-out**: in every environment of the cluster, it redeploys each live, non-internal deployment whose resolved config (cluster → environment → deployment) differs from the resolved config of its active instance ([research.md](research.md) D1).

When the effective `dedicated_ingress` of an environment changes, the fan-out also manages that environment's dedicated ingress controller. Applications move to a controller only once it is `RUNNING`, and a controller is removed only once its applications have finished moving off it. The status reporter drives both steps: a controller that reaches `RUNNING` re-runs its environment's fan-out, and an application that reaches `RUNNING` or `FAILED` re-runs the controller removal check (D4, D5). In P2, an edit dialog on the cluster detail page submits the same mutation and keeps every value the form does not show (D11).

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3, React 19 (frontend, P2)

**Primary Dependencies**: Strawberry GraphQL, SQLModel/SQLAlchemy (async), Pydantic v2, Prefect (existing `apply_state` flow only), Cyclopts (CLI), httpx and ariadne-codegen (SDK); TanStack Form, Zod and TanStack Query (frontend)

**Storage**: PostgreSQL. No schema change: `cluster.config` and `cluster.capabilities` are existing JSON columns. No Alembic revision.

**Testing**: pytest (unit, functional GraphQL propagation, E2E on vCluster), CLI tests in `cli/tests/`, Vitest and React Testing Library (frontend)

**Target Platform**: Styrmin server and agent on Kubernetes; `styrminctl` on Linux and macOS

**Project Type**: Web service with GraphQL API, Python SDK, CLI and React SPA

**Performance Goals**: The resolved-config comparison runs without driver or chart lookups (D1). An update over a cluster with tens of deployments returns in the same order of time as `updateEnvironment` today, where each redeploy start dominates.

**Constraints**:

- The cluster row is committed before any redeploy starts (FR-001).
- Applications in an environment that changes its dedicated ingress stay reachable during the change (FR-004, SC-005).
- The status reporter must not fail because of the fan-out continuation (savepoint, D7).
- A misspelled key in the CLI config file must not clear a value (D3).

**Scale/Scope**: One cluster (ADR-039), a few environments, tens of deployments.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How the plan meets it |
|---|---|---|
| I. Declarative state reconciliation | Pass | A cluster change now reaches the deployments (architecture.md §3.5 becomes true for the cluster). The per-deployment comparison makes a resubmission a no-op (SC-003). |
| II. Driver-based deployment | Pass | Redeploys reuse the bound driver version through `redeploy_for_environment_update`; no ad-hoc rendering. |
| III. Layered architecture | Pass | Resolver → `services.clusters.update_cluster` → `services.cluster_config_fanout` → repositories under one `UnitOfWork`. The status reporter hook calls the service layer. |
| IV. Type safety and typed errors | Pass | Existing `ServiceError` subclasses only: `InvalidContextError`, `ClusterNotFoundError`, `EnvironmentOperationInProgressError`, `AmbiguousIdentifierError`. No union error types. |
| V. Test-first development | Pass | Unit suites for the update service, the fan-out and the controller ordering; a propagation test for `updateCluster`; CLI tests; one `api_only` E2E (P1) and one `ui_only` E2E (P2) with local pass evidence (D10). |
| VI. Format and lint | Pass | `uv run invoke format lint` and `pnpm lint` before each commit. |
| VII. Documentation accuracy | Pass | Documentation tasks listed below, including ADR-0066 (D9). |
| Governance gate: GraphQL schema change | Crossed, approved | One new mutation and three new input types. Recorded as crossed in the PRD's governance list, decided with the issue author in the requirements session (2026-10-12). |
| Governance gates: database, dependencies, CI/CD, auth | Not crossed | No migration, no new package, no workflow change (no new shard), the existing `ADMIN` permission extension. |

**Post-design re-check**: Pass. The design adds no persisted state, no new task type and no new flow. The one new cross-cutting behaviour (status reporter continuation) follows the existing `tear_down_unused_ingress_controller` precedent and is recorded in ADR-0066.

## Project Structure

### Documentation (this feature)

```text
specs/021-cluster-config-update/
├── plan.md              # This file
├── research.md          # Decisions D1–D12
├── data-model.md        # Cluster, resolved config, controller states, counts
├── quickstart.md        # Validation guide
├── contracts/
│   ├── graphql.md       # updateCluster, UpdateClusterInput, propagation test
│   └── sdk-cli.md       # clusters.update, styrminctl clusters update
├── checklists/
│   └── requirements.md
└── tasks.md             # Created by /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── context/resolvers.py                       # + resolve_instance_config (public)
├── services/clusters.py                       # + update_cluster, _apply_cluster_defaults
├── services/cluster_config_fanout.py          # NEW: fan_out_cluster_config, continue_environment_fan_out
├── services/deployment.py                     # + _create_ingress_controller; extended tear_down_unused_ingress_controller
├── services/deployment_status.py              # + hooks on RUNNING (internal) and RUNNING/FAILED (application)
├── api/definitions/config/inputs.py           # + StandardStorageInput, FastStorageInput
├── api/definitions/cluster/inputs.py          # NEW: UpdateClusterInput, update_cluster_input_to_dict
└── api/schema/mutation.py                     # + updateCluster (ADMIN)

backend/tests/
├── unit/context/test_resolve_instance_config.py
├── unit/services/test_cluster_update.py
├── unit/services/test_cluster_config_fanout.py
├── unit/services/test_ingress_controller_ordering.py
├── unit/services/test_deployment_status_fanout_hooks.py
├── functional/graphql/test_cluster_update_propagation.py
├── e2e/helpers/ingress.py                     # moved helpers from test_ingress_controller.py
└── e2e/test_cluster_update.py                 # NEW (shard_compute)

python_sdk/src/styrmin_sdk/
├── graphql/update_cluster.graphql             # NEW
├── graphql/_generated/                        # regenerated
├── resources/clusters.py                      # + update
└── __init__.py                                # export UpdateClusterInput

cli/src/styrminctl/
├── commands/clusters.py                       # + update
└── output.py (or a new strict-input module)   # + validate_input_strict
cli/tests/test_clusters.py

frontend/src/
├── graphql/update_cluster.graphql             # NEW
├── generated/graphql.ts                       # regenerated
├── components/cluster/ClusterConfigFields.tsx # extracted from CreateClusterDialog
├── pages/settings/CreateClusterDialog.tsx     # uses ClusterConfigFields
├── pages/clusters/EditClusterDialog.tsx       # NEW (P2)
├── pages/clusters/ClusterDetailPage.tsx       # + Edit button (ADMIN only)
└── __tests__/EditClusterDialog.test.tsx

backend/tests/e2e/pages/cluster_detail.py      # + edit dialog page object (P2 E2E)

schema.graphql                                 # regenerated

docs/docs/reference/styrminctl.md
docs/docs/concepts-and-architecture/ingress-and-networking.md
docs/docs/concepts-and-architecture/reconciliation.md
dev/knowledge/architecture.md                  # §3.5
dev/knowledge/backend/data-models.md           # Cluster section
dev/adr/0066-cluster-config-fanout.md          # NEW
CONTEXT.md                                     # Config fan-out entry
changelog/423.added.md                         # NEW
```

**Structure Decision**: The existing web-service layout (backend, SDK, CLI, frontend). The fan-out gets its own service module (D8) so that it has its own test suite and `services/deployment.py` does not grow further.

## Implementation Phases

1. **Foundation**: `resolve_instance_config`; `_apply_cluster_defaults` shared with `create_cluster`; `_create_ingress_controller` extracted with `_ensure_ingress_controller` unchanged in behaviour.
2. **US1 core (P1)**: `update_cluster` (guard, defaults, validation, capabilities, commit); `fan_out_cluster_config` without the controller rules (applications only, skip rules, counts, log line); a unit test that an instance generated by `generate_context_from_deployment` is found at config when the cluster config does not change (critique E7); GraphQL input and mutation; schema export; propagation test; SDK operation and method; `uv run invoke generate`; CLI command with the strict-key guard, a result message that says redeploys started, and `clusters get`/`clusters update` printing the config as JSON (critique P2, P3); tests.
3. **US2 (P1)**: controller actions and the per-application rule (D4); extended removal rule, including "the controller is not `PENDING` or `DEPLOYING`" (D5); status reporter hooks inside a savepoint, with the `cluster_config_fanout_continued` log line (D7); ordering unit tests, including a resubmission after a failed turn-on (applications do not move onto the failed controller) and an environment update that turns `dedicated_ingress` off (controller removed after the applications move).
4. **E2E (P1)**: move helpers to `e2e/helpers/ingress.py`; `test_cluster_update_redeploys_and_moves_dedicated_ingress` (`api_only`), local pass evidence; full `shard_compute` run.
5. **US3 (P2)**: frontend operation and codegen; `ClusterConfigFields` extraction; `EditClusterDialog` that carries unseen values; ADMIN gating; Vitest; `ui_only` E2E with page object, local pass evidence.
6. **Documentation**: ADR-0066; CONTEXT.md; architecture.md §3.5; data-models.md; `docs/` pages, including the change to the environment update's controller removal (critique E2), how to revert an update by resubmitting the previous file, and that the file must hold the current config because the last update wins (critique E9, P5); changelog fragments for the new command and for the environment update change.

## Risks

| Risk | Mitigation |
|---|---|
| A Styrmin upgrade changes the resolved-config computation, so the first cluster update after it redeploys many deployments (D1). | Recorded in ADR-0066 and the docs. The redeploy is a Helm upgrade with the same values where nothing changed, so pods do not restart. |
| A status transition is lost (server restart between the report and the commit), so waiting applications are not moved. | A resubmission of the same config moves them (per-deployment comparison). Documented as the recovery path. |
| The E2E changes the shared session cluster and disturbs later tests in `shard_compute`. | The module sorts first in the shard, restores the original config in `finally`, and waits until no deployment of the cluster is `PENDING` or `DEPLOYING` (D10). The full shard is run once locally. |
| A storage class change fails a StatefulSet-based deployment and a resubmission does not retry it. | Documented limit and recovery (spec edge case, D12); same behaviour as the environment update. |
| The status reporter continuation slows status reports. | It runs only on a state transition, not on every report, and only for the environment of the deployment that changed state. |

## Follow-up Candidates (not in this feature)

- Strict unknown-key validation for every SDK input type through an `ariadne-codegen` plugin (research D3).
- A preview of the deployments that an update would redeploy (`--dry-run`) (critique P6).
- An optimistic concurrency check on the cluster update, so an old file cannot revert a newer update (critique P5).
- The environment update creating and redeploying the dedicated ingress controller (spec Out of Scope).

## Complexity Tracking

No constitution violations to justify.
