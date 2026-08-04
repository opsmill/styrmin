# Implementation Plan: Declarative Deployment Management via YAML Manifests

**Branch**: `009-deployments-apply` | **Date**: 2026-05-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-deployments-apply/spec.md`

## Summary

Add `styrminctl deployments apply` — a declarative upsert command that reads one or more YAML manifests (or a directory of them, or a multi-document file), validates them with a Pydantic schema, resolves overrides (CLI flag > env var > manifest field), then for each manifest performs a create-or-update against the Styrmin platform.

The orchestration is **client-side** in the SDK: a new `DeploymentResource.apply()` method (1) resolves the target environment by name + optional cluster, (2) looks up an existing deployment by `(name, environmentId)` via a new GraphQL query, (3) creates if absent or updates config/parameters and version-upgrades if present, (4) errors on driver-mismatch. The CLI is a thin wrapper that loads files, applies overrides, calls `apply()` per manifest, prints per-deployment status lines and a summary, and exits non-zero if any manifest failed.

A single new backend GraphQL query — `deployment(name, environmentId)` — is required so the SDK can decide create-vs-update without first scanning every deployment in the environment. The query and its propagation test are the only backend-side changes.

## Technical Context

**Language/Version**: Python 3.11+ (backend, SDK, CLI). Manifests are YAML on disk, parsed to typed Python.
**Primary Dependencies**:
- Backend: Strawberry GraphQL, SQLModel, Pydantic, Prefect (no new deps).
- SDK: Pydantic, `ariadne-codegen`-generated query bindings.
- CLI: Cyclopts (existing), `pydantic_settings` for env vars.
- **PyYAML** (already in `uv.lock` transitively via Prefect): promoted to a **direct** dep of both `python_sdk/pyproject.toml` (because `DeploymentResource.apply_files()` parses YAML in the SDK so non-CLI callers can use it) and `cli/pyproject.toml`.
**Storage**: PostgreSQL (existing). No schema migrations — `(name, environmentId)` lookup uses an existing logical key already enforced by the `unique_deployment_name_per_environment` constraint.
**Testing**: pytest (backend service tests, GraphQL propagation tests, SDK unit tests, CLI unit tests, E2E tests under `backend/tests/e2e/`). E2E will be marked `@pytest.mark.api_only` per AGENTS.md heuristic — `apply` has no UI flow.
**Target Platform**: Linux/macOS dev + Linux CI. CLI is a Python entry point published in `cli/`.
**Project Type**: Three-tier — backend (GraphQL schema/services) + SDK (Python client) + CLI (Cyclopts subcommand).
**Performance Goals**: A 50-manifest batch should complete validation + lookup + create/update submission in well under one minute on a developer laptop against a local cluster. Batch processing is sequential (no parallelism in v1).
**Constraints**:
- Validation MUST run before any backend call so typos do not produce partial state.
- Continue-on-error is mandatory: one bad manifest in a batch must not block others.
- Fire-and-forget by default; `--wait` blocks until terminal state per the existing `backups create --wait` and `deployments create --wait` pattern.
- Idempotent in observable behaviour: re-applying the same manifest converges to the same state.
**Scale/Scope**: Target real-world batches of single-digit-to-low-tens of manifests in CI; no parallelism or streaming output design in v1.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan satisfies it |
|---|---|
| **I. Declarative State Reconciliation** | The whole feature exists to make declarative reconciliation user-driven (manifest-as-source-of-truth). The upsert relies on the existing reconciliation engine — `apply` only emits create/update/update-version operations and lets the Prefect-driven workflows reconcile to `RUNNING`. Idempotency is part of the spec's success criteria. ✅ |
| **II. Driver-Based Deployment** | `apply` does not introduce any new deployment behaviour outside drivers. It validates that the manifest's driver matches the existing deployment's driver and refuses driver-change updates (drivers are versioned and self-contained — changing them out from under a deployment would violate this principle). ✅ |
| **III. Layered Architecture** | Backend: the new `deployment(name, environmentId)` query field calls a new service-layer function `get_deployment_by_name(name, environment_id, uow)` which dispatches through the existing repository layer. No cross-layer calls. SDK: only consumes the GraphQL transport. CLI: only consumes the SDK. ✅ |
| **IV. Type Safety and Typed Errors** | Manifest validation uses Pydantic models with `extra="forbid"`. The SDK's `apply()` raises typed exceptions (`DriverMismatchError`, `EnvironmentAmbiguityError`, `ManifestValidationError` — subclasses of an existing or new SDK base exception) instead of returning union error types. The backend service raises `ServiceError`-derived exceptions consistent with the existing `get_deployment` family. ✅ |
| **V. Test-First Development** | Each phase ships tests. Specifically: (a) GraphQL propagation test for `deployment(name, environmentId)` is mandatory under §V and §V's NON-NEGOTIABLE clause; (b) SDK unit tests for `apply()` covering create/update/version-upgrade/driver-mismatch/ambiguity paths; (c) CLI unit tests for batch loading, override precedence, `--name` rejection, summary output, exit code; (d) one E2E test under `backend/tests/e2e/` covering apply→re-apply→update→batch-with-failure, marked `api_only`. ✅ |
| **VI. Format and Lint Before Commit** | Pre-commit hooks (already installed) run `ruff format`, `ruff check`, `ty`, schema regen, query regen. No bypasses. ✅ |
| **Governance — GraphQL schema modifications** | The PRD explicitly enumerates the new `deployment(name, environmentId)` query and the rationale (lookup by natural identity is required for client-side upsert). User has authorised the schema change via the PRD itself; no further gate needed. ✅ |
| **Governance — New dependencies** | `PyYAML` is already a transitive dep but will be promoted to a direct dep of **both** `python_sdk/` and `cli/` (so non-CLI tooling can call `DeploymentResource.apply_files()` directly without re-implementing YAML parsing). This is the only new direct dep. PyYAML is industry-standard, MIT-licensed, well-maintained — no alternatives discussion needed. ✅ |

**Verdict**: All gates pass. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/009-deployments-apply/
├── plan.md              # this file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── manifest-schema.md   # YAML manifest contract (apiVersion, kind, fields)
│   ├── cli-apply.md         # CLI surface (flags, env vars, output, exit codes)
│   ├── sdk-apply.md         # SDK DeploymentResource.apply() contract
│   └── graphql-deployment-by-name.md  # new query contract
├── checklists/
│   └── requirements.md  # Phase 0 (Specify) output
└── tasks.md             # Phase 2 (/speckit-tasks) output
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── api/
│   │   └── schema/
│   │       └── query.py                     # +deployment(name, environmentId) field
│   └── services/
│       └── deployment.py                    # +get_deployment_by_name(name, env_id, uow)
└── tests/
    ├── functional/graphql/
    │   └── test_deployment.py               # +propagation tests for the new query
    └── e2e/
        └── test_deployments_apply.py        # NEW — apply create→update→batch-failure flow

python_sdk/
├── src/styrmin_sdk/
│   ├── graphql/
│   │   └── get_deployment_by_name.graphql   # NEW — query
│   ├── models/
│   │   └── deployment_manifest.py           # NEW — Pydantic model for the manifest
│   └── resources/
│       └── deployments.py                   # +apply(), +get_by_name(), exception types
└── tests/
    └── test_deployments.py                  # +unit tests for apply() paths

python_sdk/pyproject.toml                   # +PyYAML as a direct dep (apply_files parses YAML)

cli/
├── src/styrminctl/
│   └── commands/
│       └── deployments.py                   # +apply subcommand
├── tests/
│   └── test_deployments.py                  # +unit tests for the apply CLI surface
└── pyproject.toml                           # +PyYAML as a direct dep

schema.graphql                               # regenerated to include deployment(name, environmentId)
```

**Structure Decision**: Three-tier layout per the existing repo (`backend/` + `python_sdk/` + `cli/`). The feature's user-facing entry point is the CLI; the upsert orchestration lives in the SDK; the backend exposes only one new query field. No new top-level packages, no new test directories.

## Complexity Tracking

> No Constitution Check violations. Section intentionally empty.
