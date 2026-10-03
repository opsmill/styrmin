# Errors

## `COMPONENT_CONTAINER_NOT_DECLARED` (FR-003)

- **Class**: `ComponentContainerNotDeclaredError(ServiceError)` in
  `backend/styrmin_backend/services/env_vars/exceptions.py`.
- **When**: a write submits a component-scope env var block that adds a key or changes a value,
  relative to the stored block, for a component that declares no component container in the
  driver version the deployment will be pinned to after the write.
- **Not raised**: for unchanged re-submissions or removals (submitted ⊆ stored); for deployment-
  or environment-scope env vars; for unknown components (those keep `UNKNOWN_COMPONENT_ENV_VAR`,
  checked first against the current version).
- **Default message**: `Environment variables target component {name!r}, which declares no
  component container in the deployment's driver. Components that accept env vars:
  {components_with_container}`.
- **Metadata**: `component_name: str`, `components_with_container: list[str]` (sorted).

## `RETIRED_TEMPLATE_FILTER` (FR-007)

- **Class**: `RetiredTemplateFilterError(ServiceError)` in
  `backend/styrmin_backend/services/exceptions.py` (next to `SchedulingPatchRenderingError`).
- **When**: a driver `values.j2.yml` calls `component_env_vars` during rendering.
- **Effect**: rendering aborts before a HelmRelease is built or applied; the operator pipeline
  records the message on the instance (existing `except Exception` path), so the deployment
  reports the failure with the message below.
- **Default message**: `The 'component_env_vars' template filter was removed: Styrmin now injects
  env vars into each component's declared component container. Deployment users: upgrade this
  deployment to a driver version that declares component containers. Driver authors: remove the
  filter from values.j2.yml and declare components.<name>.container in driver.styrmin.yml.
  Migration guide: https://styrmin.pages.dev/docs/drivers/migrating-env-vars`.
- **Metadata**: `filter: "component_env_vars"`, `migration_guide: <url>`.

## Env var patch serialisation failure

Reuses the scheduling precedent: eager `render_value()` of each `ContainerEnvPatch`; a failure
raises a typed `OPERATION_FAILED` `ServiceError` carrying `kind` and `label_selector`.

## Wrong component container name (runtime)

Not a Styrmin error: the strategic merge adds an image-less container, the Kubernetes API rejects
the workload, and the Helm release fails with Flux's message (`spec.template.spec.containers[0].image:
Required value`). Documented in the driver-author guide and migration guide.
