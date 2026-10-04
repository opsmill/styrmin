---
description: "Task list for 018-component-image-overrides"
---

# Tasks: Per-Component Image Overrides via Post-Render

**Input**: Design documents from `specs/018-component-image-overrides/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution §V (test-first, E2E definition of done, GraphQL propagation tests) applies. Within each phase, write the listed tests first and see them fail before implementing.

**Organization**: Tasks are grouped by user story (spec.md) so each story can be implemented and tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 to US4 from spec.md
- Paths are repo-relative. Backend code lives in `backend/styrmin_backend/`, backend tests in `backend/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeletons and the shared grammar vectors both languages test against.

- [X] T001 Create `frontend/src/lib/image-reference.vectors.json`: an array of `{reference, valid, reason?, note}` cases covering research D-007. Valid: `simple-app:0.1.0`, `registry.example/acme/app:1.0.0`, `localhost:5000/app:v1`, `[::1]:5000/a/b:t`, `app@sha256:<64 hex>`, `app:1.0@sha256:<64 hex>`, path separators `.`, `_`, `__`, `-`, a 128-char tag. Invalid with `reason`: `app` (`missing_tag_or_digest`), `App:1` (`grammar`), `app:` (`grammar`), `app:-x` (`grammar`), a 129-char tag (`grammar`), `app@sha256:abc` (`grammar`), whitespace or control characters (`grammar`), `app:{{ app.name }}` (`template_expression`), `app:{% x %}` (`template_expression`). Token cases: `app:{{ app.version }}`, `app:{{app.version}}`, `app:{{   app.version   }}`, and `{{ app.version }}` in a path component.
- [X] T002 [P] Create package skeletons `backend/styrmin_backend/services/image_overrides/__init__.py` and `backend/styrmin_backend/services/component_container/__init__.py` (module docstrings only).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Storage, context, reference logic, and the shared post-render patch builder with its guard. Every story depends on them.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

### Tests first

- [X] T003 [P] Write `backend/tests/unit/services/image_overrides/test_reference.py`: load `frontend/src/lib/image-reference.vectors.json` (repo-relative path) and assert `validate_reference(ref, version=...)` accepts or rejects each case with the expected `reason`. Cover `substitute_app_version` (every occurrence, whitespace-tolerant), `has_app_version_token`, the `after_substitution` reason (`app:{{ app.version }}` with version `1.0.0+build`), and placeholder validation (`validate_stored_reference` uses version `0`).
- [X] T004 [P] Write `backend/tests/unit/services/image_overrides/test_resolver.py` mirroring `backend/tests/unit/services/test_container_overrides_resolver.py`: live entries per driver component, orphans sorted by name, blocks without `image` dropped, `driver_components=None` returns nothing.
- [X] T005 [P] Write `backend/tests/unit/services/component_container/test_exceptions.py`: `parse_guard_failure(message)` returns `(component, container)` for a captured helm-controller-style message containing `/spec/template/spec/styrmin.io~1component-container~1server~1wrong-name/image`, unescapes `~1` and `~0` in the component name, and returns `None` for unrelated messages. Also assert `ComponentContainerNotFoundError` code, metadata, and message (contracts/errors.md).
- [X] T006 [P] Extend `backend/tests/unit/agent/test_container_env_patch.py` and add `backend/tests/unit/agent/test_component_container_patch.py`: `ContainerEnvPatch` with empty env renders `containers: [{name: C}]` and no `env` key; `ComponentContainerPatch` renders exactly the op lists in contracts/post-render-patch.md (image variant and env-only variant) through `yaml.dump`, JSON-pointer-escapes component names containing `~` and `/`, and round-trips a reference with every allowed separator.
- [X] T007 [P] Write `backend/tests/unit/services/component_container/test_patch_builder.py` (move the cases from `backend/tests/unit/services/env_vars/test_patch_builder.py` here and delete that file): no patch for a component without a container or without any override (SC-002 golden: a context with no overrides yields an empty list); env only → 2 patches per kind (SMP with env, env-only guard); image only → SMP name-only + image JSON6902 with the substituted reference; both → SMP with env + image JSON6902; orphaned env vars or orphan image skipped; `{{ app.version }}` resolved from `context.app.version`; invalid after substitution raises `InvalidImageReferenceError` (reason `after_substitution`, `component_name`); one log line per component without values.
- [X] T008 [P] Extend `backend/tests/unit/agent/test_application_builder_env_vars.py`: component-container patches are appended after every other post-render patch, including when only an image override is set.
- [X] T009 [P] Write `backend/tests/integration/test_component_container_kustomize.py` (skips when `kubectl` is absent; CI's integration job has it): render the builder's real patches into a kustomization over a fixture with `initContainers: [init]`, `containers: [sidecar, main]`, a `Job` and a `StatefulSet` sharing the label, then run `kubectl kustomize`. Assert: image override on `main` sets the image, keeps env, `imagePullPolicy`, `sidecar`, `init`, and the `Job`; wrong name fails with the guard key naming component and container, and no output; env-only on `main` gives a workload byte-identical to the env strategic merge alone (SC-002); env-only with a wrong name fails the same way; a kind matching nothing is a no-op.

### Implementation

- [X] T010 Implement `backend/styrmin_backend/services/image_overrides/exceptions.py`: `InvalidImageReferenceError` (`INVALID_IMAGE_REFERENCE`; metadata `component_name`, `reference`, `reason`, `application_version`) and `UnknownComponentImageOverrideError` (`UNKNOWN_COMPONENT_IMAGE_OVERRIDE`; metadata `component_name`, `known_components`), following `backend/styrmin_backend/services/container_overrides/exceptions.py`.
- [X] T011 Implement `backend/styrmin_backend/services/image_overrides/reference.py`: `APP_VERSION_TOKEN_RE`, `substitute_app_version(ref, version)`, `has_app_version_token(ref)`, `validate_reference(ref, *, version, component_name=None) -> str` (returns the resolved reference; raises `InvalidImageReferenceError` with the reasons in data-model.md §1), and `validate_stored_reference(ref)` (placeholder version `0`). Hand-written grammar per research D-007; no new dependency. Makes T003 pass.
- [X] T012 Implement `backend/styrmin_backend/services/component_container/exceptions.py`: `ComponentContainerNotFoundError` (`COMPONENT_CONTAINER_NOT_FOUND`; metadata `component_name`, `container`) and `parse_guard_failure(message) -> tuple[str, str] | None` (`GUARD_KEY_PREFIX = "styrmin.io~1component-container~1"`; parse the key that precedes `/image`; unescape). Makes T005 pass.
- [X] T013 Generalize `ComponentContainerNotDeclaredError` in `backend/styrmin_backend/services/env_vars/exceptions.py` with `override: Literal["env_vars", "image"] = "env_vars"` (new metadata key, image-specific message per contracts/errors.md; env message unchanged), and extend its tests in `backend/tests/unit/services/env_vars/test_validator.py` or the existing test module that covers it.
- [X] T014 Add `image: str | None = None` to `ComponentConfigBlock` in `backend/styrmin_backend/context/models/config.py` with a `mode="before"` field validator calling `validate_stored_reference` (lazy import, as `command`/`args` do); update the class and `DeploymentConfig` docstrings.
- [X] T015 [P] Add `ResolvedComponentImageOverride {reference: str, is_orphaned: bool = False}` (`extra="forbid"`) and `ComponentContext.image_override: ResolvedComponentImageOverride | None = None` in `backend/styrmin_backend/context/models/components.py`.
- [X] T016 Implement `backend/styrmin_backend/services/image_overrides/resolver.py` (`ImageOverridesResolver.resolve_for_deployment`, `ResolvedImageOverrideEntry`), mirroring `backend/styrmin_backend/services/container_overrides/resolver.py`. Makes T004 pass.
- [X] T017 Add `_populate_component_image_overrides` to `backend/styrmin_backend/services/context.py` and call it after `_populate_component_container_overrides`: attach `image_override` only to live components with an override, leave `None` otherwise. Extend `backend/tests/unit/services/test_services_context.py` (live, orphan not attached, none when unset).
- [X] T018 In `backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py`: make `ContainerEnvPatch.env` optional (omit the `env` key when empty) and add `ComponentContainerPatch(component, container, image: str | None, kind)` rendering the JSON6902 op list from contracts/post-render-patch.md with `yaml.dump` and JSON-pointer escaping. Makes T006 pass.
- [X] T019 Implement `build_component_container_patches(context)` in `backend/styrmin_backend/services/component_container/patch_builder.py` per contracts/post-render-patch.md (env from `component.env_vars`, image from `component.image_override` substituted with `context.app.version` via `validate_reference`; eager render validation like today's `_validate_renders`). Remove `backend/styrmin_backend/services/env_vars/patch_builder.py` and update its importers. Makes T007 pass.
- [X] T020 In `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`, replace `build_env_var_post_rendering_patches` with `build_component_container_post_rendering_patches` calling the shared builder, still appended last. Makes T008 and T009 pass.

**Checkpoint**: an override stored in `Deployment.config` renders onto the component container; a wrong name fails the render; env-var output is unchanged.

---

## Phase 3: User Story 1 - Run a custom build on one component (Priority: P1) 🎯 MVP

**Goal**: A user sets `server`'s image through GraphQL, the SDK, `apply`, or the configuration editor, and the component container runs it after the next reconcile; the read-back shows stored, resolved, and applied.

**Independent Test**: E2E test 1's set half (quickstart §3): override `server` on a `simple-app` deployment, read the live pod spec and `componentImageOverrides`.

### Tests for User Story 1

- [X] T021 [P] [US1] Write `backend/tests/functional/graphql/test_image_overrides_propagation.py` (pattern: `test_container_overrides_propagation.py`): `ComponentConfigInput.image` on `updateDeployment` and on `deploy` reaches `Deployment.config.components.<name>.image`; `Deployment.componentImageOverrides` projects `reference`, `resolvedReference` (token replaced with `applicationVersion`), `isOrphaned`, and `isApplicable`.
- [X] T022 [P] [US1] Extend `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.test.tsx`: an "Image" input appears for a component with a container, valid input passes, and the value is mapped into the submitted component block. Extend `frontend/src/lib/deployment-input.test.ts`: `image` round-trips read → form → `ComponentConfigInput`, and an empty field becomes `image: null`.
- [X] T023 [P] [US1] Write `frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.test.tsx`: shows stored and resolved references and an "applied" badge when `isApplicable`, "not applied" otherwise.
- [X] T024 [P] [US1] Write `frontend/src/lib/image-reference.test.ts` driven by `image-reference.vectors.json` (same expectations as T003, including the token helpers).

### Implementation for User Story 1

- [X] T025 [US1] Add `image: str | None` to `ComponentConfigInput` in `backend/styrmin_backend/api/definitions/deployment/inputs.py` (description from contracts/graphql-deltas.md) and pass it through `_flatten_components` for both `update_deployment_input_to_dict` and `deployment_config_input_to_dict`; update the `ComponentConfigInput` class description.
- [X] T026 [US1] Add the `ComponentImageOverride` Strawberry type and `Deployment.component_image_overrides` resolver in `backend/styrmin_backend/api/definitions/deployment/model.py`, mirroring `component_container_overrides` plus `component_env_vars`'s `isApplicable` (containers from `deployment.components`); compute `resolvedReference` with `substitute_app_version(reference, deployment.application_version)`.
- [X] T027 [US1] Regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`).
- [X] T028 [US1] Add `componentImageOverrides { component reference resolvedReference isOrphaned isApplicable }` to `python_sdk/src/styrmin_sdk/graphql/get_deployment.graphql`, create `python_sdk/src/styrmin_sdk/graphql/get_deployment_component_image_overrides_full.graphql` (`GetDeploymentComponentImageOverridesFull`), run `uv run invoke validate-graphql` and `uv run invoke generate`. Makes T021 pass.
- [X] T029 [US1] Add `componentImageOverrides { … }` to `frontend/src/graphql/get_deployment.graphql` and regenerate frontend types (part of `uv run invoke generate`).
- [X] T030 [P] [US1] Implement `frontend/src/lib/image-reference.ts`: `validateImageReference(ref) -> {reason} | null`, `hasAppVersionToken(ref)`, `APP_VERSION_TOKEN_RE`, mirroring research D-006/D-007. Makes T024 pass.
- [X] T031 [US1] In `frontend/src/lib/deployment-input.ts`, carry `image` on `ReadComponentBlock`, `componentsDictToList`, and the form → `ComponentConfigInput` mapping (empty string → `null`). Makes T022's mapping cases pass.
- [X] T032 [US1] In `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx`, add `image: z.string().optional()` to `componentOverridesSchema` with a refinement on `validateImageReference`, an "Image" input in `ComponentOverrideBody` for components with a container (hint text from contracts/client-surfaces.md), and the image token in `summariseOverrideRow`. Makes T022 pass.
- [X] T033 [US1] In `frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx`, render per-component image rows from `componentImageOverrides` (stored, resolved, applied badge). Confirm `frontend/src/lib/config-diff.ts` shows image changes in the Review & apply dialog (extend `config-diff.test.ts` if not). Makes T023 pass.
- [X] T034 [P] [US1] E2E harness: add a session fixture `simple_app_override_images` in `backend/tests/e2e/conftest.py` that depends on `simple_app_image` and `simple_app_image_v2` and runs `docker tag` to `registry.example/acme/simple-app-patched:0.1.0` and `:0.2.0`.
- [X] T035 [US1] Add `set_component_image(*, deployment_id, component, image: str | None)` to `backend/tests/e2e/drivers/protocol.py`; implement it in `backend/tests/e2e/drivers/api_driver.py` (`updateDeployment` with the stored components plus `image`, preserving other slots) and in `backend/tests/e2e/drivers/ui_driver.py` via a new `set_component_image` on `backend/tests/e2e/pages/deployment_detail.py` (open the configuration drawer, fill or clear the component's Image input, Review & apply, confirm). Keep `backend/tests/unit/test_e2e_driver_conformance.py` green.
- [X] T036 [US1] Create `backend/tests/e2e/test_deployment_image_override.py` (`pytestmark = [pytest.mark.shard_configuration]`; every test function also gets `@pytest.mark.ci`, as in `test_deployment_env_vars.py`) with a module environment and deployment fixture (pattern: `test_deployment_container_overrides.py`) and `test_override_then_clear` (dual-entrypoint) covering the set half: `set_component_image(server, "registry.example/acme/simple-app-patched:0.1.0")`, wait for the pod template, assert the `simple-app` container image, unchanged `initContainers`, env, and container count, and `componentImageOverrides` (`reference`, `resolvedReference`, `isApplicable: true`). Run it to a pass with `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_image_override.py::test_override_then_clear -v -s --pdb`.

**Checkpoint**: US1 is usable end-to-end through API and UI.

---

## Phase 4: User Story 2 - Follow the application version (Priority: P2)

**Goal**: `{{ app.version }}` overrides follow upgrades; pinned overrides are listed before confirming in the UI and in `apply` output; upgrades that would break a reference are rejected up front; action Jobs see the override.

**Independent Test**: E2E test 2 (quickstart §3): pinned listing, then token override at 0.1.0, upgrade to 0.2.0, assert the `server` image and the action Job image.

### Tests for User Story 2

- [X] T037 [P] [US2] Extend `backend/tests/functional/graphql/test_image_overrides_propagation.py`: `updateDeploymentVersion` to a version whose substitution breaks a stored, applicable reference returns `INVALID_IMAGE_REFERENCE` (reason `after_substitution`, `application_version`) and creates no task; a non-applicable (containerless) stored override does not block the upgrade.
- [X] T038 [P] [US2] Write `backend/tests/unit/agent/test_get_component_images.py`: with `container` given and present, its image is element 0 and the list keeps every image; absent or unset container keeps pod-template order. Extend the action-task test (or add one) that `actions/primitives.py::get_component_images` passes `context.components[component].config.container`.
- [X] T039 [P] [US2] Write `python_sdk/tests/test_image_reference.py` (`has_app_version_token`, `pinned_image_components`) and extend `python_sdk/tests/test_deployments.py`: `apply` on a version change sets `ApplyOutcome.pinned_image_components` from the manifest's components when present, else from the stored config; empty on create and when the version is unchanged.
- [X] T040 [P] [US2] Extend `cli/tests/test_deployments.py`: `styrminctl deployments apply` prints the `warning:` line from contracts/client-surfaces.md to stderr for an outcome with pinned components, and the exit code is unchanged.
- [X] T041 [P] [US2] Write `frontend/src/components/deployment/PinnedImageOverridesNotice.test.tsx`: lists applicable, token-free overrides with their references; renders nothing when every override has the token or is not applicable.

### Implementation for User Story 2

- [X] T042 [US2] In `backend/styrmin_backend/services/deployment.py::update_deployment_version`, after resolving `target_driver_version` and before no-op detection and task dispatch, validate every stored override whose component has a container in the target driver version with `validate_reference(ref, version=<target>, component_name=...)`. Makes T037 pass.
- [X] T043 [US2] Add a keyword-only `container: str | None = None` to `get_component_images` in `backend/styrmin_backend/agent/service/kubernetes/primitives.py` (component container's image first when present) and pass `context.components[component].config.container` from `get_component_images` in `backend/styrmin_backend/actions/primitives.py` (signature unchanged; update both docstrings). Makes T038 pass.
- [X] T044 [P] [US2] Update the `upgrade` actions in `driver/examples/simple-app/actions.py`, `driver/examples/infrahub/actions.py`, and `driver/examples/infrahub-enterprise/actions.py`: take `images[0]` instead of a substring match and compute `image_base = image.split("@", 1)[0].rsplit(":", 1)[0]`.
- [X] T045 [P] [US2] Implement `python_sdk/src/styrmin_sdk/models/image_reference.py` (`APP_VERSION_TOKEN_RE`, `has_app_version_token`, `pinned_image_components(overrides: Mapping[str, str | None]) -> list[str]`, sorted); export it from `python_sdk/src/styrmin_sdk/models/__init__.py`.
- [X] T046 [US2] Add `pinned_image_components: list[str] = []` to `ApplyOutcome` in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py` and compute it in `_apply_update` in `python_sdk/src/styrmin_sdk/resources/deployments.py` (research D-011). Makes T039 pass.
- [X] T047 [US2] Print the pinned-override warning to stderr in `cli/src/styrminctl/commands/deployments.py::apply` for both the non-wait and wait output paths. Makes T040 pass.
- [X] T048 [US2] Implement `frontend/src/components/deployment/PinnedImageOverridesNotice.tsx` (uses `hasAppVersionToken`) and render it in the upgrade dialog in `frontend/src/pages/deployments/DeploymentDetailPage.tsx`, above the confirm button, from the deployment query's `componentImageOverrides`. Makes T041 pass.
- [X] T049 [US2] Add `pinned_image_components(*, deployment_id, target_version) -> list[str]` to `backend/tests/e2e/drivers/protocol.py`; API implementation in `api_driver.py` uses the SDK helper over `componentImageOverrides`; UI implementation in `ui_driver.py` uses a new `read_pinned_image_warning(target_version)` on `backend/tests/e2e/pages/deployment_detail.py` (open the upgrade dialog, pick the version, read the list, cancel).
- [ ] T050 [US2] Add `test_token_follows_upgrade_and_action_job` (dual-entrypoint) to `backend/tests/e2e/test_deployment_image_override.py` with its own deployment at 0.1.0: set a pinned override and assert `pinned_image_components(…, "0.2.0") == ["server"]`; set `registry.example/acme/simple-app-patched:{{ app.version }}` and assert `[]`; `upgrade_deployment` to 0.2.0; assert the `server` image is `…-patched:0.2.0`, the `<release_reference>-job` Job's container image is `…-patched:0.2.0`, and `resolvedReference` follows. Run to a pass with `--pdb` (`sleep infinity |` prefix).
  - ⚠️ Partial: the `<release_reference>-job` image assertion is omitted. The simple-app `upgrade` action's first primitive (`stop_components`) calls the Styrmin API without credentials and fails with `Authentication is required` under default-deny auth (opsmill/styrmin#381), so the Job never runs. Everything else passes in both variants.

**Checkpoint**: US1 and US2 work independently; the upgrade path is safe.

---

## Phase 5: User Story 3 - Clear the override (Priority: P3)

**Goal**: Clearing the override restores the chart image on the next reconcile.

**Independent Test**: E2E test 1's clear half.

### Tests for User Story 3

- [ ] T051 [P] [US3] Extend `backend/tests/functional/graphql/test_image_overrides_propagation.py`: submitting the component block without `image` (and with `image: null`) clears it, and `componentImageOverrides` no longer lists it. Extend `backend/tests/unit/services/component_container/test_patch_builder.py`: after clearing, the context yields no image patch.
- [ ] T052 [P] [US3] Extend `ComponentOverridesSection.test.tsx`: clearing the Image input submits `image: null` and the diff dialog shows a removal.

### Implementation for User Story 3

- [ ] T053 [US3] Make the T051 and T052 cases pass with any fixes needed in `inputs.py`, `deployment-input.ts`, or `ComponentOverridesSection.tsx` (most clearing behaviour comes from full replacement and per-render patch regeneration).
- [ ] T054 [US3] Extend `test_override_then_clear` in `backend/tests/e2e/test_deployment_image_override.py` with the clear half: `set_component_image(server, None)`, wait, assert the `simple-app` container image is back to `simple-app:0.1.0` and the read surface lists no override. Run to a pass with `--pdb`.

**Checkpoint**: US1 and US3 together match brief test 1 (P1 + P3).

---

## Phase 6: User Story 4 - Mistakes fail loudly, never silently (Priority: P3)

**Goal**: Invalid references, overrides on containerless components, and misnamed component containers are caught with typed errors naming the component; Styrmin never adds a container or falls back to the chart image.

**Independent Test**: Mutation error tests plus E2E test 3 (misnamed-container driver, `api_only`).

### Tests for User Story 4

- [ ] T055 [P] [US4] Extend `backend/tests/functional/graphql/test_image_overrides_propagation.py` with error cases on `deploy` and `updateDeployment`: unknown component → `UNKNOWN_COMPONENT_IMAGE_OVERRIDE`; each `INVALID_IMAGE_REFERENCE` reason (grammar, missing tag or digest, template expression, after substitution at the current version); containerless add or change → `COMPONENT_CONTAINER_NOT_DECLARED` with `override: "image"`; containerless removal and unchanged re-submission accepted; no task created on any rejection.
- [ ] T056 [P] [US4] Extend `backend/tests/unit/test_styrmin_deployment_timer.py`: a HelmRelease whose `Ready=False` condition for the current generation carries the guard key fails the CR (`phase: Failed`, `displayState: Error`, condition reason `ComponentContainerNotFound`, typed message) in phase `CREATING_HELM_RELEASE` **and** in `READY` (stale `HelmReleaseReady=True` from a previous rollout); the key found in a `Released` condition message also matches; a stale generation or a non-guard failure is ignored (today's behaviour).
- [ ] T057 [P] [US4] Extend `ComponentOverridesSection.test.tsx`: invalid references show the inline error and block submission; a component without a container has no Image input, and a stored override there is read-only with a Remove action and "not applied" text.
- [ ] T058 [P] [US4] Extend `backend/tests/functional/graphql/test_image_overrides_propagation.py` with the stranded case: a stored override on a component whose pinned driver version has no container reads back `isApplicable: false` and is absent from the rendered patches (build the context and call the shared builder).

### Implementation for User Story 4

- [ ] T059 [US4] Implement `backend/styrmin_backend/services/image_overrides/validator.py`: `validate_image_override_targets(config, known_names)` (unknown component), `prevalidate_image_overrides(config, *, version)` (grammar and substitution via `validate_reference`).
- [ ] T060 [US4] Wire T059 into `update_deployment` and `deploy_application` in `backend/styrmin_backend/services/deployment.py` before `validate_deployment_config`, next to the container-override checks. Generalize `_validate_component_env_var_containers` into `_validate_component_container_targets(submitted, stored, containers, slots=("env_vars", "image"))`: for `image`, a non-null submitted value different from the stored one on a containerless component raises `ComponentContainerNotDeclaredError(override="image")`. Makes T055 and T058 pass.
- [ ] T061 [US4] Implement `read_helmrelease_guard_failure(namespace, release_reference) -> tuple[str, str] | None` in `backend/styrmin_backend/operator/reconciler.py` (Ready `False` for the current generation: the condition's `observedGeneration`, else `status.lastAttemptedGeneration`, equals `metadata.generation`; guard key in any condition message; `parse_guard_failure`).
- [ ] T062 [US4] In `kopf_styrmin_deployment_timer` in `backend/styrmin_backend/operator/handlers/styrmin_deployment.py`, call T061 at the start of the `CREATING_HELM_RELEASE` branch and before drift detection in `READY`; on a match set `phase: Failed`, `displayState: Error`, the `HelmReleaseReady` condition `False` with reason `ComponentContainerNotFound`, and the `ComponentContainerNotFoundError` message, then return. Makes T056 pass.
- [ ] T063 [US4] In `ComponentOverridesSection.tsx`, for a component without a container show a stored override read-only with a Remove action (sets `image` to `null`) and the "not applied" text, with no input. Makes T057 pass.
- [ ] T064 [US4] Add an E2E helper `publish_misnamed_simple_app_driver()` in `backend/tests/e2e/helpers/drivers.py` (new module; pattern: `_publish_next_driver_version` in `test_driver_version_reselection.py`): clone `simple-app` from the in-cluster git server, set `metadata.name: simple-app-misnamed` and `components.server.container: wrong-name`, push to branch `misnamed-container`, and load it with `ref="misnamed-container"`.
- [ ] T065 [US4] Add `test_misnamed_container_never_added` (`@pytest.mark.api_only(reason="asserts operator status and live workload only; no UI flow")`) to `backend/tests/e2e/test_deployment_image_override.py`: deploy `simple-app-misnamed` at 0.1.0 (no override, so it reaches Running), set a `server` image override through the SDK, then wait (≤ 2 timer intervals plus the Flux reconcile) for the deployment's status to fail with a message naming `server` and `wrong-name`; assert the live `styrmin-simple-app` Deployment still has exactly one container, `simple-app`. Run to a pass with `--pdb`.

**Checkpoint**: all four stories pass their independent tests.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (Constitution §VII), changelog, regeneration, and full verification.

- [ ] T066 [P] Write `dev/adr/0058-image-overrides-and-component-container-guard.md` per research D-013: decision (token, guard, shared env guard, operator surfacing, upgrade re-validation, `get_component_images` ordering); consequences (component container moves to index 0 for image-only components, rollback needs overrides cleared, the apply race, failures visible within one or two timer intervals); alternatives (research D-001, D-004, D-005); follow-ups (Flux `replacements`, registry mirror, pull secrets, generic HelmRelease failure surfacing, target references in the upgrade dialog). Add a "Narrowed by ADR-058" note to `dev/adr/0057-post-render-component-overrides.md`.
- [ ] T067 [P] Write `docs/docs/concepts-and-architecture/image-overrides.md` (user page per the plan: set and clear through UI, CLI, SDK; token vs pin; upgrade warning; guard failure message; pull failures in the Pods tab; unique tags or digests for rebuilt images; admission policies for registry allow-lists; clear before a platform rollback; v1 limits: no registry mirror, no pull secrets, no partial overrides). Link it from `docs/docs/concepts-and-architecture/index.md`.
- [ ] T068 [P] Update `docs/docs/reference/styrminctl.md` ("Manifest `spec.config` shape": `components[].image` example; the pinned warning; the override + version race).
- [ ] T069 [P] Update `docs/docs/drivers/creating-a-driver.md` (the component container also receives image overrides; a wrong name fails the reconcile with `COMPONENT_CONTAINER_NOT_FOUND` for env vars and images; Styrmin never adds a container; the component container moves to index 0 once an override applies), `docs/docs/drivers/context.md` (`components[<name>].image_override` is read-only context), and `docs/docs/concepts-and-architecture/hooks-and-actions.md` (`get_component_images` returns the component container's image first).
- [ ] T070 [P] Update `docs/docs/concepts-and-architecture/glossary.md` (Image override) and review `CONTEXT.md`'s drafted entries (Image override, Component container, Component overrides) against the final behaviour, including `COMPONENT_CONTAINER_NOT_FOUND`.
- [ ] T071 [P] Update `dev/knowledge/backend/deployment-env-vars.md` (shared guard, `build_component_container_patches`, operator surfacing) and `dev/knowledge/backend/hooks-and-actions.md` (`get_component_images` ordering, in-repo upgrade actions).
- [ ] T072 [P] Add towncrier fragments: `changelog/20.added.md` (per-component image overrides with `{{ app.version }}`; UI, CLI, SDK) and `changelog/20.changed.md` (`get_component_images` returns the component container's image first; a misnamed component container now fails with `COMPONENT_CONTAINER_NOT_FOUND` instead of an image-less container rejection; clear image overrides before rolling back below this release). Follow `dev/guidelines/changelog.md`.
- [ ] T073 Re-run `uv run styrmin export graphql-schema schema.graphql`, `uv run invoke validate-graphql`, and `uv run invoke generate`; confirm no diff remains.
- [ ] T074 Run `uv run invoke format lint` and `cd frontend && pnpm lint && pnpm test`; fix findings.
- [ ] T075 Run `uv run invoke test`, `uv run pytest backend/tests/integration/test_component_container_kustomize.py -v`, `uv run pytest python_sdk/tests cli/tests -v`, and the existing env-var and container-override E2E modules (`test_deployment_env_vars.py`, `test_deployment_container_overrides.py`) to confirm the shared guard did not regress them.
- [ ] T076 Run the whole `backend/tests/e2e/test_deployment_image_override.py` module (both entrypoints) to a pass with `sleep infinity | uv run pytest … -v -s --pdb` and record the result.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: depends on Setup; blocks every story.
- **US1 (Phase 3)**: depends on Foundational. MVP.
- **US2 (Phase 4)**: depends on Foundational and on T025–T029 (GraphQL surface and codegen) and T034–T035 (E2E harness) from US1.
- **US3 (Phase 5)**: depends on US1 (extends its tests and E2E test).
- **US4 (Phase 6)**: depends on Foundational; its frontend task (T063) touches the file US1's T032 changes, so run it after T032; T065 depends on T034–T036's module.
- **Polish (Phase 7)**: after the stories it documents; T073–T076 last.

### Within Each Phase

- Tests first (they must fail), then implementation.
- `inputs.py` → `model.py` → schema export → SDK/frontend codegen.
- Backend validation before the E2E tests that rely on it.

### Parallel Opportunities

- Phase 2 tests T003–T009 are all [P] (different files).
- T010, T012, T015 can run in parallel once tests exist; T011 depends on T010; T019 depends on T011, T012, T015, T018; T020 depends on T019.
- US1: T021–T024 in parallel; T030 and T034 in parallel with backend T025–T029.
- US2: T037–T041 in parallel; T044 and T045 in parallel with T042–T043.
- Polish: T066–T072 in parallel.

## Parallel Example: User Story 1

```text
T021 functional propagation test     | T022 section + input mapping tests
T023 summary test                    | T024 image-reference.test.ts
then: T025 → T026 → T027 → T028/T029 (codegen)
in parallel: T030 image-reference.ts, T034 docker-tag fixture
then: T031 → T032 → T033, T035 → T036 (E2E)
```

## Parallel Example: User Story 2

```text
T037 upgrade propagation test | T038 get_component_images test | T039 SDK tests | T040 CLI test | T041 notice test
then: T042 (service) | T043 (primitives) | T044 (driver actions) | T045 (SDK helper)
then: T046 → T047, T048, T049 → T050 (E2E)
```

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 and Phase 2 (the guard is part of the foundation: no override ever reaches a pod without it).
2. Phase 3: set an image through API and UI; E2E test 1's set half passes.
3. Stop and validate: SC-001 and SC-006 hold.

### Incremental Delivery

1. Foundation → US1 (MVP, demo the custom build).
2. US2 → upgrades follow the token; pinned warning; action Jobs.
3. US3 → clearing (brief test 1 complete).
4. US4 → typed failures and the operator guard surfacing (brief test 3).
5. Polish → ADR, docs, changelog, full verification.

### Notes

- Every E2E run uses `--pdb` with the `sleep infinity |` prefix in non-interactive shells (AGENTS.md).
- No Alembic revision: `image` lives in the existing `Deployment.config` JSON.
- Never set `resources.limits` in Helm charts (unchanged by this feature).
