# Tasks: Service ingress override

**Input**: Design documents from `/specs/033-service-ingress-override/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/graphql-and-manifest.md](contracts/graphql-and-manifest.md), [quickstart.md](quickstart.md), [critique](critiques/critique-20261110-1000.md)

**Tests**: Required. Constitution V asks for tests before the implementation, a GraphQL propagation test for every schema change, and an end-to-end test that is run to a pass for every new feature. API and UI variants apply to scenarios that use the deployment entry points (AGENTS.md).

**Organization**: Tasks are grouped by user story. The Ingress builder and the operator support are foundational, because stories 1, 2 and 3 all rest on them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story of [spec.md](spec.md): US1 publish one service differently, US2 deploy an external service with no override, US3 set the override in the UI, US4 refused changes name the service
- Paths are relative to the repository root `/Users/Simon/styrmin-598-spec`
- Before each commit: `uv run invoke format lint` (Constitution VI). Do not edit generated files by hand.

---

## Phase 1: Setup and verification of what the plan did not verify

**Purpose**: settle the open points of the plan. Each task writes its result into the named section of `research.md`, and changes the plan only if the result differs.

- [X] T001 Verify whether the id of a `DeployedService` row stays the same across a driver version change and a service name override: read the code that writes deployed services (`backend/styrmin_backend/services/deployment.py`, the deployed-services repository under `backend/styrmin_backend/repository/`) and record the result in `research.md` D-005. If the row is recreated, change the Ingress name in `data-model.md` and D-005 to a name built from the driver service name.
- [X] T002 [P] Verify that the Kubernetes role the operator runs under can create, update, list and delete `ingresses` in `networking.k8s.io`: read `helm/agent/templates/roles.yaml` and the operator's service account binding, record the result in `research.md` D-002, and add the rule if it is missing. Do not add resource limits to any chart (AGENTS.md).
- [X] T003 [P] Read `python_sdk/src/styrmin_sdk/models/deployment_manifest.py`, `python_sdk/src/styrmin_sdk/resources/deployments.py` and the CLI `apply` command under `cli/`, and record in `research.md` D-009 whether the manifest `spec.config.services` block needs a hand-written change or comes from regeneration. Record how a manifest without `services` is applied (full replacement or not) and fix `contracts/graphql-and-manifest.md` if it differs.
- [X] T004 [P] Read `frontend/src/pages/deployments/DeployFormPage.tsx` and its GraphQL query, and record in `research.md` D-010 whether the deploy form already reads `applicationDriverVersion.services` with `scope`.
- [X] T005 [P] Read how `fqdn_suffix` is validated for clusters and environments (`backend/styrmin_backend/api/definitions/cluster/inputs.py`, `backend/styrmin_backend/context/models/config.py`) and record in `data-model.md` the exact rule that the override suffix reuses.
- [X] T006 [P] Find the test that covers `IngressUtility.build_app_post_rendering_patches` today (start from `backend/tests/unit/agent/test_utility_resources.py` and `test_utility_builder.py`) and note its name in `research.md` D-001, so the chart-patch regression task (T011) extends it.

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: the config block, the address function, the Ingress builder without an override, and the operator support for the `Ingress` kind.

### Tests first (they must fail before the implementation)

- [X] T007 [P] Write unit tests for `ServiceConfigBlock` and `DeploymentConfig.services` in `backend/tests/unit/context/test_service_config_block.py`: both fields optional, an empty `ingress_class` is rejected, a block with both fields `None` is dropped, an invalid suffix is rejected, `extra="forbid"` rejects other keys, a config without `services` serializes to the same dict as before, and the stored config of an existing deployment round-trips unchanged (data-model, FR-015).
- [X] T008 [P] Write unit tests for the address function in `backend/tests/unit/context/test_service_address.py`: effective class and host with and without an override, the override suffix in the readable host, `primary_fqdn` unchanged, no suffix gives `None`, and a service of another deployment uses its owner's override (FR-006, critique E2).
- [X] T009 [P] Write unit tests for the Ingress builder without an override in `backend/tests/unit/agent/test_ingress_utility_service_ingress.py`: one Ingress per external `http` or `https` service and none for internal, `tcp` and `udp` services; backend is the ClusterIP Service on the declared port; name and labels follow data-model (`styrmin.io/service-name`, name `styrmin-svc-<driver service name>`); readable host for every external service; the application address only on the first declared service when it is external, and not at all when it is internal (FR-002 as changed); annotations equal to the chart patch for the same context (FR-003); `ip_whitelist` middleware, endpoints-type; dedicated ingress controller gives no `spec.ingressClassName` and the implementation annotation (FR-008); no `spec.tls` (FR-007); a missing suffix raises the same `ValueError` as the chart patch.
- [X] T010 [P] Write operator unit tests in `backend/tests/unit/test_ingress_operator_reconcile.py`: `list_managed_resources` returns Ingresses, `delete_kubernetes_resource` deletes an Ingress and ignores a 404, `compute_diff` creates, updates and deletes Ingresses, and the reconcile loops include `Ingress` (D-002, FR-001).
- [X] T011 [P] Extend the chart-patch test found in T006 so it asserts that chart Ingresses still get the class, the annotations and the dedicated-controller removal patch exactly as before (ADR-071, SC-003).

### Implementation

- [X] T012 Add `ServiceConfigBlock` and `DeploymentConfig.services` with the serializer that omits `None`, in `backend/styrmin_backend/context/models/config.py` (data-model). No database column and no Alembic revision.
- [X] T013 [P] Add the address function in `backend/styrmin_backend/context/fqdn.py`: from the resolved config, the optional override, the service and the environment name it returns the effective class, suffix and hosts (research D-007, ADR-022).
- [X] T014 [P] Add `ingress_class` and `overridden` to `ServiceReference` in `backend/styrmin_backend/context/models/services.py`, with defaults.
- [X] T015 Use the address function in `generate_context_from_deployment` in `backend/styrmin_backend/services/context.py`, add `scope` and the effective class and suffix to each `deployed_services` entry, and read the owning deployment's override for services of other deployments (T008).
- [X] T016 Move the annotation and class rules of `build_app_post_rendering_patches` into one helper in `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`, used by the chart patch and by the new builder (research D-006). T011 must still pass.
- [X] T017 Build the Ingress objects in `IngressUtility.build_resources` in `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py` for the no-override case (T009): name `styrmin-svc-<driver service name>`, `styrmin.io/service-name` label, hosts, backend, class, annotations.
- [X] T018 [P] Add `Ingress` to `list_managed_resources` and `delete_kubernetes_resource` in `backend/styrmin_backend/operator/reconciler.py` (T010).
- [X] T019 Add `Ingress` to the reconcile loops in `backend/styrmin_backend/operator/handlers/helmrelease.py` (line 342) and `backend/styrmin_backend/operator/handlers/styrmin_deployment.py` (lines 991 and 1162).
- [X] T020 [P] Add kopf update and delete drift handlers for `ingresses` in `backend/styrmin_backend/operator/handlers/utility_resources.py`, following the NetworkPolicy and Service handlers.
- [X] T021 Confirm that the Prefect path applies the Ingress: read `backend/styrmin_backend/agent/tasks/extra.py` (`_apply_utility`, `_filter_out_operator_managed_resources`) and add a unit test in `backend/tests/unit/agent/test_utility_resources.py` that an `Ingress` object is neither filtered out nor left unlabeled.

**Checkpoint**: unit tests T007 to T011 pass. An external service gets a Styrmin-built Ingress with the resolved class, and the operator keeps it in step.

---

## Phase 3: User Story 1 - Publish one service with a different ingress class and suffix (Priority: P1) MVP

**Goal**: an operator sets the class and suffix of `task-manager` in an Infrahub deployment, and only that service moves.

**Independent test**: deploy `infrahub` on the new driver version, set the override, and compare the Ingresses before and after (quickstart step 2).

### Tests first

- [X] T022 [P] [US1] Add override cases to `backend/tests/unit/agent/test_ingress_utility_service_ingress.py`: override class and suffix in the hosts, only `kubernetes.io/ingress.class` and `spec.ingressClassName` set, no entry-point, external-dns, Cloudflare or allow-list annotation (FR-004), an override with a dedicated ingress controller on (FR-008), and the other services' Ingresses unchanged (SC-002).
- [X] T023 [P] [US1] Write the GraphQL propagation test in `backend/tests/functional/graphql/test_service_ingress_propagation.py` (the location that `dev/guides/graphql-propagation-tests.md` names for HTTP-driven propagation tests), following `dev/guides/graphql-propagation-tests.md`: `ServiceConfigInput` on `deploy`, `updateDeployment` and `updateDeploymentVersion` reaches `Deployment.config["services"]`; omitting `services` clears it; the output fields on the deployment config and on `DeployedService` read back the stored state (Constitution V).
- [X] T024 [P] [US1] Write the Infrahub driver unit tests: extend `backend/tests/unit/agent/test_infrahub_values_prefect_env.py` or add `backend/tests/unit/agent/test_infrahub_driver_task_manager.py` to assert that the new `infrahub` and `infrahub-enterprise` driver versions declare `task-manager` as `scope: external`, turn off the Prefect Ingress, keep `infrahub` as `internal` with its chart Ingress and its `primary_fqdn` host, and read the override host in `prefectUiApiUrl` (FR-013).
- [X] T025 [US1] Write the end-to-end test `backend/tests/e2e/test_service_ingress_override.py` with marker `shard_infrahub`, API and UI variants: user story 1 scenarios 1 and 2 of [spec.md](spec.md), plus an environment with a dedicated ingress controller and one overridden service (scenario 3). The test asserts objects on the vCluster, not traffic. Reuse the Infrahub stack that `test_infrahub_services.py` boots (AGENTS.md "Reuse before you boot"); confirm first that the fixture has an active consumer.

### Implementation

- [X] T026 [US1] Handle the override in `IngressUtility.build_resources` in `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py` (T022).
- [X] T027 [P] [US1] Add `ServiceConfigInput` and `DeploymentConfigInput.services` in `backend/styrmin_backend/api/definitions/deployment/inputs.py`, with the conversion to the stored dict next to the `components` conversion in the same file, and wire it in `backend/styrmin_backend/api/schema/mutation.py` (contract).
- [X] T028 [P] [US1] Add the output type for the stored overrides in `backend/styrmin_backend/api/definitions/deployment/model.py`, and `ingress_class`, `ingress_class_overridden` and `fqdn_suffix_overridden` to `DeployedService` in `backend/styrmin_backend/api/definitions/service/model.py`, filled by the address function so `human_readable_fqdn` and `human_readable_url` use the override suffix (FR-006).
- [X] T029 [US1] Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`), the SDK types and the frontend types (`uv run invoke generate`), and run `uv run invoke validate-graphql`. CI fails if any of them is out of date. Then replace `_read_deployment` in `backend/tests/functional/graphql/test_service_ingress_propagation.py`, which builds the read operations for the new output fields through the `graphql` AST, with `.graphql` files in `backend/tests/functional/graphql/operations/`.
- [X] T030 [P] [US1] Make the manifest `spec.config.services` block work through `styrminctl deployments apply` in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py` and `cli/` as T003 found, with a test in the SDK tests that applies a manifest with an override and reads it back (the block must not be dropped like unknown component keys).
  - [X] T030a `DeploymentResource.scale` in `python_sdk/src/styrmin_sdk/resources/deployments.py` sends only `components`, and `updateDeployment` replaces the whole stored config. Reproduced first by `backend/tests/functional/graphql/test_sdk_scale_keeps_service_overrides.py` (2 of 3 tests failed before the fix: the stored `services` was cleared); `scale` now resends the stored `services`. `scale` still clears every other stored config key (a probe showed `ip_whitelist` and `env_vars` cleared): not changed here. Other builders of a partial `UpdateDeploymentInput`: the CLI `update` and `update-version` commands take the whole payload from the user and `apply` builds it from the manifest (both are full replacement by design); the frontend `deploymentConfigToInput` in `frontend/src/lib/deployment-input.ts` lists every config field and has no `services`, so the UI save would clear overrides until Phase 5 (T039 to T046) adds it.
- [X] T031 [P] [US1] Update the `infrahub` driver in `driver/examples/infrahub/driver.styrmin.yml` and `values.j2.yml`: new driver version, `task-manager` `scope: external`, `prefect-server.ingress.enabled: false`, `infrahub` stays `internal` with its chart Ingress (FR-013). Check `backend/tests/unit/test_e2e_driver_conformance.py` and `test_drivers_have_no_override_wiring.py` still pass.
- [X] T032 [P] [US1] Make the same change in `driver/examples/infrahub-enterprise/driver.styrmin.yml` and `values.j2.yml`.
- [X] T033 [US1] Run T025 to a pass. Record the pytest node ids, the exact command, the ISO 8601 time, the vcluster id and kubeconfig path, and the verbatim `PASSED` lines in `specs/033-service-ingress-override/e2e-evidence.md` (Constitution V). API variant passed; the UI variant is not run and is deferred to T048.

**Checkpoint**: user story 1 works through the API and a manifest, with no UI.

---

## Phase 4: User Story 2 - Deploy an external service with no override (Priority: P2)

**Goal**: a driver that declares a service `external` gets its Ingress from Styrmin, and its chart needs none.

**Independent test**: deploy `generic-app` and count its Ingresses (quickstart step 3).

### Tests first

- [X] T034 [P] [US2] Extend `backend/tests/e2e/test_deploy_generic_app.py` (marker `shard_general`, already `api_only`): assert exactly one Ingress for the `app` service with the resolved class, the annotations of the former chart Ingress, and both the application address and the readable host; delete the deployment and assert the Ingress is gone (FR-001, FR-012, SC-006). The Ingress also covers the first-service rule on a real stack.
- [X] T035 [P] [US2] Add a unit test with a two-external-service driver fixture in `backend/tests/unit/agent/test_ingress_utility_service_ingress.py`, if T009 did not already cover it, asserting exactly one Ingress has the application address (FR-002). T009 already covers it (`test_the_application_address_is_on_exactly_one_ingress` with three external services, `test_the_application_address_is_only_on_the_first_declared_service` with two); no test added.

### Implementation

- [X] T036 [US2] Remove the chart Ingress from `driver/examples/generic-app/values.j2.yml` (the `ingress:` block near line 83) and bump the driver version in `driver/examples/generic-app/driver.styrmin.yml`; update `docs/docs/drivers/generic-app.md` (FR-012).
- [X] T037 [US2] Run T034 to a pass and record the evidence in `specs/033-service-ingress-override/e2e-evidence.md`.

**Checkpoint**: stories 1 and 2 work. A deployment of a driver in this repository that declares no external service has no Ingress difference (SC-003): add the assertion to `backend/tests/e2e/test_deploy_app.py` or the existing `simple-app` test as a read of its Ingress objects.

- [X] T038 [P] [US2] Add the SC-003 read-only assertion to an existing end-to-end test that already deploys `simple-app` or `semaphore` (find it in `backend/tests/e2e/test_deploy_app.py` or `test_deploy_semaphore.py`), without booting a new stack.

---

## Phase 5: User Story 3 - Set, view and clear the override in the UI (Priority: P3)

**Goal**: an operator sets the class and suffix of one service on the Configuration tab and on the deploy form, and the Networking summary shows what is published where.

**Independent test**: quickstart step 4.

### Tests first

- [ ] T039 [P] [US3] Extend `frontend/src/components/deployment/configuration/sections/edit/ServiceOverridesSection.test.tsx`: only external services are offered, set and clear class and suffix, suffix validation, and the form sends `services` in the update input.
- [ ] T040 [P] [US3] Add a Vitest test for `frontend/src/components/deployment/configuration/sections/read/NetworkingSummary.tsx` (new `NetworkingSummary.test.tsx` next to it): per-service class and host, marked overridden or inherited (FR-016).
- [ ] T041 [P] [US3] Extend `frontend/src/lib/config-diff.test.ts` and `frontend/src/lib/config-impact.test.ts` for the new `services` config (the diff dialog and the impact rules).
- [ ] T042 [US3] Add the UI variant steps of `backend/tests/e2e/test_service_ingress_override.py` (T025) using page objects `backend/tests/e2e/pages/deployment_detail.py` and `deploy_form.py`: Configuration, Service overrides, Networking summary, and the deploy form fields.

### Implementation

- [ ] T043 [US3] Extend `frontend/src/components/deployment/configuration/sections/edit/ServiceOverridesSection.tsx`: per external service, fields for ingress class and FQDN suffix, with a clear action; keep the existing service name override rows.
- [ ] T044 [P] [US3] Pass the services with their scope from `deployment.deployedServices` to the section in `frontend/src/components/deployment/configuration/ConfigEditDrawer.tsx` (line 136 and 275-280).
- [ ] T045 [P] [US3] Show per-service class and host with overridden or inherited marks in `frontend/src/components/deployment/configuration/sections/read/NetworkingSummary.tsx`.
- [ ] T046 [P] [US3] Carry `services` through `frontend/src/lib/deployment-input.ts`, `frontend/src/lib/config-diff.ts` and `frontend/src/lib/impact-rules.ts`.
- [ ] T047 [US3] Add the same fields to the deploy form in `frontend/src/pages/deployments/DeployFormPage.tsx`, reading the services of the selected driver version (T004).
- [ ] T048 [US3] Run the UI variant of T025 to a pass; record the evidence; run `cd frontend && pnpm test`.

**Checkpoint**: stories 1, 2 and 3 work.

---

## Phase 6: User Story 4 - Refused changes name the service (Priority: P3)

**Goal**: an override that Styrmin cannot honour, and a driver version change that would drop one, fail with an error that names the service, before any pod changes.

**Independent test**: quickstart step 5.

### Tests first

- [ ] T049 [P] [US4] Write validator unit tests in `backend/tests/unit/services/service_ingress/test_validator.py` (new directory with `__init__.py`): unknown service, internal service, external service accepted, a version change that removes or internalizes a service with a stored override is refused, a version change that keeps it is allowed, clearing a stale override is allowed (FR-009, FR-010, SC-004).
- [ ] T050 [P] [US4] Write the `api_only` end-to-end test steps in `backend/tests/e2e/test_service_ingress_override.py`: an override on `infrahub` returns `SERVICE_INGRESS_NOT_BUILT`; a version change that makes `task-manager` internal returns `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`, no pod restarts, the override is still stored. Use the existing upgrade test pattern for retired parameters.

### Implementation

- [ ] T051 [P] [US4] Add `backend/styrmin_backend/services/service_ingress/__init__.py`, `exceptions.py` (three `ServiceError` subclasses with the codes and metadata of the contract) and `validator.py`, mirroring `backend/styrmin_backend/services/replicas/`.
- [ ] T052 [US4] Call the validator next to `_validate_replica_overrides` in `backend/styrmin_backend/services/deployment.py` (around line 367) for `deploy`, `updateDeployment` and `updateDeploymentVersion`, so the version check runs before any pod changes. `apply` must hit the same path (ADR-065).
- [ ] T053 [P] [US4] Show the typed errors in the UI Service overrides section and on the deploy form (find the shared error rendering the replica errors use in `frontend/src/components/deployment/configuration/` and reuse it), with a Vitest case in `ServiceOverridesSection.test.tsx`.
- [ ] T054 [US4] Run T050 to a pass and record the evidence.

**Checkpoint**: all four stories work.

---

## Phase 7: Polish and documentation (Constitution VII)

- [ ] T055 [P] Correct the `scope` statements in `docs/docs/drivers/creating-a-driver.md` (lines 511-520, and the services note near line 707) and `docs/docs/concepts-and-architecture/ingress-and-networking.md` (lines 323-324 and the service section near 292 and 439): `scope: external` means Styrmin builds the Ingress, `internal` means it does not, and state how Styrmin chooses the readable host and the application address of a service (FR-011).
- [ ] T056 [P] Add `docs/docs/concepts-and-architecture/service-ingress-overrides.md`: what an override does, the manifest and API forms, the UI path, the `ip_whitelist` limit (FR-005), the Tailscale `tls` status (not tested), and that the tests check objects, not traffic. Add it to the sidebar.
- [ ] T057 [P] Add the migration guide `docs/docs/drivers/migrating-external-service-ingress.md` next to `migrating-replica-parameters.md` (FR-014): steps for a driver that declares `external` and renders its own Ingress, the effect at the Styrmin upgrade (spec edge case), the downgrade effect, and what is not known (the number of drivers outside this repository).
- [ ] T058 [P] Update `docs/docs/reference/driver-api.md`, `docs/docs/reference/styrmindeployment.md` and the CLI reference if the manifest block appears there, and `docs/docs/drivers/changing-driver-versions.md` for the refused change (FR-010).
- [ ] T059 [P] Add the ADR in `dev/adr/` (next number after 0088, chosen at implementation): Styrmin builds the Ingress of external services; the application address rule; refuse rather than drop on a version change; mark the affected part of ADR-071 as superseded. Update `dev/knowledge/architecture.md` and the backend knowledge page on ingress if one exists under `dev/knowledge/backend/`.
- [ ] T060 [P] Update `CONTEXT.md` with the terms "service ingress override" and "Styrmin-built Ingress", and check the glossary in `docs/docs/concepts-and-architecture/glossary.md`.
- [ ] T061 [P] Add the towncrier fragment in `changelog/` with `uv run towncrier create -c "..." 598.<type>.md`; the type follows `dev/guidelines/changelog.md`. It names the breaking change for drivers that declare `external` (FR-014).
- [ ] T062 Run the SC-005 and interruption checks by hand where possible and record them in `e2e-evidence.md`: the upgrade of a running `infrahub` deployment (quickstart step 7) and, if a Tailscale operator is available, the tailnet access. If not available, write "not verified" and why.
- [ ] T063 Confirm `git diff origin/develop -- backend/styrmin_backend/db/models.py backend/styrmin_backend/db/migrations` is empty, which confirms that no Alembic revision is needed (plan, Storage).
- [ ] T064 Run `uv run invoke format lint`, `uv run invoke test`, `cd frontend && pnpm test` and `pnpm lint`, the three schema and SDK regeneration commands (no diff expected), and `uv run invoke validate-graphql`.
- [ ] T065 Walk through [quickstart.md](quickstart.md) once end to end and fix any step that does not match what was built.

---

## Dependencies and order

- Phase 1 has no dependency. T001 to T006 can run together.
- Phase 2 needs Phase 1 for T001 (name), T002 (RBAC), T005 (suffix rule) and T006. Tests T007 to T011 before T012 to T021.
  - T012 before T013, T015, T017. T013 before T015. T016 before T017. T018 before T019 and T020.
- Phase 3 (US1) needs Phase 2. T022 to T025 first. T026 needs T017. T027 and T028 need T012 and T013. T029 needs T027 and T028. T030 needs T029 and T003. T031 and T032 need T026 and T029.
- Phase 4 (US2) needs Phase 2 only; it can run in parallel with Phase 3 after T017.
- Phase 5 (US3) needs T029 (regenerated types) and Phase 3.
- Phase 6 (US4) needs T012, T027 and T029. It can run in parallel with Phase 5.
- Phase 7 after the stories it documents. T055 to T061 can start once the behaviour is fixed (after Phase 3).

## Parallel examples

- Phase 1: T002, T003, T004, T005 and T006 together.
- Phase 2 tests: T007, T008, T009, T010 and T011 together (five different files).
- US1 tests: T022, T023 and T024 together; US1 implementation: T027, T028, T031 and T032 together.
- US3: T039, T040 and T041 together; T044, T045 and T046 together.

## Implementation strategy

1. Minimum useful scope: Phase 1, Phase 2 and Phase 3. That fixes the sandbox problem through the API and a manifest (SC-005 object part, SC-002).
2. Then Phase 4 (generic-app) because it shares the builder and is the other driver that changes, then Phase 6 (refusals) and Phase 5 (UI) in either order.
3. Ship all stories in one release: the driver changes and the build-and-patch change must reach users together (FR-012, FR-013, FR-014).

## Open items that the tasks cannot close

- The PRD owner must confirm the changed FR-002 (critique E1) and decide the question in the spec edge case about existing external-declaring deployments (critique P1).
- The Tailscale `tls` question, the count of drivers outside this repository, the interruption during the Infrahub move, and backup and restore of an environment with Styrmin-built Ingresses are not known. T062 records what can be measured.
