# Data Model: Typed `UpdateDeploymentInput` GraphQL Surface

This feature does not change any persisted data model. The Pydantic `DeploymentConfig`, `EnvironmentConfig`, `ClusterConfig`, `BaseConfigSection`, `ComponentConfigBlock` classes, the persisted `Deployment.config` dict shape, and the persisted `Deployment.parameters` dict shape are all unchanged. This document instead specifies the new **GraphQL-surface** types and the conversion rules between them and the existing Pydantic models.

## 1. New GraphQL input types

### 1.1 `UpdateDeploymentInput`

Top-level input for the `updateDeployment` mutation. Full-replacement semantics for every field except `parameters` (documented merge-not-replace asymmetry).

| Field | Type | Source-of-truth on Pydantic side | Notes |
|---|---|---|---|
| `name` | `String` | n/a (top-level scalar on `Deployment`) | Resolver-level rename. Omitted → no rename. |
| `parameters` | `[ParameterValueInput!]` | n/a (resolver derives a `dict[str, Any]`) | **Merge semantics** (not full-replacement). See FR-006. |
| `serviceNameOverrides` | `[ServiceNameOverrideInput!]` | n/a (resolver derives a `dict[str, str]`) | Full-replacement at top level. |
| `components` | `[ComponentConfigInput!]` | `DeploymentConfig.components: dict[str, ComponentConfigBlock]` | Resolver flattens list→dict on `name`. Full-replacement; duplicate `name` → `DuplicateComponentNameError`. |
| `envVars` | `[EnvVarInput!]` | `EnvironmentConfig.env_vars` (inherited into `DeploymentConfig`) | Resolver flattens list→dict on `name`. Duplicate `name` → `DuplicateEnvVarNameError` (scope `"deployment"`). |
| `ipWhitelist` | `[String!]` | `EnvironmentConfig.ip_whitelist` | List preserved as-is; empty list = explicit clear. |
| `dedicatedIngress` | `DedicatedIngressInput` | `DedicatedIngressConfig` (shared) | Reuses existing leaf input. |
| `scheduling` | `SchedulingInput` | `SchedulingConfig` (shared) | Reuses existing leaf input. |
| `fqdnSuffix` | `String` | `BaseConfigSection.fqdn_suffix` | Scalar passthrough. |
| `externalUrlScheme` | `ExternalUrlScheme` | `BaseConfigSection.external_url_scheme` (`Literal["http","https"]`) | Enum; `.value` on convert. |
| `externalUrlPort` | `Int` | `BaseConfigSection.external_url_port` | Scalar passthrough; Pydantic enforces `1 ≤ port ≤ 65535`. |
| `externalDnsEndpointsType` | `ExternalDnsEndpointsType` | `BaseConfigSection.external_dns_endpoints_type` | Enum. |
| `ingressClass` | `String` | `BaseConfigSection.ingress_class` | Scalar passthrough. |
| `dbSize` | `String` | `BaseConfigSection.db_size` | Scalar passthrough. |
| `runtimeClass` | `String` | `ClusterConfig.runtime_class` | New on this input (not present on `UpdateEnvironmentInput`). |
| `nodeSelector` | `String` | `ClusterConfig.node_selector` | New on this input. |
| `standardStorage` | `StandardStorageInput` | `ClusterConfig.standard_storage: StandardStorage{storage_class}` | New leaf input; lives in `config/inputs.py`. |

**Verification (FR-001)**: Introspect `UpdateDeploymentInput`, compare its field set to `set(DeploymentConfig.model_fields) ∪ {"name", "parameters", "serviceNameOverrides"}`. The two sets must be equal (modulo camelCase ↔ snake_case naming).

### 1.2 `ComponentConfigInput`

Per-component override block. Currently carries `envVars` only; future per-component knobs (e.g. replicas from #202) slot into the same input without a schema renumber.

```
input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!]
}
```

| Field | Type | Source-of-truth | Notes |
|---|---|---|---|
| `name` | `String!` | dict-key on `DeploymentConfig.components` | Required; duplicates → `DuplicateComponentNameError`. |
| `envVars` | `[EnvVarInput!]` | `ComponentConfigBlock.env_vars: dict[str, str]` | Flattened list→dict on `name`; duplicates → `DuplicateEnvVarNameError(scope="component:<name>")`. |

### 1.3 `ParameterValueInput`

Single driver-defined parameter assignment. Value stays JSON because parameter shapes are dynamic per driver version.

```
input ParameterValueInput {
  name: String!
  value: JSON!
}
```

### 1.4 `ServiceNameOverrideInput`

The existing `ServiceNameOverride` type (`api/definitions/service/model.py:97`) is already a `@strawberry.input` and is reused unchanged; it just moves from being a mutation argument to being nested under `UpdateDeploymentInput.serviceNameOverrides`. No new type, no field changes.

### 1.5 `StandardStorageInput`

New leaf input mirroring `StandardStorage`.

```
input StandardStorageInput {
  storageClass: String!
}
```

Lives in `config/inputs.py` alongside the other shared leaves.

## 2. Reused leaf inputs (no changes)

Defined today in `backend/styrmin_backend/api/definitions/environment/inputs.py`; moved to `backend/styrmin_backend/api/definitions/config/inputs.py` and re-exported from `environment/inputs.py` for backwards compatibility within the same release:

- `EnvVarInput`, `LabelSelectorInput`, `LabelSelectorRequirementInput`, `DeploymentReferenceInput`
- `AffinityTermInput`, `WeightedAffinityTermInput`, `AffinityBlockInput`
- `ResourceSpecInput`, `ResourceRequirementsInput`
- `TolerationInput`, `TopologySpreadConstraintInput`, `PostRenderInjectionInput`
- `SchedulingInput`, `IngressServiceConfigInput`, `DedicatedIngressInput`
- Enums: `ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, `TolerationEffect`, `WhenUnsatisfiable`, `LabelSelectorOperator`

## 3. New typed errors

| Class | Module | `error_code` | Payload | Raised from |
|---|---|---|---|---|
| `DuplicateParameterNameError` | `backend/styrmin_backend/services/parameters/exceptions.py` (or equivalent — verify at impl time) | `DUPLICATE_PARAMETER_NAME` | `{"name": <offending name>}` | `update_deployment_input_to_dict` during `parameters` flatten |
| `DuplicateComponentNameError` | `backend/styrmin_backend/services/env_vars/exceptions.py` (sibling to `DuplicateEnvVarNameError`) | `DUPLICATE_COMPONENT_NAME` | `{"name": <offending name>}` | `update_deployment_input_to_dict` during `components` flatten |

Both inherit from `ServiceError` and surface via the `StructuredErrorExtension` middleware, exactly like the existing env-var errors.

## 4. Conversion rules — `update_deployment_input_to_dict`

Mirrors the rules in `update_environment_input_to_dict` (`api/definitions/environment/inputs.py:295-341`) with two additions (`parameters` flatten, `components` flatten). Pseudocode:

```text
def update_deployment_input_to_dict(input) -> dict[str, Any]:
    converted = _convert_value(input)   # generic recursive omitter+enum→.value
    result = {}
    for key, value in converted.items():
        if key == "env_vars":
            result["env_vars"] = _flatten_env_vars(value, scope="deployment")
        elif key == "parameters":
            result["parameters"] = _flatten_parameters(value)
        elif key == "components":
            result["components"] = _flatten_components(value)
        elif key == "service_name_overrides":
            result["service_name_overrides"] = {
                o["driver_service_name"]: o["override_name"] for o in value
            }
        else:
            result[key] = value
    return result


def _flatten_components(rows) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        name = row["name"]
        if name in out:
            raise DuplicateComponentNameError(name=name)
        block = {k: v for k, v in row.items() if k != "name"}
        if "env_vars" in block:
            block["env_vars"] = _flatten_env_vars(block["env_vars"], scope=f"component:{name}")
        out[name] = block
    return out
```

The shared `_convert_value` helper is moved to `config/inputs.py` so both top-level converters can use it.

## 5. Resolver post-conversion split

The resolver in `api/schema/mutation.py` derives the four legacy service-function arguments from the converted dict:

```text
converted = update_deployment_input_to_dict(input)
deployment_name = converted.pop("name", None)
deployment_parameters = converted.pop("parameters", None)
service_name_overrides = converted.pop("service_name_overrides", None)
deployment_config = converted or None   # remainder is the config dict
task = await update_deployment(
    deployment_id=deployment_id,
    deployment_config=deployment_config,
    deployment_parameters=deployment_parameters,
    deployment_name=deployment_name,
    service_name_overrides=service_name_overrides,
    uow=uow,
)
```

The `or None` guard preserves the "all-omitted → service raises InvalidContextError" path: if the input is `{}`, `converted` is `{}`, all three pops return `None`, and `deployment_config` resolves to `None` — the service's existing "at least one of …" check fires unchanged (FR-007).

## 6. State and lifecycle

No state machines change. The mutation continues to be the **trigger** for a deployment re-reconciliation; the typed input does not change what state the deployment passes through (`PENDING → RUNNING → CONVERGED` or its failure variants) or what objects are produced (a new `Instance` row, an `apply_state` Task, the same Kubernetes resources). The persisted `Deployment.config` dict shape after this feature is bit-identical to what today's JSON-blob caller produces, given semantically equivalent inputs.

## 7. Out-of-scope (data-model edition)

- No new persisted columns.
- No new Pydantic model classes (the new GraphQL inputs map to existing Pydantic models).
- No changes to the `Instance` shape, the `Task` shape, the reconciliation workflow, or the driver-rendering pipeline.
- No per-driver schema generation for `parameters.value`.
