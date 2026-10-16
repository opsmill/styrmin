# Implementation Plan: Per-Component Replica Counts

**Branch**: `fac/per-component-replica-1jel3` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/023-per-component-replicas/spec.md` (PRD: [#202 comment](https://github.com/opsmill/styrmin/issues/202#issuecomment-6187621046))

## Summary

A user can change a component's pod count today only when the driver wires a parameter into its values template. This change lets a user set a replica override on any component, lets a driver declare a default count and singleton components, and lets the `infrahub` drivers retire their two replica parameters without a manual step for deployments that kept the defaults.

Technical approach (details in [research.md](research.md)):

- Store the override at `DeploymentConfig.components.<name>.replicas` with a typed validator (D-001); type `replicas` and `singleton` on the driver's component model with a load-time contradiction check (D-002). No migration.
- One resolver for the order of precedence (override, driver default, chart), used by the patch builder, the write checks and the read field (D-003).
- Replace the stop patch builder with a component replica patch builder that emits at most one `spec.replicas` patch per kind per component: 0 when stopped, the resolved count, or none (D-004).
- Three write checks on every write path, including the check against the target driver version (D-005, D-006), and the rule that drops a retired parameter value equal to the current default and rejects any other value (D-007).
- No change to readiness: helm-controller's kstatus wait and the direct-apply polling already compare each workload with its post-rendered `spec.replicas` (D-008).
- GraphQL `ComponentConfigInput.replicas`, `Deployment.componentReplicas`, `ComponentConfig.replicas`/`singleton` (D-009); SDK, `styrminctl` and frontend surfaces (D-010, D-011).
- New example driver versions: `infrahub` 5 and `infrahub-enterprise` 4 (with `database`, `task-manager-db` and `cache` as singleton components), `simple-app` 4 (D-013); a dual-entrypoint E2E in `shard_configuration` that reads the workload once after each task to prove the task waited (D-012).

## Technical Context

**Language/Version**: Python 3.14+ (backend, agent, operator, SDK, CLI); TypeScript 5.9.3 with React 19 (frontend, Node 22)

**Primary Dependencies**: Strawberry GraphQL, SQLModel/SQLAlchemy (async), Pydantic v2, Jinja2, kopf; FluxCD helm-controller post-renderers (kustomize) and its kstatus wait; TanStack Query, TanStack Form and Zod (frontend). No new dependency.

**Storage**: PostgreSQL. No schema change and no Alembic revision: the override lives in `Deployment.config` (JSON), the driver declaration in `ApplicationDriverVersion.components` and `ComponentConfig.config` (JSON).

**Testing**: pytest (unit, integration with real `kubectl kustomize`, functional GraphQL propagation, E2E on vCluster in `shard_configuration`); Vitest and React Testing Library (frontend).

**Target Platform**: Styrmin server, agent and operator on Kubernetes; workloads patched by helm-controller post-renderers.

**Project Type**: Web service (backend, agent, operator, frontend) with a Python SDK, a CLI and example drivers.

**Performance Goals**: No new goal. At most two patches per component (one per workload kind), the same number the stop patch emits today. Scaling 1 → 2 and 2 → 1 pods completes within the HelmRelease timeout (SC-002).

**Constraints**:

- The same stored config gives the same patches (Constitution §I).
- No two patches write `/spec/replicas` on the same workload (D-004).
- A deployment whose driver declares no `replicas` or `singleton` and has no override renders the same patches as before (SC-006).
- Every new error is raised before any task, flow run or ingress dispatch.

**Scale/Scope**: About 20 backend files, 3 example drivers, 1 extended E2E module, 5 frontend components, 7 documentation pages, 1 new ADR.

All items are resolved; [research.md](research.md) has no open "NEEDS CLARIFICATION".

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How the design meets it |
|-----------|--------|-------------------------|
| I. Declarative state reconciliation | Pass | The count is part of the desired state; patches are rebuilt from the stored config on every render; clearing produces no patch (D-004) |
| II. Driver-based deployment | Pass | The driver declares defaults and singleton components; the override reaches pods through the post-render path of ADR-057 with no driver template code |
| III. Layered architecture | Pass | Write checks and the retired-parameter rule live in the service layer; resolvers call `resolve_replicas`; the agent reads only the context |
| IV. Type safety and typed errors | Pass | Four new `ServiceError` subclasses with codes and metadata ([contracts/errors.md](contracts/errors.md)); typed driver fields; frozen `ResolvedReplicas` |
| V. Test-first development | Pass | Dual-entrypoint E2E that runs in CI's `ui / configuration` cell, propagation tests for every new field, kustomize integration test, infrahub upgrade functional test (D-012, D-014). Local PASS evidence for both variants is required at implementation |
| VI. Format and lint | Pass | `uv run invoke format lint` and frontend lint in the tasks |
| VII. Documentation accuracy | Pass | Concept page, driver format pages, infrahub migration note, glossary, `styrminctl` reference, ADR-070, `dev/knowledge`, CONTEXT.md and changelog fragments in the same change (D-015) |
| Governance gates | Pass | GraphQL schema change is in the PRD (Governance Gates Crossed). No database schema change, no new dependency, no CI or auth change |

**Post-critique re-check** ([critiques/critique-2026-10-15.md](critiques/critique-2026-10-15.md)): Pass. E1 (serialisation) and E7 (E2E proves SC-002) were applied to research D-002 and D-012; P2 extends FR-011 to `task-manager-db` and `cache`.

**Post-design re-check**: Pass. Phase 1 added no dependency and no layer shortcut. It added one error code beyond the PRD's three (`UNKNOWN_COMPONENT_REPLICA_OVERRIDE`), which applies the existing unknown-component rule to the new slot (D-005).

## Project Structure

### Documentation (this feature)

```text
specs/023-per-component-replicas/
├── spec.md
├── plan.md               # This file
├── research.md           # D-001 to D-015, dependency evaluation
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql.md
│   ├── errors.md
│   ├── post-render-patch.md
│   ├── driver-format.md
│   └── cli-and-ui.md
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks output
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── context/models/
│   ├── config.py                              # ComponentConfigBlock.replicas + validator
│   └── components.py                          # ComponentContext.replica_override
├── context/resolvers.py                       # fill replica_override from DeploymentConfig
├── services/
│   ├── replicas/                              # new package
│   │   ├── __init__.py
│   │   ├── resolver.py                        # ReplicaSource, ResolvedReplicas, resolve_replicas, replica_patch_count
│   │   ├── patch_builder.py                   # build_component_replica_patches
│   │   ├── validator.py                       # validate_replica_overrides
│   │   └── exceptions.py                      # INVALID_REPLICA_COUNT, UNKNOWN_COMPONENT_REPLICA_OVERRIDE, SINGLETON_REPLICA_OVERRIDE
│   ├── parameters/
│   │   ├── retired.py                         # drop_retired_parameters (new)
│   │   └── exceptions.py                      # RETIRED_PARAMETER_VALUE (new or extended)
│   ├── deployment.py                          # call validators in _validate_config_write, deploy_application, update_deployment_version
│   └── driver/models/resources/driver.py      # ArbitrarySectionModel.replicas, .singleton, contradiction check
├── agent/service/kubernetes/resources/builders/application.py   # use build_component_replica_patches
└── api/definitions/
    ├── deployment/inputs.py                   # ComponentConfigInput.replicas
    ├── deployment/model.py                    # ComponentReplicas, ReplicaSource, Deployment.componentReplicas
    └── application_driver/model.py            # ComponentConfig.replicas, .singleton

backend/tests/
├── unit/services/replicas/                    # resolver, patch builder, validator
├── unit/services/driver/test_component_replicas.py
├── unit/services/parameters/test_retired.py
├── unit/agent/test_application_builder_replicas.py
├── unit/services/replicas/test_example_drivers_no_patch.py      # SC-006
├── unit/test_e2e_driver_conformance.py        # set_component_replicas
├── integration/test_component_container_kustomize.py            # replica and stop cases
├── fixtures/legacy_drivers/infrahub-v4/       # copy of the version 4 driver
├── functional/graphql/
│   ├── test_replica_overrides_propagation.py
│   ├── test_retired_parameters_propagation.py
│   ├── test_infrahub_replica_parameter_upgrade.py
│   └── test_application_driver_version_propagation.py           # ComponentConfig.replicas/singleton
└── e2e/
    ├── test_deployment_image_override.py      # + test_scale_server_and_singleton_guard (dual-entrypoint)
    ├── drivers/{protocol,api_driver,ui_driver}.py               # set_component_replicas
    ├── pages/deployment_detail.py             # set_component_replicas
    └── helpers/workloads.py                   # read_workload_replicas

python_sdk/src/styrmin_sdk/
├── graphql/get_deployment.graphql (+ driver operations)         # select new fields; regenerate _generated/
├── models/deployment_manifest.py              # OverrideKind += "replicas"
└── resources/deployments.py                   # _inapplicable_overrides covers replicas
cli/src/styrminctl/commands/deployments.py     # Replicas column; apply warning label

frontend/src/
├── graphql/{get_deployment,get_driver,deploy}.graphql
├── components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx (+ test)
├── components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx (+ test)
├── pages/deployments/DeployFormPage.tsx (+ test)
├── pages/drivers/driver-detail/tabs/ComponentsTab.tsx (+ test)
└── lib/{deployment-input,config-diff}.ts (+ tests)

driver/examples/{infrahub,infrahub-enterprise,simple-app}/       # new versions (D-013)
driver/DRIVERS.md
docs/docs/concepts-and-architecture/{replica-overrides.md (new), glossary.md}
docs/docs/drivers/{creating-a-driver.md, migrating-replica-parameters.md (new)}
docs/docs/reference/styrminctl.md, docs/sidebars.ts
dev/adr/0070-replica-overrides-and-retired-parameters.md (new)
dev/knowledge/backend/{api,services,data-models}.md, dev/knowledge/frontend/deployment-configuration.md
CONTEXT.md (drafted), changelog/202.added.md, changelog/202.changed.md
```

**Structure Decision**: Existing web-service layout. A new `services/replicas/` package holds the resolver, patch builder, validator and errors, next to `services/image_overrides/` and `services/component_container/`. The stop patch moves out of `builders/application.py` into that package, because the replica patch replaces it.

## Implementation Order

User Story 1 is the first deliverable; the others build on its resolver and patch builder.

1. **Foundation**: `ComponentConfigBlock.replicas` and its validator; `ArbitrarySectionModel.replicas`/`singleton` with the load check; `ComponentContext.replica_override` and its resolver wiring; `services/replicas/` resolver and errors. Unit tests first.
2. **User Story 1 (P1)**: patch builder replacing the stop patch, unit and kustomize tests; write checks on create, update and version change; `ComponentConfigInput.replicas` and `Deployment.componentReplicas` with propagation tests; `simple-app` version 4; the E2E protocol method, page object, helper and the new node in `test_deployment_image_override.py`; edit drawer and create form fields.
3. **User Story 2 (P2)**: `ComponentConfig.replicas`/`singleton` read fields and propagation test; driver version page rows; driver format docs.
4. **User Story 3 (P3)**: clearing (already covered by the input semantics) with tests; configuration view line; `styrminctl deployments get` column; SDK `_inapplicable_overrides`.
5. **User Story 4 (P2)**: `drop_retired_parameters` and `RETIRED_PARAMETER_VALUE`; `infrahub` 5 and `infrahub-enterprise` 4; legacy fixture and the upgrade functional test; migration guide.
6. **Documentation and changelog**: concept page, glossary, `styrminctl` reference, ADR-070, `dev/knowledge`, changelog fragments; CONTEXT.md check.
7. **Verification**: regenerate schema and SDK; `format lint`; unit, functional and integration suites; frontend tests and lint; E2E in both variants with recorded PASS evidence, plus the rest of `shard_configuration` once per variant.

## Risks

| Risk | Mitigation |
|------|------------|
| A third-party driver version already declares an undocumented `components.<name>.replicas` key, which starts to apply after the upgrade (D-002) | Changelog `changed` fragment and the driver format docs state it; driver authors can remove the key |
| The new typed fields add `replicas: null, singleton: false` to every serialised declaration, so the first update after a Styrmin upgrade would start a HelmRelease upgrade that changes nothing (critique E1) | The model serialises the two keys only when set; a unit test compares the dump with the dump before the change (D-002) |
| A driver version stored before the change holds an untyped `replicas` or `singleton` value that the typed model rejects, which would fail the render | `parse_stored_component_declaration` drops the two keys with a warning when they are invalid (D-002); a unit test covers it |
| An older operator reads a context with the new `ComponentContext.replica_override` field (`extra="forbid"`) | Same upgrade order as image overrides (018): the agent chart and server are released together; the changelog notes it |
| helm-controller's wait does not treat a scale-down as in progress | The E2E asserts `status.replicas` returns to 1 after the task completes (D-008) |
| Changing the `simple-app` driver affects every E2E that deploys it | The chart already renders 1 PostgreSQL replica, so the patch changes no count; the whole `shard_configuration` runs once per variant at verification |
| Users of the infrahub drivers who changed a replica parameter are blocked on upgrade | Intended (user need 14); the error message and the migration guide give both ways to resolve it |

## Complexity Tracking

No constitution violation to justify.
