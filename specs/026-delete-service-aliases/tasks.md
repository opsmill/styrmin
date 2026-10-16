---

description: "Tasks for 026: deleting a deployment deletes its service aliases"
---

# Tasks: Deleting a Deployment Deletes Its Service Aliases

**Input**: Design documents from `specs/026-delete-service-aliases/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/internal-interfaces.md](contracts/internal-interfaces.md), [quickstart.md](quickstart.md)

**Tests**: Required. FR-014 and FR-015 list the unit tests and the E2E test, and Constitution §V requires local PASS evidence for the new E2E test.

**Organization**: One phase per user story. Phase 2 holds the Kubernetes primitives that User Stories 1 and 2 both use. User Story 3 adds the tests of the best-effort and guard rules that User Story 1 implements.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US3 (spec user stories)
- Paths are relative to the repository root

## E2E run rules (apply to every E2E task)

- Build the server image once before the first session: `docker compose build server`. The fixture's parallel builds race on one tag.
- One CI shard per pytest session, and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |` and stop the run by PID, never with `pkill -f`.
- Record each passing run in `specs/026-delete-service-aliases/e2e-evidence.md`: the pytest node IDs, the exact command, ISO 8601 start and end times, the vcluster name and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, and the verbatim `PASSED` lines (Constitution §V).

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/agent/test_service_aliases.py backend/tests/unit/agent/test_delete_service.py backend/tests/unit/test_deployment_deletion_operator.py backend/tests/unit/agent/test_kopf_deletion_cycle.py backend/tests/unit/test_restore_recovery_cross_target.py -q`, and note the result as the baseline (no file change)

---

## Phase 2: Foundational (blocks US1 and US2)

**Purpose**: the Kubernetes calls that the teardown and the alias flow need ([contract](contracts/internal-interfaces.md#kubernetes-primitives-agentservicekubernetesprimitivespy)).

- [X] T002 In `backend/styrmin_backend/agent/service/kubernetes/primitives.py` add `get_namespace(name: str, client: ApiClient = Depends(get_api_client)) -> V1Namespace | None`, decorated with `@inject` like `list_services_in_all_namespaces`: it calls `CoreV1Api(client).read_namespace(name=name)`, returns `None` on a 404 `ApiException` and re-raises any other error
- [X] T003 In the same file add `apply_service(resource: dict, namespace: str, client: ApiClient = Depends(get_api_client)) -> V1Service` (`@inject`): `create_namespaced_service`; on a 409 `ApiException`, `replace_namespaced_service(name=resource["metadata"]["name"], ...)`; return the API result; re-raise every other error. Then make the `kind == "Service"` branch of `apply_kubernetes_resource` call `await apply_service(resource=resource, namespace=namespace, client=client)` instead of its own create-then-replace, so Services have one implementation
- [X] T004 In the same file add `is_namespace_gone_error(exc: ApiException) -> bool`: `True` when `exc.status == 404`, or when `exc.status == 403` and either the JSON in `exc.body` has a `details.causes[*].type` equal to `"NamespaceTerminating"` or `exc.body` contains `"because it is being terminated"`. Parse the body with `json.loads` inside `try`; a body that is not JSON falls back to the text check. `False` otherwise (research R-005, critique E6)
- [X] T005 [P] Create `backend/tests/unit/agent/test_apply_service.py`, in the style of `backend/tests/unit/agent/test_delete_service.py` (call `apply_service.__wrapped__` with `client=None` and patch `kubeclient.CoreV1Api`): (a) a create that succeeds returns the created object; (b) a create that raises 409 calls `replace_namespaced_service` with the given `ClusterIP` manifest and returns its result. Name this test after the case it covers: a `ClusterIP` Service replaces an `ExternalName` alias with the same name that a failed teardown left (spec Clarifications, research R-007); (c) a create that raises 500 re-raises and does not call replace; (d) `apply_kubernetes_resource.__wrapped__` with a `Service` manifest calls `apply_service` (patch it in the module)
- [X] T006 [P] Create `backend/tests/unit/agent/test_namespace_primitives.py`: `get_namespace` returns the object, returns `None` on 404, re-raises 500 (same `__wrapped__` pattern); `is_namespace_gone_error` is `True` for 404, for a 403 whose body is `{"details": {"causes": [{"type": "NamespaceTerminating"}]}}`, and for a 403 whose non-JSON body contains "because it is being terminated"; `False` for an RBAC 403 body (`"services is forbidden: User ... cannot create resource"`), for 409 and for 500
- [X] T007 Run `uv run pytest backend/tests/unit/agent/test_apply_service.py backend/tests/unit/agent/test_namespace_primitives.py backend/tests/unit/agent/test_delete_service.py -q`; fix failures; then `uv run invoke format lint`

**Checkpoint**: the three primitives exist and are tested; Services written by the operator go through `apply_service`.

---

## Phase 3: User Story 1 - The teardown deletes the deployment's aliases in all namespaces (Priority: P1) 🎯 MVP

**Goal**: when a deployment reaches `DELETED`, no namespace holds an alias of its services (FR-001 to FR-006, FR-017).

**Independent Test**: `test_deleted_deployment_leaves_no_alias` (T014) passes; the unit tests of T010 and T011 pass.

### Implementation for User Story 1

- [X] T008 [US1] In `backend/styrmin_backend/operator/handlers/styrmin_deployment.py` add `async def _delete_service_aliases(*, deployment_id: str, namespace: str, deletion_requested: bool, logger: Any) -> None` next to `_teardown_owned_resources`, as the [contract](contracts/internal-interfaces.md#_delete_service_aliases-deployment_id-str-namespace-str-deletion_requested-bool-logger---none-new) says. Import inside the function, as the teardown already does: `get_kubernetes_reference` from `styrmin_backend.agent.service.kubernetes.utils`; `get_namespace`, `list_services_in_all_namespaces` and `delete_service` from `styrmin_backend.agent.service.kubernetes.primitives`; `SERVICE_ALIAS_LABEL` and `is_alias_of_deployment` from `styrmin_backend.agent.tasks.service_aliases`. Steps:
  1. Parse `deployment_id` with `UUID(...)`; on `ValueError`, or when `namespace != get_kubernetes_reference(UUID(deployment_id))`, call `logger.warning` naming the namespace and the id, and return (research R-001).
  2. When `deletion_requested` is false: `get_namespace(name=namespace)` inside `try`. On an exception, `logger.exception` and return. When it returns `None`, or its `status.phase == "Terminating"`, `logger.info("Namespace %s is being deleted without a deletion request; keeping its service aliases", namespace)` and return (research R-011).
  3. `list_services_in_all_namespaces(label_selector=f"{SERVICE_ALIAS_LABEL}=true")` inside `try`; on an exception, `logger.exception` and return.
  4. For each item with `is_alias_of_deployment(item, deployment_id, namespace)`: `await delete_service(name=item.metadata.name, namespace=item.metadata.namespace)` inside `try`; count a `True` or `False` result as deleted; on an exception, `logger.exception("Failed to delete service alias %s/%s", ...)` and continue.
  5. `logger.info("Deleted %d service aliases of %s", count, deployment_id)`. The function never raises.
- [X] T009 [US1] In the same file change `_teardown_owned_resources` to take the keyword arguments `deployment_id: str` and `deletion_requested: bool`; add a first step, logged as `"Teardown step 1: service aliases of %s in all namespaces"`, that awaits `_delete_service_aliases(...)`; renumber the existing log lines to steps 2, 3 and 4; update the docstring's order line to "Service aliases in all namespaces -> Services/Middlewares -> HelmRelease -> NetworkPolicies/Secrets". In `kopf_on_styrmin_deployment_deletion_requested` and in `kopf_on_styrmin_deployment_delete` (after its skip-teardown branch, which stays first) pass `deployment_id=spec.get("deploymentId", "")` and `deletion_requested=bool(spec.get("deletionRequested", False))`
- [X] T010 [US1] In `backend/tests/unit/test_deployment_deletion_operator.py` add tests that call `_delete_service_aliases` directly, with `list_services_in_all_namespaces`, `delete_service` and `get_namespace` patched where the function imports them (`styrmin_backend.agent.service.kubernetes.primitives`) and `V1Service` items built as `_live_alias` does in `backend/tests/unit/agent/test_service_aliases.py`; use a real UUID for the deployment and `namespace=get_kubernetes_reference(id)`:
  - with `deletion_requested=True`: an alias labelled with the id in a peer namespace and an alias without the label whose `externalName` points into the namespace are deleted; an alias labelled with another deployment's id, an unlabelled alias that points into another namespace, and an alias of a deployment of another environment are not;
  - `get_namespace` is not called when `deletion_requested` is true;
  - the list call uses `label_selector="styrmin.io/service-alias=true"`.
- [X] T011 [US1] In the same file add teardown-level tests: `_teardown_owned_resources` (with `list_managed_resources`, `delete_kubernetes_resource` and `get_kubernetes_client` patched as the module's other tests patch the handler helpers) awaits `_delete_service_aliases` before it lists the deployment's own Services; `kopf_on_styrmin_deployment_deletion_requested` with `spec={"releaseReference": "rel-1", "deletionRequested": True, "deploymentId": <id>}` calls `_teardown_owned_resources` with that `deployment_id` and `deletion_requested=True`, and calls it before `_request_namespace_deletion` (use a shared `mocker.Mock()` parent to check the order); `kopf_on_styrmin_deployment_delete` with `spec={"releaseReference": "rel-1", "deploymentId": <id>}` passes `deletion_requested=False`. Update the existing tests whose `spec` lacks `deploymentId` only if they now fail
- [X] T012 [US1] Run `grep -rn "_teardown_owned_resources" backend/tests` and update every test that calls it or asserts its arguments, including `backend/tests/unit/agent/test_kopf_deletion_cycle.py` and `backend/tests/unit/test_restore_recovery_cross_target.py`; then run `uv run pytest backend/tests/unit/test_deployment_deletion_operator.py backend/tests/unit/agent/test_kopf_deletion_cycle.py backend/tests/unit/test_restore_recovery_cross_target.py -q` and `uv run invoke format lint`

### E2E for User Story 1

- [X] T013 [US1] Before writing the test, check that deleting `intent` breaks no other test: `grep -rln "shard_general" backend/tests/e2e` and, in each module that the `api-chromium` session of `shard_general` runs after `test_service_discovery.py`, look for uses of `intent` or of a count of the scenario environment's deployments; record the result as a comment in the PR notes draft (`specs/026-delete-service-aliases/pr-notes.md`) (critique E5)
- [X] T014 [US1] At the end of `backend/tests/e2e/test_service_discovery.py` add `test_deleted_deployment_leaves_no_alias(styrmin_resources: dict, discovery_deployments: dict[str, str], vcluster: dict)`, with `client: StyrminClient = styrmin_resources["client"]` as in `backend/tests/e2e/test_delete_deployment_api.py`, marked `@pytest.mark.api_only(reason="Deletes through the SDK and checks Services with kr8s; the [ui-chromium] variant would re-run the same SDK call.")` and `@pytest.mark.ci` (the module's `pytestmark` already carries `shard_general`). Steps (research R-008):
  1. With `kr8s`, wait (reuse `_wait_for_alias_names`) until `executor`'s namespace holds the alias `intent` labelled with `intent`'s id, and assert it, so the test cannot pass when no alias was written.
  2. `await client.deployments.delete(intent_id)`.
  3. Poll `client.deployments.get(intent_id)` every 5 seconds, up to 300 seconds, until `status == "deleted"`, with a local helper `_wait_for_deleted`; fail with the last status on timeout.
  4. List the Services of `executor`'s namespace and assert that none has the label `styrmin.io/deployment-id=<intent id>` and none has a `spec.externalName` whose second dot-separated part is `styrmin-<intent id>`; the failure message names the remaining Services and #503.
  Extend the module docstring: deleting `intent` deletes its alias in `executor`'s namespace (#503), and this test runs last because the other tests use `intent`
- [X] T015 [US1] Run the new test with the rules above: `docker compose build server`, then `sleep infinity | uv run pytest backend/tests/e2e/test_service_discovery.py -k "api-chromium" -v -s --pdb 2>&1 | tee <scratch log>`. All three module tests must pass; on a failure, investigate while pytest is paused (`kubectl get svc -A -l styrmin.io/service-alias=true`, the agent log), fix, re-run. Record the evidence in `specs/026-delete-service-aliases/e2e-evidence.md`

**Checkpoint**: deleting a deployment deletes its aliases on both deletion paths, and the E2E test passes locally.

---

## Phase 4: User Story 2 - Flows of other deployments do not write the aliases again during a deletion (Priority: P1)

**Goal**: a flow writes no alias of a departing deployment, removes what it wrote just before it could read the request, never creates another deployment's namespace, and completes while a peer's namespace is being deleted (FR-007 to FR-010).

**Independent Test**: the unit tests of T021 to T023 pass.

### Implementation for User Story 2

- [X] T016 [US2] In `backend/styrmin_backend/agent/tasks/service_aliases.py` add the Pydantic model `WrittenAlias(namespace: str, name: str, owner_namespace: str, resource_version: str | None = None)` next to `StaleAlias` ([data model](data-model.md#writtenalias-pydantic-model-new-agent)), and `def owner_namespace(alias: dict) -> str`: `get_kubernetes_reference(UUID(alias["metadata"]["labels"][DEPLOYMENT_ID_LABEL]))` when the label is present, otherwise the second dot-separated part of `alias["spec"]["externalName"]`
- [X] T017 [US2] In the same file add `async def find_departing_namespaces(namespaces: Iterable[str]) -> set[str]`. For each distinct namespace, concurrently with `asyncio.gather` (critique E3), read the Namespace with `get_namespace` and the StyrminDeployment named after the namespace with `get_custom_resource(plural=CRD_PLURAL, name=ns, group=CRD_GROUP, version=CRD_VERSION, namespace=ns)` (constants from `styrmin_backend.operator.config`, as `orchestration.py` imports them; `CustomResourceNotFound` means absent). A namespace is departing when the Namespace is `None`, its `status.phase == "Terminating"`, or the CR exists with `spec.deletionRequested` true or `metadata.deletionTimestamp` set. A missing CR with an `Active` Namespace is not departing. Other errors propagate (research R-003, data model "Departing namespace")
- [X] T018 [US2] In the same file change the task `apply_single_alias` to return `WrittenAlias | None`: write with `apply_service(resource=resource, namespace=alias_namespace)`; on an `ApiException` for which `is_namespace_gone_error` is true, log with `get_run_logger().info("Skipping service alias %s/%s: the namespace is gone or being deleted", ...)` and return `None`; re-raise other errors; on success return `WrittenAlias(namespace=alias_namespace, name=alias_name, owner_namespace=owner_namespace(resource), resource_version=<result>.metadata.resource_version)`
- [X] T019 [US2] In the same file rewrite the flow `apply_service_aliases(aliases: list[dict], stale_aliases: list[StaleAlias] | None = None) -> None` as the [contract](contracts/internal-interfaces.md#apply_service_aliasesaliases-listdict-stale_aliases-liststalealias--none--none-none-changed-flow) says: remove the `namespace_labels` parameter, the `apply_namespace` loop and the `apply_namespace` import; compute the holder and owner namespaces of the aliases and the namespaces of the stale aliases; `departing = await find_departing_namespaces(...)`; log and drop each alias whose holder or owner namespace is departing and each stale alias whose namespace is departing; write the rest with `apply_single_alias`; delete the remaining stale aliases as today; then `departing_after = await find_departing_namespaces({w.owner_namespace for w in written})` and, for each written alias whose `owner_namespace` is in `departing_after` and whose `namespace` is not, `await delete_single_alias(alias_namespace=w.namespace, alias_name=w.name, resource_version=w.resource_version)` with a log line naming #503 (research R-004). Update the module docstring: aliases are never written for, or into the namespace of, a deployment whose deletion was requested, and the flow never creates a namespace
- [X] T020 [US2] In `backend/styrmin_backend/agent/tasks/orchestration.py` drop the `namespace_labels=` argument from the four `apply_service_aliases(...)` calls: `_apply_service_aliases_step` and the legacy `upgrade_instance`, `update_instance` and `create_instance`. Keep `_build_namespace_labels` where the other callers use it

### Tests for User Story 2

- [X] T021 [P] [US2] In `backend/tests/unit/agent/test_service_aliases.py` add `class TestFindDepartingNamespaces` with `get_namespace` and `get_custom_resource` patched in `styrmin_backend.agent.tasks.service_aliases`: one case per row of the state table in `data-model.md` (running; `deletionRequested`; `Terminating` with `deletionTimestamp`; both gone; `kubectl delete` with `deletionTimestamp` and an `Active` namespace; a new deployment with no CR and an `Active` namespace, not departing; no CR and no namespace, departing); a 500 from either read propagates
- [X] T022 [US2] In the same file add `class TestApplyServiceAliasesFlow`, calling `apply_service_aliases.fn(...)` with `find_departing_namespaces`, `apply_service`, `delete_service` and `get_run_logger` patched in the module, and contexts built with `_make_context` and `compute_service_aliases`:
  - no departing namespace: every alias of `compute_service_aliases` is written once, and no namespace is created (assert `apply_namespace`/`apply_kubernetes_namespace` are not referenced by the module any more, or patch them and assert no call) (FR-009);
  - a peer whose namespace is departing on the first read (the context was built before the request or while the peer is `DELETING`; both give the same input to the flow): no alias of the peer's services and no alias into the peer's namespace is written, and a stale alias in the peer's namespace is not deleted (FR-007, FR-008, SC-002);
  - the peer becomes departing only on the second read: the alias of the peer's service that the flow wrote into its own namespace is deleted with the `resource_version` returned by the write; the flow's own alias written into the peer's namespace is not deleted (spec User Story 2 scenario 3, research R-004);
  - `apply_service` raises a 403 with the `NamespaceTerminating` cause, and a 404: the flow completes and skips that alias (spec User Story 2 scenario 6);
  - `apply_service` raises an RBAC 403: the flow raises.
- [X] T023 [P] [US2] Create `backend/tests/unit/services/test_context_deleting_peer_services.py`, seeding fakes the way `backend/tests/unit/services/test_update_deployment_service_rename.py` does: two deployments of one environment with one `DeployedService` row each, the peer with `status = DeploymentState.DELETING`; `generate_context_from_deployment` for the other deployment lists the peer's service in `context.services` (by driver service name) and in `context.deployed_services` (by resolved name and deployment id) (FR-010, research R-006)
- [X] T024 [US2] Run `grep -rn "namespace_labels\|apply_service_aliases\|apply_single_alias" backend/tests` and update tests that pass `namespace_labels` to `apply_service_aliases` or mock `apply_single_alias`'s old return value (for example `backend/tests/unit/agent/tasks/test_remediation_flow_steps.py` and `backend/tests/unit/agent/test_styrmin_deployment_crd_write_order.py`); then run `uv run pytest backend/tests/unit/agent backend/tests/unit/services/test_context_deleting_peer_services.py -q` and `uv run invoke format lint`

**Checkpoint**: flows skip departing deployments, remove racing writes, create no namespace, and tolerate a terminating namespace.

---

## Phase 5: User Story 3 - A failed alias deletion does not block the deletion (Priority: P2)

**Goal**: alias deletion is best-effort, skip-teardown deletes nothing, and a restore's namespace deletion deletes nothing (FR-004, FR-006, FR-017, SC-003, SC-006).

**Independent Test**: the unit tests of T025 and T026 pass.

- [X] T025 [US3] In `backend/tests/unit/test_deployment_deletion_operator.py` add best-effort tests of `_delete_service_aliases` (same patching as T010): `delete_service` returning `False` for one alias still counts it and deletes the next; `delete_service` raising for one alias logs an exception naming that alias's namespace and name and still deletes the next; `list_services_in_all_namespaces` raising logs and returns without raising; and `_teardown_owned_resources` with `_delete_service_aliases` raising inside (patch the list call to raise) still runs its HelmRelease step, and the `deletionRequested` handler still calls `_request_namespace_deletion` (FR-004)
- [X] T026 [US3] In the same file add guard tests: (a) `kopf_on_styrmin_deployment_delete` with the skip-teardown annotation and patched primitives makes no `list_services_in_all_namespaces` call (FR-006); (b) `_delete_service_aliases` with `deletion_requested=False` and `get_namespace` returning a namespace with `status.phase == "Terminating"`, then `None`, deletes no alias and makes no list call (FR-017, SC-006); (c) with `deletion_requested=False` and `get_namespace` raising, it deletes no alias and logs; (d) with `deletion_requested=False` and an `Active` namespace it deletes the aliases (`kubectl delete styrmindeployment`, FR-005); (e) with `deletion_requested=True` and a `Terminating` namespace it deletes the aliases; (f) a namespace that is not `styrmin-<deployment_id>`, as on a restored copy of a source's CR, makes no API call (research R-001)
- [X] T027 [US3] Run `uv run pytest backend/tests/unit/test_deployment_deletion_operator.py -q` and `uv run invoke format lint`

**Checkpoint**: every rule of the teardown step has a unit test.

---

## Phase 6: Documentation and changelog (all stories)

**Purpose**: Constitution §VII; FR-012 and FR-013.

- [ ] T028 [P] In `CONTEXT.md` add the **Service alias** entry with the text of the brief (spec Input), right after the **Service** (deployed service) entry. Add at the end of its description: "A restore's namespace deletion deletes no alias."
- [ ] T029 [P] In `dev/knowledge/agent/operator.md`, section "Deletion": change the teardown order in the platform-driven paragraph to "service aliases in all namespaces → Services/Middlewares → HelmRelease → NetworkPolicies/Secrets"; add a paragraph on the new step: it finds the aliases by `styrmin.io/deployment-id` or, without the label, by `spec.externalName`; it runs only when the namespace is `styrmin-<spec.deploymentId>`; it is best-effort (a 404 counts as deleted, other errors are logged); it runs on both paths, and on the `kubectl delete` path only while the namespace is not being deleted, so a restore's namespace deletion deletes no alias (#503)
- [ ] T030 [P] In `dev/knowledge/backend/orchestration-flows.md`, section "Service aliases": add bullets for the departing rule (Namespace missing or `Terminating`, or a StyrminDeployment with `spec.deletionRequested` or a `deletionTimestamp`), the second read after the writes and the deletion of racing writes with their `resourceVersion`, that a namespace that is gone or terminating is skipped without failing the step, and that the flow creates no namespace; add a bullet that the operator's teardown deletes a deployment's aliases when it is deleted (#503)
- [ ] T031 [P] In `docs/docs/drivers/generic-app.md`, section "Networking", bullet "Other applications of the environment": add that when an application is deleted, Styrmin deletes its service aliases, so its name stops resolving in the other applications of the environment
- [ ] T032 [P] In `dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md`, "More information": remove the bullet "Known case that does not follow the decision yet: deleting a deployment leaves its aliases ... (#503)"; extend the alias bullet: the operator's teardown finds a deleted deployment's aliases in all namespaces by the same rule and deletes them ([#503](https://github.com/opsmill/styrmin/issues/503))
- [ ] T033 [P] Create `changelog/503.fixed.md` with `uv run towncrier create -c "<text>" 503.fixed.md`. Text, one paragraph: deleting a deployment now deletes its service aliases in the namespaces of the other deployments of its environment, and a create, update or upgrade of another deployment that runs during the deletion no longer writes them again or creates the deleted deployment's namespace again; a change of another deployment no longer fails when the deleted deployment's namespace is being deleted; if deleting an alias fails, the deletion continues and the alias can stay; aliases left by deletions made before this version stay

---

## Phase 7: Polish and verification

- [ ] T034 Run `uv run invoke format lint` and `uv run invoke test`; fix failures. Run the docs build for the `generic-app.md` change (`cd docs && pnpm install && pnpm build`, in a `node:22-slim` container when the host Node is older)
- [ ] T035 Run the `ui-chromium` variant of the module in its own session (`-k "ui-chromium"`, same rules), to check that the discovery test still passes with the new alias flow; record it in `e2e-evidence.md`
- [ ] T036 Walk through `specs/026-delete-service-aliases/quickstart.md` (unit tests, E2E, the two `kubectl` checks on the paused session of T015) and note any result that differs in `e2e-evidence.md`
- [ ] T037 Complete `specs/026-delete-service-aliases/pr-notes.md`: link `e2e-evidence.md`; state that the change touches operator and agent code that AGENTS.md lists as high risk (teardown, flow writes into other namespaces); ask the maintainer to confirm (1) the unit test chosen for the brief's open question (spec Clarifications) and (2) FR-017, which the brief did not list; list research R-010 (a deployment's own flow can create its own namespace again after its deletion was requested) as a follow-up issue to file

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: T002, T003, T004 in any order; T005 after T003; T006 after T002 and T004; T007 last. Blocks US1 and US2.
- **US1 (Phase 3)**: after Phase 2. T008 → T009 → T010, T011 → T012. T013 → T014 → T015; T015 needs T009 and, to pass, nothing from US2.
- **US2 (Phase 4)**: after Phase 2. T016 → T017 → T018 → T019 → T020 → T022 → T024; T021 after T017; T023 is independent of the other US2 tasks.
- **US3 (Phase 5)**: after T009.
- **Docs (Phase 6)**: after the behaviour they describe is implemented (T009, T019); T028 to T033 in parallel.
- **Polish (Phase 7)**: after all phases. T035 and T036 after T015.

### User Story Dependencies

- US1 and US2 need only Phase 2 and can be built in parallel; they change different files (`operator/handlers/styrmin_deployment.py` and `agent/tasks/service_aliases.py`).
- US3 tests the function that US1 adds.

### Parallel Opportunities

- Phase 2: T005 and T006.
- US1 and US2 in parallel after Phase 2.
- US2: T021 and T023 in parallel with T018 to T020.
- Phase 6: T028 to T033.
- E2E sessions (T015, T035) each need a full vcluster; run them in sequence on one host.

## Parallel Example: after Phase 2

```text
T008 _delete_service_aliases (operator)
T016 WrittenAlias and owner_namespace (agent)
T023 context test for a DELETING peer
```

## Implementation Strategy

1. Phase 1 and Phase 2: primitives with unit tests.
2. US1 (MVP): the teardown step, its unit tests and the E2E test. This alone fixes the defect that #503 reports, except for the race.
3. US2: the flow guard, which closes the race and stops the namespace from being created again.
4. US3: the best-effort and guard tests.
5. Docs, changelog and polish. US1 and US2 ship together in one change; do not merge US1 without US2, because a flow that runs during a deletion would write the aliases back.
