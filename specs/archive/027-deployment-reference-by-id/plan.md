# Implementation Plan: Deployment References Stored by Id

**Branch**: `fac/affinity-by-id-zsdtf` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/027-deployment-reference-by-id/spec.md` (PRD: [#508 comment](https://github.com/opsmill/styrmin/issues/508#issuecomment-6226052128))

## Summary

An affinity term that names a deployment by name stops working when that deployment is renamed (#492). After this change, Styrmin replaces the name with the deployment's id when a config is written, refuses a write that names a deployment the environment does not have, and resolves only ids at reconcile. An environment clone gives each counterpart its id before it creates anything, rewrites the copied terms to name the counterparts, and refuses a request that leaves out a deployment that a term names.

Technical approach (details in [research.md](research.md)):

- New module `services/scheduling/references.py`: find the deployment references in a stored config dict, bind them (name to id, with checks) against an environment, and rewrite ids with a mapping (R-001, R-002).
- Call the binding in `deploy_application`, `update_deployment`, `update_deployment_version`, `create_environment` and `update_environment`, at the points listed in R-001, including the component configs copied from the driver version (R-005).
- The reconcile-time resolver reads ids only, refuses a tombstoned deployment with its last name, and expands each level's terms before the merge so that the error path names the level (R-004).
- `clone_environment` checks the terms of the merged environment config, the copied deployments and their components before it creates anything (R-007).
- The clone flow cascades capture failures, gives counterparts their ids in advance, rewrites the configs, creates the environment and the counterparts with those ids, and orders the counterparts so that the named ones come first (R-008).
- The environment restore's redeploy loop isolates each redeploy in a savepoint (R-009).
- GraphQL descriptions only; regenerate `schema.graphql`, SDK and frontend types (R-011).
- Unit, functional and propagation tests; two existing E2E tests extended (R-013).
- Documentation, ADR-075 and two changelog fragments (R-014).

## Technical Context

**Language/Version**: Python 3.14+ (backend, workflows, SDK); GraphQL schema text.

**Primary Dependencies**: Strawberry GraphQL, SQLModel and SQLAlchemy (async), Pydantic v2, Prefect. No new dependency, no version change (R-012).

**Storage**: PostgreSQL. No column change and no data migration: configs stay JSON columns (`environment.config`, `deployment.config`, `component.config`), only the shape of a stored `deployment_ref` changes (spec Assumptions).

**Testing**: pytest unit tests (`backend/tests/unit/services/`), functional tests with real services and SQLite or PostgreSQL fixtures (`backend/tests/functional/`), GraphQL propagation tests (`backend/tests/functional/graphql/`), E2E on vCluster (`shard_compute` api cell, `shard_env_backup` both cells).

**Target Platform**: Styrmin server and task worker on Kubernetes.

**Project Type**: Web service (backend with GraphQL API, Prefect workflows) with SDK, CLI and frontend clients.

**Performance Goals**: no new goal. A write that has terms makes one lookup per term. Reconcile-time expansion of the environment and deployment levels runs once per instance instead of once per component.

**Constraints**:

- ADR-054 no-op detection must keep returning a null `Task` for a write-back and for a re-apply with names (R-003).
- Constitution §III: binding lives in the service layer and calls the repository through the unit of work.
- A failed counterpart creation still leaves no row (R-008).
- ADR-066 savepoint rules apply to the restore loop change (R-009).

**Scale/Scope**: 1 new service module, 8 changed service or workflow modules, 2 changed exception classes (1 new), 1 GraphQL input with new descriptions, about 9 new or extended test files, 2 extended E2E tests, 8 documentation files, 1 ADR, 2 changelog fragments.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
| --- | --- | --- |
| I. Declarative state reconciliation | Pass | A term still resolves to `styrmin/deployment_id=<id>` at each reconcile. A rename no longer changes any stored term, so reconciliation of the other deployments is unchanged by it (FR-010). Write-backs stay idempotent (R-003). |
| II. Driver-based deployment | Pass | Driver component terms are bound when copied from the driver version (R-005); the driver format does not change. |
| III. Layered architecture | Pass | Binding and remapping are service-layer functions; the clone flow calls services; repositories are reached through the unit of work. |
| IV. Type safety and typed errors | Pass | One new typed error, `UnclonedDeploymentReferenceError`, and one new field on `UnresolvableAffinityReferenceError` (R-010). |
| V. Test-first development | Pass | Two existing E2E tests are extended (reuse before boot); both use fixtures with active consumers in their shards. Propagation tests cover the changed input descriptions and the stored id. Local PASS evidence is recorded for both E2E tests. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit. |
| VII. Documentation accuracy | Pass | Guide, `CONTEXT.md`, ADR-075, two knowledge pages, one public page section and changelog fragments ship in the same change (R-014). |
| Governance gates | Pass, one gate crossed | GraphQL schema: descriptions of `DeploymentReferenceInput` only, decided in the PRD (#508). No database, dependency, CI or authorization change. |

Post-design re-check (after Phase 1): unchanged. The `upcoming_deployments` argument added to the instance-generation chain follows the same path as `release_reference` (R-008) and adds no new layer.

## Design Decisions

### D-001: `services/scheduling/references.py`

Pure helpers and one async binder, all on raw config dicts (R-002):

- `ReferenceSite` (dataclass): `path: str` and the `deployment_ref` dict it points to.
- `iter_reference_sites(config: Mapping | None, path_prefix: str) -> Iterator[ReferenceSite]`: yields every `deployment_ref` under `scheduling.pod_affinity` and `scheduling.pod_anti_affinity` (`required[i]` and `preferred[i].term`), with paths such as `deployment.config.scheduling.pod_affinity.required[0]`.
- `referenced_deployment_ids(config, path_prefix) -> dict[UUID, list[str]]`: id to paths, for configs that are already bound.
- `remap_deployment_references(config, mapping: Mapping[UUID, UUID]) -> tuple[dict | None, dict[UUID, list[str]]]`: returns a deep copy with every id rewritten and the ids that had no entry, with their paths. Never mutates its input.
- `async bind_deployment_references(uow, environment_id: UUID | None, config: dict | None, *, path_prefix: str, upcoming_deployments: Mapping[UUID, str] | None = None) -> dict | None`: returns a deep copy in which each reference gives `deployment_id` only (canonical lowercase string) and keeps `components`. Rules from R-001 for upcoming deployments. For a name: `uow.deployments.get_by_name(name, environment_id)`, which excludes tombstoned rows. For an id: `uow.deployments.find(id)`, refused when missing, in another environment, or tombstoned (with `deleted=True` and the last name). `environment_id=None` means the environment does not exist yet, so only upcoming deployments match. Raises `UnresolvableAffinityReferenceError` with the full path on the first term that fails. A config without references is returned unchanged (same object is acceptable).

Unit tests: `backend/tests/unit/services/scheduling/test_references.py`, including that a bound config is unchanged by the `EnvironmentConfig.model_validate(...).model_dump(exclude_none=True, mode="json")` round trip that the clone merge and the environment no-op check use (critique E8).

### D-002: Deployment writes call the binding

In `services/deployment.py`:

- `deploy_application` gains `deployment_id: UUID | None = None` and `upcoming_deployments: Mapping[UUID, str] | None = None`. It computes `new_id = deployment_id or uuid4()` and passes `id=new_id` to `Deployment.create` (new optional `id` argument in `domain/models.py`). After the name is resolved, it binds `deployment_config` with path prefix `deployment.config` and `{**(upcoming_deployments or {}), new_id: resolved_name}`, and each copied component config with `component[<name>].config`. It passes `upcoming_deployments` to `generate_instance_from_deployment`.
- `update_deployment`: after the config and the new name are set (L609-613) and before the save at L655, bind `deployment.config` with `{deployment.id: deployment.name}`.
- `update_deployment_version`: after the name is validated (L970-974), bind `effective_config` and each re-copied component config with `{deployment.id: new_name}`, before `deployment.config = effective_config` (L1066) and the no-op comparison (L1106-1110).

Tests: unit `backend/tests/unit/services/test_deployment_reference_binding.py` (the three paths: name stored as id, self-reference, rename with a term that names the new name and the old name, refused write saves nothing, component configs bound); propagation rows in `test_deploy_input_propagation.py`, `test_update_deployment_input_propagation.py` and `test_update_deployment_version_input_propagation.py` (`deploymentRef.deploymentName` in, `deployment_id` in the database); no-op rows in `test_deployment_noop_propagation.py` (write-back of a read config, re-apply with names).

### D-003: Environment writes call the binding

In `services/environments.py`:

- `create_environment` gains `upcoming_deployments: Mapping[UUID, str] | None = None` and binds `config` with path prefix `environment.config` and `environment_id=None`, so any term is refused unless it names an upcoming deployment.
- `update_environment` binds `config` against `environment_id` after the shape check (L348-352) and before `environment.config = config` (L357).

Tests: rows in `test_environment_update_propagation.py` (name in, id stored; missing name refused and config unchanged; no-op of a re-sent config with a name), and a `createEnvironment` refusal test in the same file or `test_api_scheduling_config.py`.

### D-004: The reconcile-time resolver

In `services/scheduling/validator.py`:

- `resolve_deployment_reference(uow, environment_id, ref, path, upcoming_deployments=None)`: ids only; a name is refused; an upcoming id is accepted without a lookup; a tombstoned row is refused with `deleted=True` and its name.
- `expand_deployment_references(uow, environment_id, config, *, path_prefix="scheduling", upcoming_deployments=None)`: the prefix is used in paths.

In `services/context.py` `_populate_component_scheduling` and `api/definitions/deployment/model.py` `resolvedScheduling`: expand the environment and the deployment level once each, with prefixes `environment.config.scheduling` and `deployment.config.scheduling`, and each component level with `component[<name>].config.scheduling`, before `_resolve_scheduling_config`. `generate_instance_from_deployment` and `generate_context_from_deployment` take `upcoming_deployments` and pass it down.

Tests: extend `backend/tests/unit/services/test_scheduling_validator.py` (tombstoned id refused with last name and `deleted`, name refused, upcoming id accepted, per-level path); the existing `test_resolves_by_name` changes to expect a refusal. Existing tests that write the name of a deployment that does not exist are updated to create it first or to expect the refusal: `backend/tests/functional/test_api_scheduling_config.py::test_accepts_anti_affinity_with_deployment_ref` (L49-63) and any other found by `grep -rn deployment_name backend/tests` in scheduling tests (critique E7).

### D-005: Error types

In `services/exceptions.py` (R-010): `UnresolvableAffinityReferenceError(..., deleted: bool = False)` and the new `UnclonedDeploymentReferenceError(deployments: list[UnclonedReference])`, where `UnclonedReference` holds `deployment_id: UUID`, `deployment_name: str | None` and `paths: list[str]`. Export both from `context/exceptions.py` where the existing one is re-exported. Unit tests for messages and `error_metadata`.

### D-006: Clone request check

In `services/backup/clone.py` `clone_environment`, before the clone row is created (L1336):

1. Bind `canonical_override` with path prefix `config_override` against the source environment; store the bound override.
2. `merged = merge_environment_config(source.config, bound_override, cleared_config_fields)`.
3. `copied = {result.deployment_id for result in planned if result.outcome is PENDING}`.
4. Collect `referenced_deployment_ids` of `merged` (prefix `environment.config`) and of each copied deployment's config (prefix `deployment[<name>].config`). For components, read the component definitions of each copied deployment's driver version and check each reference by name against the names of the copied deployments and by id against their ids (prefix `deployment[<name>].component[<component>].config`), because the flow binds those definitions by name in the new environment (critique X1).
5. When any collected id is not in `copied`, raise `UnclonedDeploymentReferenceError`, with names from the roster (`find_all_by_environment(..., include_deleted=True)`, already loaded at L1324-1326).

New helper `find_uncloned_references(...)` without side effects, so the check is unit-tested without the service. Tests: extend `backend/tests/unit/services/backup/test_environment_clone_service.py` (named deployment not selected, selected but not eligible, named by the environment config, by the override, by a driver component definition, including a driver name that no copied deployment has after a rename; cleared or replaced `scheduling` accepted; no record created on refusal) and `test_environment_clone.py` (GraphQL error code and metadata).

### D-007: Clone flow

In `workflows/templates/clone.py` (R-008):

- New pure helpers in `services/backup/clone.py`:
  - `cascade_reference_failures(snapshots, failed_ids) -> dict[UUID, UUID]`: each snapshot that fails, with the named deployment that makes it fail, repeated until nothing changes;
  - `order_counterparts(snapshots, environment_config) -> list[snapshot]`: each counterpart after the ones its terms name; among those that can come next, the ones named by the environment config first, then source-name order; a cycle is broken in source-name order (critique E1).
- `_run_environment_clone`: after `_classify_captured_constituents`, cascade the capture failures and attribute them with `CLONE_REASON_REFERENCED_DEPLOYMENT_NOT_CLONED.format(name=...)`; when the merged environment config names a failed deployment, write a fatal `CloneError(step=CLONE_STEP_REFERENCED_DEPLOYMENT_NOT_CLONED, ...)`, fail the pending entries and stop. Then build `counterpart_ids = {snapshot.deployment_id: uuid4()}` and `upcoming = {counterpart_ids[s.deployment_id]: s.deployment_name}`.
- `_create_cloned_environment`: merge, then `remap_deployment_references(merged, counterpart_ids)`, then `create_environment(..., config=remapped, upcoming_deployments=upcoming)`.
- `_create_counterpart`: `remap_deployment_references(snapshot.config, counterpart_ids)`, then `deploy_application(..., deployment_id=counterpart_ids[...], deployment_config=remapped, upcoming_deployments=upcoming)`; return the given id instead of reading back by name.
- The counterpart loop runs in `order_counterparts` order; `upcoming` holds only the counterparts that have not failed (critique E2); before each, a counterpart whose config names a failed counterpart is attributed failed without being created and `env_clone_reference_not_cloned` is logged (critique E4); a failure of a counterpart named by the environment config writes the fatal error and fails the remaining pending entries.
- Add `CLONE_STEP_REFERENCED_DEPLOYMENT_NOT_CLONED = "referenced_deployment_not_cloned"` to `CLONE_STEPS`.

Tests: unit tests for the two helpers and for the flow harness (`test_environment_clone_service.py`: capture failure cascade, fatal environment-config case, order); functional tests with the real flow (`test_environment_clone.py` via `_run_clone_flow`): A names B in both snapshot orders, A and B name each other, the environment config names A, and no term in the new environment gives a source id.

### D-008: Environment restore isolates each redeploy

In `services/backup/environment.py` L1071-1089, wrap `redeploy_for_environment_update` in `async with uow.session.begin_nested():` inside the existing `try`. Test: `backend/tests/unit/services/backup/` restore test where one deployment's redeploy raises `UnresolvableAffinityReferenceError` and another's redeploy is still committed; and a functional test for FR-006 (back up, delete A, restore, then B's update refused with A's last name).

### D-009: GraphQL descriptions and generated types

Descriptions on `DeploymentReferenceInput` and its fields (R-011). Regenerate with `uv run styrmin export graphql-schema schema.graphql` and `uv run invoke generate` (with `npm_config_ignore_workspace=true` in this worktree). Propagation test rows of D-002 and D-003 cover the input.

### D-010: E2E extensions

As R-013:

- `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql`, run with `-k api-chromium` (it is `api_only`).
- `backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle`, run once with `-k api-chromium` and once with `-k ui-chromium`, each in its own pytest session and in its shard only.

### D-011: Documentation

As R-014, plus the ADR file `dev/adr/0075-deployment-references-stored-by-id.md` with Status Accepted, Related ADR-034, ADR-054, ADR-056 and ADR-073.

## Project Structure

### Documentation (this feature)

```text
specs/027-deployment-reference-by-id/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── stored-config.md # Stored shape of a deployment reference
│   └── graphql-and-errors.md # GraphQL descriptions and error extensions
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── services/
│   ├── scheduling/
│   │   ├── references.py        # new: sites, bind, remap (D-001)
│   │   └── validator.py         # resolver: ids only, tombstone, upcoming (D-004)
│   ├── deployment.py            # deploy / update / update_version bind (D-002)
│   ├── environments.py          # create / update bind (D-003)
│   ├── context.py               # per-level expansion, upcoming (D-004)
│   ├── reconciliation/__init__.py # pass upcoming (D-004)
│   ├── exceptions.py            # error types (D-005)
│   └── backup/
│       ├── clone.py             # request check, cascade, order (D-006, D-007)
│       └── environment.py       # restore savepoint (D-008)
├── workflows/templates/clone.py # ids in advance, remap, order (D-007)
├── domain/models.py             # Deployment.create(id=...) (D-002)
├── context/exceptions.py        # re-export (D-005)
└── api/definitions/
    ├── config/inputs.py         # descriptions (D-009)
    └── deployment/model.py      # resolvedScheduling per level (D-004)

backend/tests/
├── unit/services/scheduling/test_references.py           # new
├── unit/services/test_deployment_reference_binding.py    # new
├── unit/services/test_scheduling_validator.py            # extended
├── unit/services/backup/test_environment_clone_service.py # extended
├── unit/services/backup/test_restore.py (or env restore test) # extended
├── functional/graphql/test_*_propagation.py              # rows added
├── functional/graphql/test_environment_clone.py          # extended
└── e2e/test_pod_scheduling.py, e2e/test_backup_restore.py # extended

schema.graphql, python_sdk/src/styrmin_sdk/graphql/_generated/, frontend/src/generated/  # regenerated
dev/guides/pod-scheduling.md, dev/adr/0075-…, dev/knowledge/backend/{backup-restore,data-models,services}.md,
CONTEXT.md, docs/docs/concepts-and-architecture/backups-and-restores.md, changelog/492.fixed.md, changelog/508.changed.md
```

**Structure Decision**: backend-only change in the existing web-service layout; the SDK and frontend change only through regenerated types.

## Complexity Tracking

No constitution violation.
