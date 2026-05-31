---
description: "Task list for 009-deployments-apply"
---

# Tasks: Declarative Deployment Management via YAML Manifests

**Input**: Design documents from `/specs/009-deployments-apply/`
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are MANDATORY for this feature per Constitution §V. Specifically:
- Every new GraphQL query/argument requires a propagation test (NON-NEGOTIABLE).
- Every new feature requires an E2E test that is executed and observed to pass.
- SDK and CLI changes require unit tests.

**Organization**: Tasks are grouped by user story (P1, P2, P3 from spec.md) to enable independent implementation and testing. The new GraphQL lookup query is shared by US1 (apply orchestration) and US5 (public SDK lookup) and is therefore promoted to the Foundational phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Include exact file paths in descriptions

## Path Conventions

Three-tier monorepo layout:
- Backend: `backend/styrmin_backend/`, tests under `backend/tests/`
- SDK: `python_sdk/src/styrmin_sdk/`, tests under `python_sdk/tests/`
- CLI: `cli/src/styrminctl/`, tests under `cli/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make PyYAML a direct dep of the SDK and CLI, set up the new module layouts. No code logic.

- [x] T001 Add `pyyaml` as a direct dependency in `python_sdk/pyproject.toml` (matches the version pinned by Prefect; do not bump). Run `uv sync` to lock.
- [x] T002 Add `pyyaml` as a direct dependency in `cli/pyproject.toml` (same version as SDK). Run `uv sync` to lock.
- [x] T003 [P] Create empty module file `python_sdk/src/styrmin_sdk/models/deployment_manifest.py` and re-export the future `DeploymentManifest`, `ResolvedManifest`, `ApplyOverrides`, `ApplyOutcome` symbols from `python_sdk/src/styrmin_sdk/models/__init__.py` (placeholder; symbols added in later tasks).
- [x] T004 [P] Create empty SDK exception subclasses file at `python_sdk/src/styrmin_sdk/exceptions.py` additions: append `ApplyError`, `ManifestValidationError`, `MissingRequiredFieldError`, `EnvironmentAmbiguityError`, `DriverMismatchError`, `BatchNameConflictError` — each extending `StyrminError`. Re-export from `python_sdk/src/styrmin_sdk/__init__.py`.

**Checkpoint**: Dependencies and exception types are in place; subsequent tasks can import them.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the new GraphQL query `deployment(name, environmentId)` and the SDK lookup wrapper. This phase satisfies US5's user-visible behaviour AND unblocks US1's create-vs-update logic. **No US1+ work can begin until this phase is complete.**

⚠️ **CRITICAL**: Phase 2 is non-skippable for US1. Its propagation test is constitution-mandated.

### Backend GraphQL — query and service

- [x] T005 Add a new service-layer function `get_deployment_by_name(*, name, environment_id, uow) -> Deployment | None` in `backend/styrmin_backend/services/deployment.py`. Call the existing repository layer (`uow.deployments.find_one_by(name=..., environment_id=...)` or equivalent), filter out `internal=True` and soft-deleted rows, return `None` on miss.
- [x] T006 If the repository in `backend/styrmin_backend/repositories/deployment.py` does not already expose a `find_one_by_name_and_environment(name, environment_id)` method, add it; reuse the existing `unique_deployment_name_per_environment`-backed index — no new index migration.
- [x] T007 Extend the `deployment(...)` field resolver in `backend/styrmin_backend/api/schema/query.py` to accept three optional arguments (`deploymentId: UUID | None`, `name: str | None`, `environmentId: UUID | None`). At runtime, enforce that EITHER `deploymentId` is set alone OR `name` AND `environmentId` are set together. On invalid combination, raise a `ServiceError` with code `INVALID_DEPLOYMENT_LOOKUP_ARGS` (define the code in `backend/styrmin_backend/services/errors.py` or wherever existing service errors live). Dispatch to `get_deployment(...)` or `get_deployment_by_name(...)` accordingly. Preserve the existing `internal` hidden-guard.
- [x] T008 Regenerate `schema.graphql` at the repo root via `uv run styrmin export graphql-schema schema.graphql`. Commit the regenerated file alongside the resolver change.

### Backend tests — propagation (NON-NEGOTIABLE per Constitution §V)

- [x] T009 [P] Add propagation test cases to `backend/tests/functional/graphql/test_deployment.py` covering the new lookup shape:
  - case 1: `(name, environmentId)` finds a real, non-internal, non-deleted deployment;
  - case 2: `(name, environmentId)` returns null when no row matches;
  - case 3: `(name, environmentId)` returns null when only an `internal=True` row matches;
  - case 4: `(name, environmentId)` returns null when only a soft-deleted (`deletedAt IS NOT NULL`) row matches;
  - case 5: passing both `deploymentId` and `name` raises a structured GraphQL error with `extensions.code == "INVALID_DEPLOYMENT_LOOKUP_ARGS"`.
  Each test loads its operation from `backend/tests/functional/graphql/operations/get_deployment_by_name.graphql` (create that file with a query named `GetDeploymentByName`).

### SDK — public lookup wrapper (US5 user-visible surface)

- [x] T010 [P] Create `python_sdk/src/styrmin_sdk/graphql/get_deployment_by_name.graphql` containing the named operation `query GetDeploymentByName($name: String!, $environmentId: UUID!) { deployment(name: $name, environmentId: $environmentId) { ...same selection set as get_deployment.graphql... } }`.
- [x] T011 Run `uv run invoke validate-graphql` to confirm the new query parses against the regenerated schema.
- [x] T012 Run `uv run invoke generate` to regenerate SDK Pydantic types under `python_sdk/src/styrmin_sdk/graphql/_generated/`. Commit the generated files.
- [x] T013 Add `async def get_by_name(self, name: str, *, environment_id: str | UUID) -> GetDeploymentByNameDeployment | None` to `DeploymentResource` in `python_sdk/src/styrmin_sdk/resources/deployments.py`. Use `load_query("get_deployment_by_name")`. Return `None` cleanly on null.

### SDK tests — get_by_name unit tests

- [x] T014 [P] [US5] Add unit tests for `DeploymentResource.get_by_name()` in `python_sdk/tests/test_deployments.py` covering: returns the deployment on hit; returns `None` on miss; returns `None` on internal-hidden response. Mock the GraphQL transport.

**Checkpoint**: The new lookup query exists, is propagation-tested, and is exposed via the SDK. US5 (P3) is functionally complete. US1 can now branch on existence.

---

## Phase 3: User Story 1 — Apply a single manifest (Priority: P1) 🎯 MVP

**Goal**: A platform engineer authors one YAML file and runs `styrminctl deployments apply -f deployment.yaml` to create-or-update a deployment.

**Independent Test**: Author a manifest, run `apply`, and verify a deployment is created. Modify the manifest's config and re-run; verify the same deployment is updated (not duplicated). Modify only the version and re-run; verify the deployment's version is upgraded. Driver-mismatch on update fails clearly.

### Manifest model and validation

- [x] T015 [US1] Implement the `DeploymentManifest` Pydantic model in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py`, per `contracts/manifest-schema.md`: literal `apiVersion="styrmin/v1"`, literal `kind="Deployment"`, `metadata.name: str | None`, `spec.driver: str` (required), `spec.version`, `spec.environment`, `spec.cluster`, `spec.config: dict[str, JsonValue] = {}`, `spec.parameters: dict[str, JsonValue] = {}`. Set `model_config = ConfigDict(extra="forbid")` at every nested level.
- [x] T016 [US1] Implement the `ResolvedManifest` Pydantic model in the same file. After override resolution: `name`, `driver`, `version`, `environment` are required; `cluster: str | None`; `config`, `parameters` defaulted to `{}`; `source_path: pathlib.Path` for path-prefixed errors.
- [x] T017 [US1] Implement the `ApplyOverrides` Pydantic model (`name`, `version`, `environment`, `cluster`, all `str | None = None`) and the `ApplyOutcome` Pydantic model (`name`, `action: Literal["created","updated","failed"]`, `deployment_id: UUID | None`, `task_id: UUID | None`, `failure_reason: str | None`). Place in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py`.

### SDK — `apply()` orchestration (single manifest)

- [x] T018 [US1] Implement `DeploymentResource.apply(manifest: ResolvedManifest) -> ApplyOutcome` in `python_sdk/src/styrmin_sdk/resources/deployments.py`. Behaviour per `contracts/sdk-apply.md`:
  1. Resolve env+cluster to `environment_id` (reuse the existing helper used by `create()`); on multi-cluster ambiguity raise `EnvironmentAmbiguityError` listing candidate clusters.
  2. Look up via `self.get_by_name(name=manifest.name, environment_id=environment_id)`.
  3. If not found: call existing `self.create(...)`; return `ApplyOutcome(action="created", ...)`.
  4. If found: validate `existing.application_driver_name == manifest.driver`; raise `DriverMismatchError` otherwise. Call `self.update(...)` for config/parameters. If `existing.application_version != manifest.version`, also call `self.update_version(...)`. Return `ApplyOutcome(action="updated", ...)`.
- [x] T019 [US1] In `apply()`, handle the duplicate-name backend race per research.md D2: if `self.create()` raises a duplicate-name error, re-run `self.get_by_name()` once and switch to the update path. Otherwise propagate the error.

### SDK tests — apply() unit tests

- [x] T020 [P] [US1] Add unit tests for `DeploymentResource.apply()` in `python_sdk/tests/test_deployments.py` covering: create path (lookup returns None → create called with manifest fields, outcome = "created"); update-config-only path (lookup returns existing with same version → only `update_deployment` called); update-version-only path (config equal → only `update_deployment_version` called); update-both path (asserting `update_deployment` called BEFORE `update_deployment_version` per research.md D8); driver-mismatch raises `DriverMismatchError`; environment ambiguity raises `EnvironmentAmbiguityError`; duplicate-name race triggers re-lookup and update path.

### CLI — single-file apply

- [x] T021 [US1] Add the `apply` command to `cli/src/styrminctl/commands/deployments.py` with Cyclopts `@deployments_app.command`, accepting `-f` (Path, single value for now), `--name`, `--version`, `--environment`, `--cluster`, `--wait` (boolean, plumbed in Phase 6). Read env vars (`STYRMIN_NAME`, `STYRMIN_VERSION`, `STYRMIN_ENVIRONMENT`, `STYRMIN_CLUSTER`) inside the command (not from a global Settings) to keep override precedence local. Resolve `metadata.name` / `spec.version` / `spec.environment` / `spec.cluster` per CLI > env > manifest precedence; raise `MissingRequiredFieldError` for unresolved required fields.
- [x] T022 [US1] In `apply`, parse the file with `yaml.safe_load_all(...)` (multi-doc support reused later in US2 — but for US1, accept a file with one document; multiple documents produces one outcome each). Build `DeploymentManifest` for each doc, then `ResolvedManifest`, then call `await client.deployments.apply(resolved)`.
- [x] T023 [US1] Print one status line per outcome in processing order: `created <name>` / `updated <name>` / `failed <name>: <reason>`. After all outcomes, print the summary line `<N> created, <M> updated, <K> failed`. Exit non-zero if any outcome failed (for US1 this is "any" since one manifest only). Use the existing `styrmin_error_handler()` helper in `cli/src/styrminctl/output.py` so any uncaught `StyrminError` (including the new subclasses) becomes a clean exit.
- [x] T024 [US1] Update the command's `--help` docstring per `contracts/cli-apply.md` "Help text" requirements: state that `config` and `parameters` are FULLY REPLACED, not merged; reference the manifest schema's `apiVersion: styrmin/v1`; show one example invocation; mention override precedence.

### CLI tests — single-file apply

- [x] T025 [P] [US1] Add unit tests in `cli/tests/test_deployments.py` for the single-file path: success creates → outcome line + summary line + exit 0; success updates → same; validation error (extra field) → exit 1, no backend call; driver mismatch → exit 1, "failed <name>: driver mismatch ..." line; missing required field (no name in manifest, no flag, no env) → exit 1 before any client call. Use Cyclopts's invocation harness and assert via `capsys` and `pytest.raises(SystemExit)` per the existing test patterns in this file.

### E2E — create→update flow (api_only)

- [x] T026 [US1] Add `backend/tests/e2e/test_deployments_apply.py` with `@pytest.mark.api_only(reason="apply has no UI flow; api/sdk and ui variants would re-run identical SDK calls")` and `@pytest.mark.ci`. Scenario: write a temp manifest file, invoke `client.deployments.apply_files([path])` (placeholder until US2 lands `apply_files`; for US1, call `apply(resolved_manifest)` directly), assert the deployment is created and reaches `RUNNING`. Then re-author the manifest with a changed config and call again, assert `action == "updated"`, assert config matches in the cluster (read back via SDK).

**Checkpoint**: User Story 1 is fully functional and testable. A user can do `apply -f deployment.yaml` end-to-end. The MVP works.

---

## Phase 4: User Story 2 — Batch with continue-on-error (Priority: P2)

**Goal**: `apply` accepts directories, multiple `-f` flags, multi-document YAML, continues past per-manifest failures, and reports a clean summary with non-zero exit code on any failure.

**Independent Test**: Place three valid manifests and one invalid manifest (driver mismatch) in a directory; run `apply -f ./manifests/`. Verify three valid ones are created/updated, the invalid one is reported as failed, summary reports `N created, M updated, K failed`, exit code is non-zero.

### SDK — `apply_files()` and batch loader

- [x] T027 [US2] Implement `DeploymentResource.apply_files(paths: Sequence[Path | str], *, overrides: ApplyOverrides | None = None) -> list[ApplyOutcome]` in `python_sdk/src/styrmin_sdk/resources/deployments.py` per `contracts/sdk-apply.md`. Path expansion: file → one entry; directory → sorted immediate `.yaml`/`.yml` files; missing path → raise `FileNotFoundError`. Empty result (e.g. dir with no yaml files) → raise an `ApplyError` with the message `no manifests found in <path>`.
- [x] T028 [US2] In `apply_files()`, parse each file with `yaml.safe_load_all` for multi-document support. Validate each document via `DeploymentManifest`, resolve overrides into `ResolvedManifest`, dispatch to `apply()`. On any per-manifest exception, append `ApplyOutcome(action="failed", failure_reason=str(exc))` and continue. Annotate the failure_reason with the manifest's `source_path` prefix (e.g. `"manifest a.yaml: driver mismatch ..."`). Reject `overrides.name` set with more than one resolved manifest by raising `BatchNameConflictError` BEFORE any per-manifest dispatch.

### SDK tests — apply_files() unit tests

- [x] T029 [P] [US2] Add unit tests in `python_sdk/tests/test_deployments.py` covering: single file with one doc; single file with multiple `---`-separated docs; multiple `-f` paths combined; directory with sorted file order; directory with mixed valid/invalid manifests (continue-on-error); empty directory raises `ApplyError("no manifests found")`; missing path raises `FileNotFoundError`; `--name` with multi-doc raises `BatchNameConflictError` before any dispatch.

### CLI — wire `apply_files` and update output

- [x] T030 [US2] Update the CLI `apply` command in `cli/src/styrminctl/commands/deployments.py` to delegate to `client.deployments.apply_files([...])` instead of single-file `apply()`. Pass `ApplyOverrides(name=..., version=..., environment=..., cluster=...)` from the resolved CLI flag/env values.
- [x] T031 [US2] Update output to handle the list of outcomes per `contracts/cli-apply.md` "Without --wait" section: stream one status line per outcome in the order returned. After all outcomes, print the single summary line. Exit code is 1 if any outcome's action is "failed", else 0.
- [x] T032 [US2] Surface the `BatchNameConflictError` and `no manifests found in <path>` messages with the standard "failed: <reason>" CLI prefix and exit 1 before any per-manifest dispatch.

### CLI tests — batch behaviour

- [x] T033 [P] [US2] Add unit tests in `cli/tests/test_deployments.py` for: directory with three valid + one invalid → three "created/updated" lines, one "failed" line, summary `N created, M updated, K failed`, exit 1; multi-doc YAML one-doc-invalid → other docs proceed; multi `-f` flags; `--name` with two manifests → exit 1 before any client call with the expected message; empty directory → exit 1 with "no manifests found".

### E2E — extend with batch+failure scenario

- [x] T034 [US2] Extend `backend/tests/e2e/test_deployments_apply.py`: add a scenario that writes three manifests to a temp directory (two valid, one with a driver that does not match an existing deployment from a prior step), invokes `apply_files([dir])`, asserts the per-outcome shape (two `created`/`updated`, one `failed`), the count summary, and the deployment-side state in the cluster.

**Checkpoint**: User Story 2 complete. Batches work, failures are isolated, exit codes work for CI.

---

## Phase 5: User Story 3 — Override precedence (Priority: P2)

**Goal**: CLI flags override env vars override manifest fields. Required-value resolution fails before any backend call. `--name` is forbidden in batch mode.

**Independent Test**: Author a manifest with `spec.version: 1.2.3`. Run `apply --version 1.4.0`; verify deployment uses `1.4.0`. Set `STYRMIN_VERSION=1.5.0`, run `apply` (no flag); deploys at `1.5.0`. Both set → flag wins.

### Resolution helper and required-field validation

- [x] T035 [P] [US3] Extract a small pure helper `resolve_overrides(manifest: DeploymentManifest, overrides: ApplyOverrides, env: Mapping[str, str]) -> ResolvedManifest` in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py` (or a sibling module `_resolve.py` if cleaner). Precedence: overrides.X > env[STYRMIN_X] > manifest field. Raise `MissingRequiredFieldError` if any of `name`, `driver`, `version`, `environment` cannot be resolved. The error message must list all three sources (manifest, env var, CLI flag) so the user can fix it.
- [x] T036 [US3] Update `DeploymentResource.apply_files()` (T028) to call `resolve_overrides(...)` for each loaded manifest, passing `os.environ` as the `env` argument so env-var precedence is consistent with how the CLI sees the same environment.

### Override precedence unit tests

- [x] T037 [P] [US3] Add unit tests in `python_sdk/tests/test_deployments.py` (or a dedicated `test_resolve_overrides.py`) for `resolve_overrides()`: every combination of (manifest absent / env absent / flag absent) → flag-wins precedence is observable; missing required fields raise `MissingRequiredFieldError`; cluster is never required; manifest-only-name with a `--name` flag means flag wins.

### CLI — wire env vars and required-field error path

- [x] T038 [US3] In the CLI `apply` command, build `ApplyOverrides` from CLI flags only (env-var resolution is now done inside the SDK via `resolve_overrides`). Verify (in code review or via test) that env vars are NOT also read at the CLI layer to avoid double-application.
- [x] T039 [US3] Add unit tests in `cli/tests/test_deployments.py` simulating env vars via `monkeypatch.setenv`: env-var-only resolution; CLI flag overrides env; missing required field message clearly names the field and the three sources.

**Checkpoint**: User Story 3 complete. Pipelines can promote the same manifests across environments via env-var or flag overrides.

---

## Phase 6: User Story 4 — `--wait` blocks until terminal state (Priority: P3)

**Goal**: With `--wait`, the command blocks until each successfully-submitted deployment reaches a terminal state (`RUNNING` or failure). Output uses the two-line `submitted <name>` → `running <name>` / `failed <name>: <reason>` model. Default behaviour (no flag) is unchanged.

**Independent Test**: Apply a manifest without `--wait`; verify the command exits within a few seconds. Apply with `--wait`; verify it does not exit until reconciliation completes; on failure, the failed-line is emitted and the exit code is non-zero.

### SDK — wait support in `apply` and `apply_files`

- [x] T040 [US4] Extend `DeploymentResource.apply()` and `apply_files()` to accept a `wait: bool = False` keyword arg. When `wait=True`, after submission, poll `client.deployments.get(deployment_id)` (using the EXISTING `get` query) until `applicationInstance.status` reaches a terminal value (`RUNNING` or one of the documented failure states). Reuse the timeout convention used by `client.deployments.create(..., wait=True)` if it exists; otherwise lift the same constant from there into a shared module and reuse. Update `ApplyOutcome` after waiting: a deployment that submitted successfully but failed during reconciliation has `action="failed"` and `failure_reason="wait timeout"` or the reported failure reason.
- [x] T041 [US4] Update `apply_files()` to emit submitted/terminal events through an injectable callback (so the CLI can stream the two-line format). Default callback prints nothing; the CLI installs one that streams. Outcome list returned at the end is unchanged.

### SDK tests — wait behaviour

- [x] T042 [P] [US4] Add unit tests in `python_sdk/tests/test_deployments.py` mocking the `get` query to return progressively settled statuses: terminal `RUNNING` → action="updated", no failure; terminal failure status → action="failed" with the reason; mock a timeout → action="failed" with `failure_reason="wait timeout"`. Verify the callback is invoked with `submitted` then `terminal` events in order.

### CLI — `--wait` flag and two-line streaming

- [x] T043 [US4] In the CLI `apply` command, plumb `--wait` to `apply_files(..., wait=True)`. Install a callback that emits, per outcome: `submitted <name>` on submission, then `running <name>` or `failed <name>: <reason>` on terminal state. Without `--wait`, output is unchanged from US2 (single line per outcome). The post-batch summary line uses POST-WAIT counts.
- [x] T044 [US4] On a partially-updated deployment (config+parameters succeeded, version-upgrade then failed), the `failed` line MUST be `failed <name>: config/parameters were updated; version upgrade failed: <error>` per `contracts/cli-apply.md`. Implement and test.

### CLI tests — wait output

- [x] T045 [P] [US4] Add unit tests in `cli/tests/test_deployments.py` for `--wait`: terminal RUNNING → "submitted X" then "running X" lines, exit 0; terminal failure → "submitted X" then "failed X: ..." lines, exit 1; partial-update failure → message format matches the contract; timeout → "failed X: wait timeout" line, exit 1.

### E2E — extend with `--wait`

- [x] T046 [US4] Extend `backend/tests/e2e/test_deployments_apply.py` with a `--wait`-equivalent scenario: invoke `apply_files([path], wait=True)`, assert the command does not return until `applicationInstance.status == RUNNING`, assert the outcome's `action == "updated"`. Pair with one negative scenario: a manifest deliberately constructed to fail reconciliation (e.g., bad parameters), assert `action == "failed"`, assert the failure_reason is non-empty.

**Checkpoint**: User Story 4 complete. CI pipelines that need synchronous deployment behaviour have a clean opt-in.

---

## Phase 7: User Story 5 — SDK `get_by_name` public surface (Priority: P3)

**Goal**: External tooling (other CLIs, scripts, agents) can resolve a deployment by `(name, environment)` through the platform's SDK without pre-knowing internal IDs.

**Independent Test**: Through the SDK, look up a deployment by `(name, environmentId)` and verify it returns the matching deployment. Look up a non-existent name; verify the lookup returns null. Look up an internal deployment; verify it is hidden.

> Most of US5 is already delivered in Phase 2 (T010–T014). This phase finalises the public-API exposure.

- [x] T047 [P] [US5] Re-export `get_by_name` and the `GetDeploymentByNameDeployment` return type from `python_sdk/src/styrmin_sdk/__init__.py` so external callers can `from styrmin_sdk import GetDeploymentByNameDeployment`. Verify by running `uv run pytest python_sdk/tests/test_deployments.py::test_get_by_name_*`.
- [x] T048 [P] [US5] Add a one-paragraph note + code example to `python_sdk/AGENTS.md` describing the new `get_by_name` lookup, with a link to `specs/009-deployments-apply/contracts/sdk-apply.md`.

**Checkpoint**: User Story 5 complete. SDK consumers can resolve by natural identity.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, hygiene, and final verification.

- [x] T049 [P] Run `uv run invoke format lint` from repo root; fix any violations. Run `pnpm test` is not relevant (no frontend changes), but run `cd frontend && pnpm install` once if `uv run invoke generate` requires it (per AGENTS.md note).
- [x] T050 [P] Run `uv run invoke validate-graphql` from repo root; confirm zero errors.
- [x] T051 [P] Run `uv run invoke test` (backend), `cd python_sdk && uv run pytest`, and `cd cli && uv run pytest`. All test suites pass.
- [x] T052 [P] Run the new E2E `backend/tests/e2e/test_deployments_apply.py` with `--pdb` per AGENTS.md: `sleep infinity | uv run pytest backend/tests/e2e/test_deployments_apply.py -v -s --pdb 2>&1 | tee /tmp/pdb.log`. Confirm passing under both `[api-chromium]` (and skip `[ui-chromium]` since the test is `api_only`).
- [x] T053 [P] Update `dev/guides/` if a new guide entry is warranted (e.g., `dev/guides/declarative-deployments.md` linking to the quickstart). Skip if existing docs already cover it.
- [x] T054 [P] Verify `quickstart.md` examples render cleanly when copy-pasted. Pin a representative snippet block in the CLI's `--help` text if not already done.
- [x] T055 Update `CHANGELOG.md` (or release notes equivalent) with: "Added: declarative deployment management via `styrminctl deployments apply`. New `deployment(name, environmentId)` GraphQL query."
- [x] T056 Run `git diff schema.graphql` to confirm the regenerated schema only added the new argument shape — no unintended changes.
- [x] T057 Add Deployment Identity / Manifest / Apply definitions to CONTEXT.md at repo root

---

## Dependencies & Story Completion Order

```text
Phase 1 (Setup)
  └── Phase 2 (Foundational: GraphQL query + propagation test + SDK get_by_name)
        ├── US1 (single apply) — depends on Phase 2 for create-vs-update branch
        ├── US5 (public lookup) — already 90% delivered in Phase 2; finalises in Phase 7
        └── US1 ──┬──> US2 (batch) — depends on US1's loader and apply()
                   ├──> US3 (overrides) — depends on US2's loader for batch precedence
                   └──> US4 (--wait) — depends on US1 (single) and US2 (batch) for callback wiring
                          └──> Phase 8 (Polish)
```

- US5 finalisation can run in parallel with US1/US2/US3/US4 (Phase 7 is just re-exports + docs).
- US3 and US4 are independent of each other and can be parallelised once US2 is in place.

## Parallel Execution Examples

**Within Phase 2** (after T005–T007 land):
- T009 (propagation test) ‖ T010 (graphql file) — different files
- T014 (SDK unit test) ‖ T013 (SDK method) — sequence-dependent on T012, but both run after T012

**Within Phase 3 (US1)**:
- T015, T016, T017 (Pydantic models in the same file) — sequential (same file).
- T020 (apply unit tests) ‖ T025 (CLI unit tests) ‖ T026 (E2E) — different files.

**Within Phase 4 (US2)**:
- T029 (SDK unit tests) ‖ T033 (CLI unit tests) ‖ T034 (E2E extension) — different files.

**Within Phase 5 (US3)**:
- T037 (SDK unit tests) ‖ T039 (CLI unit tests) — different files.

**Within Phase 8**:
- T049–T054 are all `[P]` — independent verification commands.

## Implementation Strategy

**MVP (US1)**: Phase 1 + Phase 2 + Phase 3 = a working `styrminctl deployments apply -f deployment.yaml` for single files, with create→update→version-upgrade behaviour and full propagation+E2E test coverage. Ship-able as a usable v1 pre-feature.

**Iterate**: Add Phase 4 (batch) → Phase 5 (overrides) → Phase 6 (--wait) → Phase 7 (lookup polish) → Phase 8 (polish). Each phase ships as an independently testable increment and produces a clean Definition-of-Done.

## Test Coverage Summary (Constitution §V)

| Layer | Coverage |
|---|---|
| GraphQL propagation tests (NON-NEGOTIABLE) | T009 — five cases: found, not-found, internal-hidden, soft-deleted, argument-validation |
| SDK unit tests | T014 (get_by_name), T020 (apply paths), T029 (apply_files batch), T037 (resolve_overrides), T042 (--wait) |
| CLI unit tests | T025 (single-file), T033 (batch), T039 (overrides), T045 (--wait) |
| E2E (api_only) | T026 (create→update), T034 (batch+failure), T046 (--wait) — one file, three scenarios |

Every new GraphQL field, argument, and SDK/CLI surface listed in the contracts has a corresponding test task.
