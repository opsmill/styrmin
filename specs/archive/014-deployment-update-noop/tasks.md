# Tasks: Backend No-Op Detection for Deployment Updates

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Branch**: `009-deployments-apply`

Conventions: `[P]` = parallelizable (different files, no ordering dep). Test-first per Constitution §V — write the failing test, then the change. Each task names its file(s).

## Phase A — Service layer (core no-op guard)

- [X] **T001** — Service test (red): `backend/tests/unit/services/test_deployment*.py` (new or extend). Assert `update_deployment` returns `None` and does **not** call `apply_state`, does **not** persist a new `ApplicationInstance`, and leaves `status` + active-instance pointer untouched when the submitted state resolves to the current instance; and returns a `Task` + calls `apply_state` once when it differs. Use the existing fakes/spies (`backend/tests/unit/services/fakes.py`).
- [X] **T002** — In `backend/styrmin_backend/services/deployment.py::update_deployment` (phase 2), after `new_instance = await generate_instance_from_deployment(...)` and **before** `set_active_instance` / `set_status` / `apply_state`, run `Comparator(current_instance=current_instance, new_instance=new_instance).compare()`; if `report.diff is None` log + `return None` (no persistence, no dispatch). Change the return type to `Task | None`. (Depends: T001.)
- [X] **T003** — In the same function, remove the `InvalidContextError("At least one of config, parameters, name, or serviceNameOverrides must be provided")` guard (FR-003). Keep all *malformed-input* validation (env-var name, duplicate component/parameter, scheduling) which runs before generation. (Depends: T002.)
- [X] **T004** — Service test (red) for the version path: assert `update_deployment_version` returns `None` / no `apply_state` / no instance when the requested version equals current, and a `Task` when it differs.
- [X] **T005** — Apply the identical `Comparator` no-op guard to `backend/styrmin_backend/services/deployment.py::update_deployment_version`; return type `Task | None`. (Depends: T004.)

## Phase B — GraphQL resolvers (M1)

- [X] **T006** — Functional/propagation tests (red): `backend/tests/functional/graphql/test_deployment.py` per `contracts/graphql.md` — (1) `updateDeployment` no-op → `null`, DB instance count + active pointer + status unchanged; (2) real change → non-null task + 1 new instance; (3) empty/no-op input → `null` (no `INVALID_CONTEXT`); (4) `updateDeploymentVersion` same version → `null`; (5) new version → non-null task. Update/replace the existing error-path test for the removed guard. [P with T007 once resolvers compile]
- [X] **T007** — Make both resolvers None-safe: `backend/styrmin_backend/api/schema/mutation.py` `updateDeployment` (~L805) and `updateDeploymentVersion` (~L1115) → `return Task.from_instance(task) if task is not None else None`. (Depends: T002, T005.)

## Phase C — SDK (thin the client — revert stopgap 6f8713a)

- [X] **T008** — SDK test (red): `python_sdk/tests/test_deployments.py` — `update()` / `update_version()` map a `null` `data.updateDeployment*` payload to `None` (not a parse error); `_apply_update` always invokes `update` *and* `update_version` (no client-side skip / version compare); maps null+null → `ApplicationOutcome(action="unchanged", task_id=None)`, any task → `updated`; a FAILED-deployment no-op stays `unchanged`.
- [X] **T009** — `python_sdk/src/styrmin_sdk/resources/deployments.py`: (a) `update`/`update_version` return `... | None` and tolerate a null payload; (b) rewrite `_apply_update` to drop the `6f8713a` empty-input skip and the `existing.application_version != manifest.version` comparison — always call `update(input=_build_update_input(manifest))` and `update_version(version=manifest.version)`; (c) map null/null → `unchanged`, else `updated` (keep `created` on the create branch). Keep the `unchanged` action value (now backend-driven). (Depends: T007, T008.)

## Phase D — CLI

- [X] **T010** — Confirm CLI rendering: `cli/src/styrminctl/commands/deployments.py` `_summary_line` ("…unchanged…"), `_format_outcome_line` / `_format_wait_event_line` (`unchanged <name>`, no terminal event on `--wait`) — already added by the stopgap; keep and verify against `cli/tests/test_deployments.py`. Adjust tests only if the action-mapping change in T009 shifts any outcome. [P]

## Phase E — E2E (definition of done, Constitution §V)

- [X] **T011** — `backend/tests/e2e/test_deployments_apply.py::test_apply_unchanged_manifest_is_noop` (new): apply a manifest, wait for RUNNING, snapshot the deployment's instance count + task count, re-apply the identical manifest, assert the second outcome is `unchanged`, instance count and task count are unchanged, and the active-instance pointer + status are unchanged. Markers: `pytestmark = [pytest.mark.ci, pytest.mark.shard_general]`, `@pytest.mark.api_only`. (Depends: T009.)
- [X] **T012** — Extend the existing apply E2E (or add focused assertions) for the partial-change cases: config-only change → exactly 1 new instance/reconcile; version-only change → exactly 1 upgrade. (Depends: T009.) [P with T011]

## Phase F — Docs + validation

- [X] **T013** — Docs: update any `docs/` page describing `deployments apply` output to mention the `unchanged` outcome + the no-op behaviour and the rebuilt-image limitation; refresh `dev/knowledge/backend/` reconciliation/deployment notes if they assert "every update creates an instance." (Constitution §VII.) [P]
- [X] **T014** — `uv run invoke format lint` clean; run `python_sdk/tests/test_deployments.py`, `cli/tests/test_deployments.py`, `backend/tests/unit`, `backend/tests/functional/graphql/test_deployment.py` green. (Depends: A–D.)
- [ ] **T015** — Run **T011/T012 to a local PASS** with recorded §V evidence (node id, exact command, ISO timestamp, vcluster id + kubeconfig path, verbatim `PASSED` line). (Depends: T011, T012, T014.)

## Notes
- No DB/schema/migration, no GraphQL schema change, no new dependency, no CI/auth change — service-layer behaviour only. No `schema.graphql` regen, no SDK codegen.
- The committed stopgap `6f8713a` is partially reverted by T009 (client skip + version compare removed; `unchanged` action retained, now backend-driven).
- Dependency order: A (T001→T002→T003, T004→T005) → B (T006/T007) → C (T008→T009) → D (T010) → E (T011/T012) → F (T013/T014/T015).
