# Data Model: Environment-Config Update with Deployment Fanout

## 1. GraphQL input types

### 1.1 `UpdateEnvironmentInput` — the top-level input

```graphql
input UpdateEnvironmentInput {
  envVars: [EnvVarInput!]
  ipWhitelist: [String!]
  dedicatedIngress: DedicatedIngressInput
  scheduling: SchedulingInput
  fqdnSuffix: String
  externalUrlScheme: ExternalUrlScheme
  externalUrlPort: Int
  externalDnsEndpointsType: ExternalDnsEndpointsType
}
```

**Semantics — full replacement**: an `UpdateEnvironmentInput` represents the **complete** desired environment configuration. Any field omitted (`null`) is persisted as its unset state on the underlying `EnvironmentConfig` Pydantic model. Operators editing a single field MUST read the existing config and re-submit unchanged fields.

### 1.2 Nested input types

Each nested input mirrors the corresponding Pydantic type field-for-field. Where the Pydantic model uses `Literal` types or enums, the Strawberry input uses `@strawberry.enum` mirrors.

```graphql
input EnvVarInput {
  name: String!
  value: String!
}

input DedicatedIngressInput {
  className: String
  resources: ResourceRequirementsInput
  scheduling: SchedulingInput
  hostnameOverride: String
  # ... fields mirror DedicatedIngressConfig
}

input SchedulingInput {
  podAffinity: AffinityBlockInput
  podAntiAffinity: AffinityBlockInput
  nodeAffinity: AffinityBlockInput
  topologySpreadConstraints: [TopologySpreadConstraintInput!]
  resources: ResourceRequirementsInput
  tolerations: [TolerationInput!]
  runtimeClass: String
  inject: PostRenderInjectionInput
}

input AffinityBlockInput {
  required: [AffinityRuleInput!]
  preferred: [AffinityRuleInput!]
  # ... mirrors AffinityBlock
}

input ResourceRequirementsInput {
  requests: ResourceSpecInput
  limits: ResourceSpecInput
}

input ResourceSpecInput {
  cpu: String
  memory: String
  ephemeralStorage: String
  extended: JSON  # opaque map
}

input TolerationInput {
  key: String
  operator: TolerationOperator
  value: String
  effect: TolerationEffect
  tolerationSeconds: Int
}

input TopologySpreadConstraintInput {
  maxSkew: Int!
  topologyKey: String!
  whenUnsatisfiable: WhenUnsatisfiable!
  labelSelector: LabelSelectorInput
}

input PostRenderInjectionInput {
  podAffinity: Boolean
  nodeAffinity: Boolean
  topologySpread: Boolean
  resources: Boolean
  tolerations: Boolean
  runtimeClass: Boolean
  envVars: Boolean
}

enum ExternalUrlScheme { HTTP HTTPS }
enum ExternalDnsEndpointsType { NODE_EXTERNAL_IP CLUSTER_IP }
enum TolerationOperator { EXISTS EQUAL }
enum TolerationEffect { NO_SCHEDULE PREFER_NO_SCHEDULE NO_EXECUTE }
enum WhenUnsatisfiable { DO_NOT_SCHEDULE SCHEDULE_ANYWAY }
```

The exhaustive list of fields and nested types is whatever `EnvironmentConfig` and its dependencies expose at implementation time. The above is illustrative; the implementer's job is to follow the Pydantic shape.

### 1.3 Validation flow

Inputs flow through three layers:

1. **Strawberry** — schema-level shape enforcement (every required field present, every scalar correctly typed, every enum value valid).
2. **Pydantic-driven model conversion** — the input is converted to a dict and passed to `EnvironmentConfig.model_validate(...)`. Field validators on the Pydantic side (regex, size caps for env vars, custom invariants) raise the typed `ServiceError` subclasses from 008-deployment-env-vars.
3. **Pre-validation helpers** — `_prevalidate_environment_env_vars` runs ahead of `model_validate` so that typed env-var errors (`InvalidEnvVarNameError`, `EnvVarSizeLimitExceededError`, `DuplicateEnvVarNameError`) reach the GraphQL boundary as their precise `extensions.code` rather than collapsing into Pydantic's `ValidationError`.

## 2. Mutation surface

### 2.1 `Mutation.updateEnvironment`

```graphql
extend type Mutation {
  updateEnvironment(
    environmentId: UUID!
    input: UpdateEnvironmentInput!
  ): Environment
}
```

The argument shape is **clean replace** — `config: JSON` is removed in the same commit. Returns the updated `Environment` (matches the post-008 return type).

### 2.2 Service-layer flow (per-deployment no-op detection per FR-010 / critique X1)

```text
Operator
  → updateEnvironment(environmentId, input: UpdateEnvironmentInput)
  → Strawberry validates input shape
  → mutation handler converts input → dict → EnvironmentConfig.model_validate
    → _prevalidate_environment_env_vars (pre-validate to surface typed errors)
    → validate_environment_config (full Pydantic validation)
  → service.update_environment_with_fanout(environment_id, validated_config, uow)
    → environment = uow.environments.get(environment_id)  # raises EnvironmentNotFoundError if missing
    → environment.config = validated_config
    → environment.capabilities = compute_environment_capabilities(environment)
    → uow.commit()  # FR-009a: row committed BEFORE any Task dispatch
    → counts = { dispatched: 0, skipped_noop: 0, dispatch_failed: 0 }
    → for deployment in environment.deployments:
        → if deployment.tombstoned or deployment.internal: continue
        → if _deployment_already_at_config(deployment, validated_config):
            → counts.skipped_noop += 1; continue   # per-deployment no-op
        → try:
            → task = redeploy_for_environment_update(deployment, uow)
            → counts.dispatched += 1
          → except Exception as e:
            → counts.dispatch_failed += 1
            → logger.exception("env_config_fanout_dispatch_error", ...)
            → continue
    → emit metric env_config_fanout_deployments_total{environment, outcome=...}
    → log structured "env_config_fanout_dispatched" with environment_id + counts
    → return environment
```

**Note**: there is no mutation-level no-op skip. The env-config row is **always** persisted on a successful mutation; whether each deployment receives a redeploy is decided per-deployment in the loop. When every deployment is already at the new config (a true environment-wide no-op), the loop dispatches zero Tasks and `counts.skipped_noop` equals the deployment count.

### 2.3 Per-deployment redeploy helper

`redeploy_for_environment_update(deployment, uow)` is a new helper extracted from `update_deployment_version`'s shared section:

```python
async def redeploy_for_environment_update(
    deployment: Deployment,
    uow: UnitOfWork,
) -> Task:
    """Redeploy a deployment in response to an environment-config change.

    Generates a new ApplicationInstance from the deployment (which now resolves
    against the just-updated environment config), sets it as the active
    instance, and dispatches the reconciliation Task. Returns the Task.

    Mirrors the post-version-decision portion of update_deployment_version
    (services/deployment.py:494-583). Does NOT change the deployment's
    application_version, parameters, or service overrides — only regenerates
    the instance with the new environment context.
    """
    current_instance = deployment.active_instance
    new_instance = await generate_instance_from_deployment(
        deployment=deployment, uow=uow,
    )
    deployment.set_active_instance(instance=new_instance)
    deployment.set_status(DeploymentState.DEPLOYING)
    task = await apply_state(
        deployment=deployment,
        current_instance=current_instance,
        uow=uow,
    )
    await uow.deployments.save(deployment=deployment)
    return task
```

The helper lives in `services/deployment.py` next to `update_deployment_version`; `update_environment` imports and calls it.

## 3. No-op detection (per-deployment per FR-010 / critique X1)

```python
def _deployment_already_at_config(
    deployment: Deployment,
    new_config: EnvironmentConfig,
) -> bool:
    """Return True when the deployment's currently-active ApplicationInstance
    was generated against an environment config canonically equal to ``new_config``.

    Used inside the fanout loop to decide whether a deployment needs a redeploy
    Task — fully-converged deployments are skipped (no spurious work), while
    laggards (e.g., from a prior partially-failed fanout) are re-dispatched.

    The canonical form normalises ``None``-vs-missing drift via the shared
    ``EnvironmentConfig.model_validate`` round-trip.
    """
    active = deployment.active_instance
    if active is None or active.context is None:
        return False  # no active instance → must dispatch redeploy
    # The active instance's source environment-config slice is stored under a
    # known key in `active.context` (concrete key TBD at implementation time).
    instance_env_config_dict = _extract_environment_slice_from_context(active.context)
    instance_env_config = EnvironmentConfig.model_validate(instance_env_config_dict)
    return (
        new_config.model_dump(exclude_none=True, mode="json")
        == instance_env_config.model_dump(exclude_none=True, mode="json")
    )
```

The decision lives **inside the fanout loop**, applied per deployment. There is no separate mutation-level no-op short-circuit — the env-config row is always committed, and whether each deployment receives a Task is computed individually. This naturally handles partial-fanout recovery: if a prior fanout dispatched Tasks for some deployments but not others, the next mutation call (with the same input) re-evaluates each deployment's active instance against the persisted config, finds the laggards, and re-dispatches Tasks only for those.

The per-deployment check is cheap (one in-memory comparison after a Pydantic round-trip; no DB hit beyond loading the active instance which is already eager-loaded for the loop).

## 4. Storage

| Field | Storage location |
|---|---|
| `Environment.config` | `Environment.config` JSON column (existing) |
| `ApplicationInstance` versions per deployment | `ApplicationInstance` rows (existing) |
| Per-deployment timeline entry for the fanout | the existing context-diff machinery (`services/deployment_timeline.py`) |
| Fanout dispatch log | `logger.info("env_config_fanout_dispatched", ...)` — no DB persistence |

**No new database columns; no migration.** This is a clean reuse of the post-008 storage shape.

## 5. State transitions

### 5.1 Successful env-config update with fanout

```text
T0: operator submits updateEnvironment(input)
T1: input validates; new_config != persisted_config
T2: environment.config row updated; capabilities recomputed; uow.commit()
T3: fanout loop dispatches one redeploy Task per non-excluded deployment
T4: mutation returns success with updated Environment
T5..Tn: each per-deployment Task runs through Prefect; successes update the deployment's timeline; failures record on the per-deployment Task
```

### 5.2 Environment-wide no-op update (every deployment already converged)

```text
T0: operator submits updateEnvironment(input) where input == persisted state
    AND every deployment in the environment already has an active instance
    at that config.
T1: input validates
T2: environment.config row updated (updated_at ticks); uow.commit()
T3: fanout loop runs; for every deployment _deployment_already_at_config returns True;
    every iteration increments skipped_noop; zero Tasks dispatched.
T4: mutation returns success.
```

### 5.2a Partial-fanout recovery (a laggard from a prior failed fanout)

```text
Scenario: a prior updateEnvironment(input=v2) dispatched Tasks for deployments A and C
but failed to dispatch for deployment B (transient Prefect error). The env-config row
was committed at v2; A and C are now at v2; B is still at v1.

T0: operator (or automation) re-submits updateEnvironment(input=v2).
T1: input validates.
T2: environment.config row updated (idempotent — already at v2); uow.commit().
T3: fanout loop iterates A, B, C:
    - A: _deployment_already_at_config returns True (A's active instance was generated
      against v2 in the prior call); skipped_noop += 1.
    - B: _deployment_already_at_config returns False (B's active instance is still v1);
      redeploy_for_environment_update dispatched; dispatched += 1.
    - C: _deployment_already_at_config returns True; skipped_noop += 1.
T4: mutation returns success; B will reconcile to v2 via the new Task.
```

### 5.3 Per-deployment failure during fanout

```text
T0: operator submits updateEnvironment(input)
T1: input validates; not a no-op
T2: environment.config row updated; uow.commit()
T3a: deployment A's redeploy_for_environment_update succeeds; Task dispatched
T3b: deployment B's redeploy_for_environment_update raises (e.g., chart render error); failure logged + continues
T3c: deployment C's redeploy_for_environment_update succeeds; Task dispatched
T4: mutation returns success (env-config row persisted, fanout dispatch complete)
T5+: A and C reconcile to the new config; B's deployment timeline shows the failed Task
```

## 6. Errors

| Error | When | GraphQL `extensions.code` |
|---|---|---|
| `EnvironmentNotFoundError` | `environment_id` does not exist | `ENVIRONMENT_NOT_FOUND` (existing) |
| `InvalidEnvVarNameError` | env var name regex fails | `INVALID_ENV_VAR_NAME` (existing from 008) |
| `EnvVarSizeLimitExceededError` | per-value or per-scope cap exceeded | `ENV_VAR_SIZE_LIMIT_EXCEEDED` (existing) |
| `DuplicateEnvVarNameError` | duplicate name in input list | `DUPLICATE_ENV_VAR_NAME` (existing) |
| `InvalidContextError` | other Pydantic validation failures (non-env-var fields) | `INVALID_CONTEXT` (existing) |

**No new error types are introduced**. The feature relies entirely on the post-008 error catalogue.

## 7. Frontend data model

### 7.1 `EnvironmentConfigurationTab` props

```typescript
interface EnvironmentConfigurationTabProps {
  environmentId: string;
  config: EnvironmentConfig;  // typed projection from generated GraphQL types
  deployments: Deployment[];   // already in the page's query result
  onSubmit: (input: UpdateEnvironmentInput) => Promise<void>;
}
```

The component is a **controlled** wrapper: it reads `config` for display, mediates edits in local state, and calls `onSubmit` when the operator confirms. The parent (`EnvironmentDetailPage`) refetches the environment on success.

### 7.2 `EnvVarsForm` state

```typescript
interface EnvVarRowState {
  id: string;        // local UUID for React key + remove targeting
  name: string;
  value: string;
  errors: {
    name?: string;   // 'invalid name pattern' / 'duplicate'
    value?: string;  // 'value exceeds 64 KiB'
  };
}

interface EnvVarsFormState {
  rows: EnvVarRowState[];
  totalBytes: number;        // running total for the per-scope 256 KiB cap
  globalError: string | null;  // 'too many entries' / 'total size exceeds 256 KiB'
}
```

Validation rules (mirror backend):

| Rule | When |
|---|---|
| Name regex `^[A-Za-z_][A-Za-z0-9_]*$` | per-row, on-blur and on-submit |
| Per-value 64 KiB | per-row, on-input |
| Per-scope 100 entries | global, on-add |
| Per-scope 256 KiB total | global, on-input (live total) |
| No duplicate names | global, on-input |

Submit is disabled whenever any row has `errors.name` or `errors.value` set, OR `globalError != null`.

### 7.3 `RedeployConfirmDialog` props

```typescript
interface RedeployConfirmDialogProps {
  open: boolean;
  deploymentCount: number;
  deploymentNames: string[];
  onConfirm: () => void;
  onCancel: () => void;
}
```

Renders one of:

- "0 deployments will be redeployed" + Redeploy button
- "1 deployment will be redeployed: {name}" + Redeploy button
- "{N} deployments will be redeployed: {name1}, {name2}, ..." + Redeploy button (truncates with "and N more" past 5 names)
