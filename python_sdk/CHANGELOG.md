# Changelog

All notable changes to the Styrmin Python SDK will be documented in this file.

## Unreleased

### Added

- **`client.clusters.update(config, cluster_id=None, cluster_name=None, *, dry_run=False)`**
  replaces a cluster's config and returns the deployments the update redeploys, leaves
  waiting for a dedicated ingress controller, skips for a restore or could not start.
  `config` is a dict, like `clusters.create()`: snake_case or camelCase keys, and the
  stored enum values that `clusters.get()` returns. An unknown key at any depth raises
  `ValueError` before any request. With `dry_run=True`, nothing is saved. The call waits
  up to 600 seconds.
- **`client.deployments.wait_for_task(task_id, *, max_wait=None)`** waits until the
  change that a task of a deployment makes has finished, and returns a `TaskWait`. It
  takes the task that `create()`, `update()`, `scale()`, `update_version()`, `delete()`,
  `start_components()`, `stop_components()` or `run_job()` returns. It waits until the
  task result is no longer `RUNNING`, then, when the result is `SUCCEEDED`, until the
  deployment status is `running`, `failed` or `deleted`. `TaskWait.succeeded` is true
  when the status is `running`, or `deleted` after `delete()`. Otherwise
  `failure_reason` names the failed step, the superseded task, the deployment status or
  the timeout, and the call does not raise. Before, a program polled by hand, and a
  `running` status read right after `start_components()` or `stop_components()` was
  the status from before the change. ([#545](https://github.com/opsmill/styrmin/issues/545))
- **`client.environments.get_pod_statuses()`** and **`client.clusters.get_pod_statuses()`**
  return the pod statuses of every deployment of an environment or of a cluster, and
  **`client.environments.get_services()`** returns the services of every deployment of an
  environment. Before, a program called `deployments.get_pod_statuses()` once per
  deployment. ([#547](https://github.com/opsmill/styrmin/issues/547))
  - They take the same arguments as `environments.get()` and `clusters.get()`: an ID or
    a name. They read the environment or the cluster first, so an unknown ID or name
    raises `ResourceNotFoundError`.
  - The lists include internal deployments, such as the ingress controller of a dedicated
    ingress, and leave out deleted deployments. Their order is not fixed.
  - A pod that started since the agent's last report, about 5 seconds earlier, is not
    listed yet, so a new environment can return an empty list.
  - The services have no URL or FQDN; `deployments.get()` returns them.
  - `styrmin_sdk.models` exports the item types as `PodStatus`, with `PodPhase`, and
    `DeployedService`.
- **`client.deployments.get_crd_status(deployment_id)`** returns the deployment state and,
  as `crd_status`, the status of the deployment's `StyrminDeployment` as the agent last
  reported it. Before, a program could read the deployment state, but not why a
  deployment did not reach `running`. ([#548](https://github.com/opsmill/styrmin/issues/548))
  - `crd_status` gives the operator's phase and message, the conditions, the managed
    resource counts and the time the server received the report (`last_polled_at`). It
    is `None` until the agent first reports the deployment.
  - The server stores every report, including a report about the previous instance
    during a rollout and a report sent during a restore. Decide from `status` whether
    the deployment is running or has failed, and read `crd_status` to find out why.
  - An unknown ID, or the ID of an internal deployment, raises `ResourceNotFoundError`.
  - `styrmin_sdk.models` exports the returned types as `DeploymentCrdStatus`,
    `CrdStatus`, `CrdCondition` and `ManagedResourceCounts`.

### Fixed

- **`StyrminAPIError.extensions`** gives all the extensions of the GraphQL error that
  the server returned, `code` included, in every subclass (`OperationFailedError`,
  `ResourceNotFoundError` and the others). Before, the exception kept only the message
  and `extensions.code` (`typename`), so a program had to parse the message to read,
  for example, the `path` of a refused affinity term or the `deployments` of a refused
  `environment_clones.create()` request. An error without extensions gives an empty
  dict. ([#522](https://github.com/opsmill/styrmin/issues/522))

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
