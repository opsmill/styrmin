# Changelog

All notable changes to the Styrmin Python SDK will be documented in this file.

## Unreleased

### Breaking changes

- **`client.deployments.update(...)` signature change.** The method no longer
  accepts `name: str`, `config: dict`, `parameters: dict`, or
  `service_name_overrides: list` keyword arguments. The only keyword arguments
  are now `deployment_id: UUID` and `input: UpdateDeploymentInput`. Every
  writable field (top-level env vars, scheduling, components, parameters,
  ip_whitelist, name, service_name_overrides) is now a named, type-checked
  attribute on the new `UpdateDeploymentInput` model, re-exported from
  `styrmin_sdk.models`.

  **Before:**

  ```python
  task = await client.deployments.update(
      deployment_id=UUID("5f2c4f8e-..."),
      name="web-staging-v2",
      config={
          "components": {
              "web": {"envVars": {"OTEL": "https://otel.staging"}},
          },
          "scheduling": {"resources": {"requests": {"cpu": "200m"}}},
      },
      parameters={"replicas": 3},
  )
  ```

  **After:**

  ```python
  from uuid import UUID
  from styrmin_sdk import StyrminClient
  from styrmin_sdk.models import (
      UpdateDeploymentInput,
      ComponentConfigInput,
      EnvVarInput,
      SchedulingInput,
      ResourceRequirementsInput,
      ResourceSpecInput,
      ParameterValueInput,
  )

  task = await client.deployments.update(
      deployment_id=UUID("5f2c4f8e-..."),
      input=UpdateDeploymentInput(
          name="web-staging-v2",
          components=[
              ComponentConfigInput(
                  name="web",
                  env_vars=[
                      EnvVarInput(name="OTEL", value="https://otel.staging"),
                  ],
              ),
          ],
          scheduling=SchedulingInput(
              resources=ResourceRequirementsInput(
                  requests=ResourceSpecInput(cpu="200m"),
              ),
          ),
          parameters=[ParameterValueInput(name="replicas", value=3)],
      ),
  )
  ```

### Semantics to remember

- Omitted fields on `UpdateDeploymentInput` are **no-ops** (the persisted value
  is not touched). Submitting `field=None` is also a no-op.
- Submitting `field=[]` (empty list) for list-shaped fields (`ip_whitelist`,
  `service_name_overrides`) is an **explicit clear**.
- `parameters` keeps **merge semantics**: entries in the input merge on top of
  the persisted parameters dict; existing keys not named in the input survive.
- Duplicate names within a single input scope return a typed error
  (`DUPLICATE_ENV_VAR_NAME`, `DUPLICATE_PARAMETER_NAME`,
  `DUPLICATE_COMPONENT_NAME`) instead of last-write-wins.
