# Contract: SDK `DeploymentResource.apply()` and `apply_files()`

This contract defines the public Python SDK surface that any CLI, automation, or higher-level tool will consume. The CLI itself is a thin wrapper around `apply_files()`.

## Methods

### `DeploymentResource.apply(manifest, /) -> ApplyOutcome`

Apply a single, *already-resolved* manifest.

```python
async def apply(self, manifest: ResolvedManifest) -> ApplyOutcome: ...
```

**Parameters**:
- `manifest: ResolvedManifest` — a manifest where every required field (`name`, `driver`, `version`, `environment`, optional `cluster`, `config`, `parameters`) has been resolved from the manifest plus its overrides. The caller is expected to do override resolution before calling `apply()`.

**Behaviour** (in order):
1. Resolve the target environment by `(environment_name, cluster_name)`. If the resolution is ambiguous and `cluster_name` is not set, raise `EnvironmentAmbiguityError` listing the candidate clusters. If no environment matches the resolved pair, raise `EnvironmentNotFoundError`.
2. Look up an existing deployment via `get_by_name(name=manifest.name, environment_id=resolved_env_id)`.
3. If not found:
   - call the existing `deploy()` method with `manifest`'s fields,
   - return `ApplyOutcome(name=..., action="created", deployment_id=..., task_id=...)`.
4. If found:
   - if `existing.application_driver_name != manifest.driver`, raise `DriverMismatchError`,
   - call `update_deployment()` with the manifest's `config`/`parameters`,
   - if `existing.application_version != manifest.version`, also call `update_deployment_version()`,
   - return `ApplyOutcome(name=..., action="updated", deployment_id=existing.id, task_id=<update task id>)`.

**Errors raised**:
- `ManifestValidationError` — never raised by `apply()` itself; raised by the loader before `ResolvedManifest` exists.
- `EnvironmentAmbiguityError` — env name resolves to multiple clusters and no cluster was provided.
- `EnvironmentNotFoundError` — no environment matches the resolved `(environment, cluster)` pair.
- `DriverMismatchError` — driver in manifest differs from existing deployment's driver.
- Any `StyrminClientError` propagated from the transport (network, auth, validation rejection from the backend).

**Does not catch** transport-level errors — the caller (typically `apply_files()` or the CLI) is responsible for converting those into `ApplyOutcome(action="failed")` for batch use.

---

### `DeploymentResource.apply_files(paths, /, *, overrides=None) -> list[ApplyOutcome]`

Batch convenience: load files (or directories), resolve overrides, and apply each one with continue-on-error.

```python
async def apply_files(
    self,
    paths: Sequence[Path | str],
    *,
    overrides: ApplyOverrides | None = None,
) -> list[ApplyOutcome]: ...
```

**Parameters**:
- `paths` — file paths and/or directory paths, in user-supplied order. Directories are expanded to their immediate `.yaml`/`.yml` files, sorted by filename.
- `overrides` — an `ApplyOverrides` object with optional `name`, `version`, `environment`, `cluster`. The CLI builds this from CLI flags + env vars; library callers pass it directly.

**Behaviour**:
1. Expand each path:
   - file → one entry,
   - directory → its sorted `.yaml`/`.yml` files,
   - missing path → fail-fast with `FileNotFoundError`.
2. Reject the combination of `overrides.name` set + more than one resolved manifest with `BatchNameConflictError`.
3. For each path, parse the YAML, validate each document via `DeploymentManifest`, resolve overrides into `ResolvedManifest`, then call `apply()`. On any per-manifest exception, append `ApplyOutcome(action="failed", failure_reason=str(exc))` and continue to the next manifest.
4. Return the list of outcomes in processing order.

**Does not raise** for per-manifest failures. **Does raise** for whole-batch errors that prevent processing (no paths, missing path, `--name` conflict, fundamentally unreadable YAML before any per-manifest dispatch).

---

### `DeploymentResource.get_by_name(name, /, *, environment_id) -> GetDeploymentByNameDeployment | None`

The thin wrapper over the new GraphQL query.

```python
async def get_by_name(
    self,
    name: str,
    *,
    environment_id: str | UUID,
) -> GetDeploymentByNameDeployment | None: ...
```

**Returns**: the deployment, or `None` if not found or hidden (internal). Mirrors `get(deployment_id)`'s shape.

---

## Types

```python
class ApplyOverrides(BaseModel):
    name: str | None = None
    version: str | None = None
    environment: str | None = None
    cluster: str | None = None

class ApplyOutcome(BaseModel):
    name: str
    action: Literal["created", "updated", "failed"]
    deployment_id: UUID | None = None
    task_id: UUID | None = None
    failure_reason: str | None = None

class ApplyError(StyrminError): ...
class ManifestValidationError(ApplyError): ...
class MissingRequiredFieldError(ApplyError): ...
class EnvironmentAmbiguityError(ApplyError): ...
class EnvironmentNotFoundError(ApplyError): ...
class DriverMismatchError(ApplyError): ...
class BatchNameConflictError(ApplyError): ...
```

`StyrminError` is the existing SDK exception base (defined in `python_sdk/src/styrmin_sdk/exceptions.py`). The new errors slot under it without changing the existing hierarchy. Because the CLI's `styrmin_error_handler()` in `cli/src/styrminctl/output.py` already catches `StyrminError`, the new exceptions integrate with the CLI's error path automatically.

### Concurrent apply (lookup-then-create race)

`apply()` performs a non-atomic lookup-then-create-or-update. Two concurrent runs against the same `(name, environment)` can both observe "not found" and both attempt `deploy()`. The database's unique constraint will reject the second one. On a duplicate-name backend error, `apply()` MUST re-run the lookup once and, if a deployment now exists, switch to the update path. Otherwise, the backend error is propagated verbatim.

### Source-path attribution

`apply()` itself takes only the resolved data (`ResolvedManifest`). Path-prefixed error messages (`"manifest <path>: <reason>"`) are constructed by `apply_files()` from the loader-level `source_path`. This keeps the SDK's `apply()` ignorant of filesystem concerns, so callers passing `ResolvedManifest` programmatically (without a backing file) get clean, path-free errors.

## Stability

- Method signatures and types: stable for the v1 SDK release.
- Error messages: not stable. Programs should branch on exception type, not message text.
- New optional fields on `ApplyOverrides` and `ApplyOutcome` are non-breaking.
