# Contract: Typed Errors

**File**: `backend/styrmin_backend/services/container_overrides/exceptions.py`

All inherit `ServiceError` (carry `error_code` + `default_message`) and surface to GraphQL via the `StructuredErrorExtension` middleware as `extensions.code` + metadata (Constitution §IV). Raised at the **mutation/write boundary, before any reconcile** (FR-004, US4: zero containers restarted on rejection).

| Error class | `error_code` | Raised when | Payload | Spec |
|-------------|--------------|-------------|---------|------|
| `InvalidContainerCommandError` | `INVALID_CONTAINER_COMMAND` | `command` is `[]`, or contains a non-string element | `component_name`, offending detail | FR-006, US4 Sc.2/Sc.3 |
| `InvalidContainerArgsError` | `INVALID_CONTAINER_ARGS` | `args` is `[]`, or contains a non-string element | `component_name`, offending detail | FR-006, US4 Sc.2/Sc.3 |
| `UnknownComponentContainerOverrideError` | `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE` | a `command`/`args` block targets a component the pinned driver version does not declare | `component_name`, `known_components` (sorted) | FR-004, US4 Sc.1 |
| `ContainerOverrideSizeLimitExceededError` | `CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED` | a `command`/`args` list exceeds the per-list element-count cap (1024) or serialised-byte cap (256 KiB) | `field`, `component_name`, `elements`/`bytes`, `cap` | mirrors env-vars FR-008 (keeps the deployment CRD under the Kubernetes resource size limit) |

**Reused, unchanged**:

- `DuplicateComponentNameError` (`DUPLICATE_COMPONENT_NAME`) — duplicate component `name` within the `components` input list (raised by the shared `_flatten_components`).

**Deliberately NOT reused**: `UnknownComponentEnvVarError` / `INVALID_ENV_VAR_*` stay env-var-specific so env-vars behaviour is byte-identical (SC-004) and the offending field (`command` vs `args`) is unambiguous in the error (US4 Sc.3). See research D5.

## Acceptance assertions (drive the propagation + E2E negative paths)

1. `command: []` → `extensions.code == "INVALID_CONTAINER_COMMAND"`; no instance generated.
2. `args: [123]` → `extensions.code == "INVALID_CONTAINER_ARGS"`; no instance generated.
3. override on undeclared component `ghost` → `extensions.code == "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE"`, metadata `known_components` lists the driver's declared components; no reconcile planned.
4. `command: ["sh","-c",""]` → **accepted** (empty-string element valid); redeploy proceeds.
