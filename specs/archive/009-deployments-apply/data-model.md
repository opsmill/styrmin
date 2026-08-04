# Data Model: Declarative Deployment Management

**Feature**: 009-deployments-apply
**Phase**: 1 (Design)

## In-scope entities

The feature does **not** introduce any new persisted entities. It introduces one new in-memory Pydantic model (the manifest), one new in-memory result type (the apply outcome), and a new GraphQL query on existing data (`deployment(name, environmentId)`).

The existing persisted shape of `Deployment` is unchanged. The lookup uses the existing logical key `(name, environment_id)` already enforced by the database constraint `unique_deployment_name_per_environment`.

---

## Pydantic: `DeploymentManifest`

Lives in `python_sdk/src/styrmin_sdk/models/deployment_manifest.py` so both the SDK and CLI can consume it. (CLI imports from the SDK to avoid duplication.)

| Field path | Type | Required | Notes |
|---|---|---|---|
| `apiVersion` | `Literal["styrmin/v1"]` | yes | exact-match validation |
| `kind` | `Literal["Deployment"]` | yes | exact-match validation |
| `metadata.name` | `str \| None` | optional | overridable via `--name` / `STYRMIN_NAME`; required at resolve-time |
| `spec.driver` | `str` | yes | format: `"<vendor>/<driver>"` or just `"<driver>"`, validation by length and non-empty |
| `spec.version` | `str` | optional in manifest | overridable via `--version` / `STYRMIN_VERSION`; required at resolve-time |
| `spec.environment` | `str \| None` | optional | overridable via `--environment` / `STYRMIN_ENVIRONMENT`; required at resolve-time |
| `spec.cluster` | `str \| None` | optional | overridable via `--cluster` / `STYRMIN_CLUSTER`; never required |
| `spec.config` | `dict[str, JsonValue]` | optional | defaults to `{}`; full-replacement semantics |
| `spec.parameters` | `dict[str, JsonValue]` | optional | defaults to `{}`; full-replacement semantics |

**Validation rules** (Pydantic `model_config = ConfigDict(extra="forbid")` plus `model_validator`):
- Top-level extras → `ValidationError` ("unknown field at top level: <key>").
- Extras under `metadata` or `spec` → `ValidationError`.
- Wrong `apiVersion` → `ValidationError` with the supported version listed.
- Wrong `kind` → `ValidationError` with the supported kinds listed (currently only `Deployment`).
- `spec.driver` empty string → `ValidationError`.

**Source-tracking field** (set by the loader, not in the YAML): `_source_path: pathlib.Path` indicating the file the manifest was loaded from, used in error messages. Excluded from validation; populated programmatically.

---

## Pydantic: `ResolvedManifest`

A second model produced **after** override resolution. Encodes that all required fields are present.

| Field | Type | Required |
|---|---|---|
| `name` | `str` | yes |
| `driver` | `str` | yes |
| `version` | `str` | yes |
| `environment` | `str` | yes |
| `cluster` | `str \| None` | optional (disambiguation only) |
| `config` | `dict[str, JsonValue]` | yes (defaulted to `{}`) |
| `parameters` | `dict[str, JsonValue]` | yes (defaulted to `{}`) |
| `source_path` | `pathlib.Path` | yes |

If any of the required fields cannot be resolved from any source (CLI > env > manifest), the loader raises `MissingRequiredFieldError` *before* any backend call (FR-014).

---

## In-memory result: `ApplyOutcome`

Returned by `DeploymentResource.apply(manifest)`. Discriminated union or simple Pydantic model — choose at implementation time. Logical shape:

```python
class ApplyOutcome:
    name: str
    action: Literal["created", "updated", "failed"]
    deployment_id: UUID | None  # set on success
    task_id: UUID | None        # the Prefect task id from deploy / update_deployment
    failure_reason: str | None  # set on action == "failed"
```

The CLI aggregates these into a `BatchSummary`:

```python
class BatchSummary:
    outcomes: list[ApplyOutcome]

    @property
    def created_count(self) -> int: ...
    @property
    def updated_count(self) -> int: ...
    @property
    def failed_count(self) -> int: ...
    @property
    def exit_code(self) -> int:
        return 1 if self.failed_count else 0
```

---

## Backend service: lookup function

New service-layer function in `backend/styrmin_backend/services/deployment.py`:

```python
async def get_deployment_by_name(
    *, name: str, environment_id: UUID, uow: UnitOfWork
) -> Deployment | None:
    """Return the non-internal deployment for (name, environment_id), or None."""
```

- Repository call: `uow.deployments.find_one_by(name=name, environment_id=environment_id)`.
- Filter `internal=True` deployments out (returns `None` for them, matching the existing `deployment(deploymentId)` query's `internal` guard at `query.py:155`).
- Returns `None` on not-found (does not raise).

This dispatches one repository read. No new joins, no new state.

---

## GraphQL: new query field

```graphql
deployment(name: String, environmentId: UUID, deploymentId: UUID): Deployment
```

**Two argument shapes, never mixed**:
- `deployment(deploymentId: UUID!)` — existing behaviour, unchanged.
- `deployment(name: String!, environmentId: UUID!)` — new behaviour.

Implementation choice (resolved at design): since Strawberry does not natively express "exactly one of these argument groups", the resolver will accept all three arguments as optional with a runtime guard:
- exactly one of `(deploymentId)` or `(name AND environmentId)` must be provided;
- otherwise raise a `ServiceError` ("specify either deploymentId or (name + environmentId)").

This keeps the existing call sites untouched (they pass `deploymentId` only) and adds the new shape without breaking type compatibility.

**Internal-deployment guard** is reused: if either lookup finds an internal deployment, the resolver returns `None` (same as today's `internal` check).

---

## State transitions

The feature only **submits** state changes; it does not introduce new ones. The Deployment lifecycle (`PENDING → DEPLOYING → RUNNING → ...`) is unchanged. `apply` interacts with the existing transitions like this:

- **Create path** → submits `deploy` mutation, which creates a `Deployment` row in the existing pre-deploy state and dispatches the Prefect deployment workflow.
- **Update path (config/parameters only)** → submits `update_deployment`, which writes new config/parameters to the row and dispatches the existing reconciliation workflow.
- **Update path (version)** → submits `update_deployment_version`, which records the new version and dispatches the existing version-upgrade workflow.
- **Update path (both)** → `update_deployment`, then `update_deployment_version`. The instance-ID-based status reporting ensures the final reconciliation reflects both.

`--wait` polls `getDeployment` until the deployment's `applicationInstance.status` reaches a terminal value (`RUNNING` or a failure state), with timeout — same pattern as `deployments create --wait`.

---

## Error model

| Error | Where raised | When | User-facing message |
|---|---|---|---|
| `ManifestValidationError` | SDK loader | YAML schema fails Pydantic validation | "manifest <path>: <field> <reason>" |
| `MissingRequiredFieldError` | SDK loader | name/driver/version/environment unresolved after overrides | "manifest <path>: <field> is required (set in manifest, env var, or CLI flag)" |
| `EnvironmentAmbiguityError` | SDK `apply()` | env name matches multiple clusters and no cluster provided | "manifest <path>: environment '<env>' exists in multiple clusters: <list>; specify --cluster or spec.cluster" |
| `EnvironmentNotFoundError` | SDK `apply()` | no env matches the resolved `(environment, cluster)` pair | "environment '<env>'[ in cluster '<cluster>'] not found" |
| `DriverMismatchError` | SDK `apply()` | manifest's driver ≠ existing deployment's driver | "manifest <path>: driver mismatch (manifest=<m>, existing=<e>); driver changes require delete-and-recreate" |
| `BatchNameConflictError` | CLI | `--name` passed with batch input | "--name cannot be combined with multiple manifests" |
| Backend errors | passed through | network / permission / etc. | "manifest <path>: <backend message>" |

All six new SDK exception types extend a common `ApplyError` base class.

---

## Out of scope (data model)

- New persisted columns or tables: none.
- New events / audit log entries: none beyond what `deploy` / `update_deployment` already emit.
- New status fields on `Deployment`: none.
