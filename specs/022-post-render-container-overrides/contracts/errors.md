# Contract: Error Codes

**Feature**: [../spec.md](../spec.md) | FR-011: no new error code.

## `RETIRED_TEMPLATE_FILTER` (extended)

`RetiredTemplateFilterError` in [`services/exceptions.py`](../../../backend/styrmin_backend/services/exceptions.py). Raised while `values.j2.yml` renders, before the HelmRelease is built, so no HelmRelease is applied.

| Filter | Metadata `filter` | Metadata `migration_guide` |
|--------|-------------------|----------------------------|
| `component_env_vars` (unchanged) | `component_env_vars` | `https://styrmin.pages.dev/docs/drivers/migrating-env-vars` |
| `component_command` (new) | `component_command` | `https://styrmin.pages.dev/docs/drivers/migrating-container-overrides` |
| `component_args` (new) | `component_args` | `https://styrmin.pages.dev/docs/drivers/migrating-container-overrides` |

Message for the two new filters (one per filter name; `<filter>` is the name):

> The '`<filter>`' template filter was removed: Styrmin now applies container command and args overrides to each component's declared component container. Deployment users: move this deployment to a driver version that no longer calls the filter. Driver authors: remove the filter from values.j2.yml and declare components.&lt;name&gt;.container in driver.styrmin.yml. Migration guide: https://styrmin.pages.dev/docs/drivers/migrating-container-overrides

On the live path only the message survives the StyrminDeployment CR hop: the operator records `Failed to create HelmRelease: <message>` on the deployment (ADR-057 §4). The message therefore names the filter and the guide.

## `COMPONENT_CONTAINER_NOT_DECLARED` (extended)

`ComponentContainerNotDeclaredError` in [`services/env_vars/exceptions.py`](../../../backend/styrmin_backend/services/env_vars/exceptions.py). Raised by `deploy` and `updateDeployment` before any task starts.

| Metadata | Value |
|----------|-------|
| `component_name` | the component |
| `components_with_container` | sorted names of components with a component container |
| `override` | `env_vars`, `image`, **`command`** (new) or **`args`** (new) |

Raised when a write adds or changes the slot. Not raised for a removal (`null` or an omitted key) or for the same value sent again.

Message for the new values: "Container `<command|args>` override targets component '`<name>`', which declares no component container in `<checked against>`. Components that accept overrides: [...]".

## `COMPONENT_CONTAINER_NOT_FOUND` (extended trigger)

`ComponentContainerNotFoundError` in [`services/component_container/exceptions.py`](../../../backend/styrmin_backend/services/component_container/exceptions.py). No code change: the guard patch is now also built when `command` or `args` is the only applicable override, so a wrong container name fails the reconcile in that case too (FR-004). Metadata `component_name`, `container`.

## Removed

| Code | Why |
|------|-----|
| `DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH` | Validated `spec.container_overrides`, which is removed. A driver file with that block now fails earlier with the unknown-key error |

## Unchanged

`INVALID_CONTAINER_COMMAND`, `INVALID_CONTAINER_ARGS`, `CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED`, `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`.
