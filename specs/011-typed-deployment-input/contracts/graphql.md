# GraphQL Contract: Typed `UpdateDeploymentInput` Surface

This contract enumerates every GraphQL surface change introduced by this feature. Each new schema element is one row in §4 — the propagation-test matrix — and **each row corresponds to one mandatory unit test** per Constitution §V. The error-code propagation matrix in §5 enumerates the boundary tests required by FR-008 and FR-009.

## 1. New input types

```graphql
"""Full-replacement input for the updateDeployment mutation.

Top-level fields use full-replacement semantics: an omitted (null) field
means "do not touch the corresponding persisted state"; an empty list/dict
means "explicitly clear". The single exception is `parameters`, which uses
merge semantics for backwards compatibility — entries in the input merge on
top of the persisted parameters dict (existing keys not named in the input
survive)."""
input UpdateDeploymentInput {
  name: String
  parameters: [ParameterValueInput!]    # merge semantics
  serviceNameOverrides: [ServiceNameOverrideInput!]
  components: [ComponentConfigInput!]

  # Mirrors EnvironmentConfig + ClusterConfig + BaseConfigSection fields
  envVars: [EnvVarInput!]
  ipWhitelist: [String!]
  dedicatedIngress: DedicatedIngressInput
  scheduling: SchedulingInput
  fqdnSuffix: String
  externalUrlScheme: ExternalUrlScheme
  externalUrlPort: Int
  externalDnsEndpointsType: ExternalDnsEndpointsType
  ingressClass: String
  dbSize: String
  runtimeClass: String
  nodeSelector: String
  standardStorage: StandardStorageInput
}

"""Per-component override block for the deployment. Carries env-var
overrides today; future per-component knobs (e.g. replicas) slot in
without a schema renumber."""
input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!]
}

"""A single driver-defined parameter assignment. Parameter shapes are
dynamic per driver version, so `value` remains JSON-typed."""
input ParameterValueInput {
  name: String!
  value: JSON!
}

"""Mirrors ClusterConfig.standard_storage."""
input StandardStorageInput {
  storageClass: String!
}
```

**Reused from `UpdateEnvironmentInput`** (no duplication; same Python objects post-extraction): `EnvVarInput`, `LabelSelectorInput`, `LabelSelectorRequirementInput`, `DeploymentReferenceInput`, `AffinityTermInput`, `WeightedAffinityTermInput`, `AffinityBlockInput`, `ResourceSpecInput`, `ResourceRequirementsInput`, `TolerationInput`, `TopologySpreadConstraintInput`, `PostRenderInjectionInput`, `SchedulingInput`, `IngressServiceConfigInput`, `DedicatedIngressInput`, `ExternalUrlScheme`, `ExternalDnsEndpointsType`, `TolerationOperator`, `TolerationEffect`, `WhenUnsatisfiable`, `LabelSelectorOperator`.

**Reused from existing**: `ServiceNameOverrideInput` — the existing `ServiceNameOverride` input type at `backend/styrmin_backend/api/definitions/service/model.py:97` is renamed to `ServiceNameOverrideInput` for consistency with the rest of the input-naming convention. The schema-side rename is the only change.

## 2. Mutation signature change

**Before**:

```graphql
type Mutation {
  updateDeployment(
    deploymentId: UUID!
    name: String
    config: JSON
    parameters: JSON
    serviceNameOverrides: [ServiceNameOverride!]
  ): Task
}
```

**After**:

```graphql
type Mutation {
  updateDeployment(
    deploymentId: UUID!
    input: UpdateDeploymentInput!
  ): Task
}
```

**Cutover rule**: the `Before` shape is removed in the same release that ships the `After` shape. No deprecation period.

## 3. New error codes

| `extensions.code` | Class | Raised when |
|---|---|---|
| `DUPLICATE_PARAMETER_NAME` | `DuplicateParameterNameError` | `UpdateDeploymentInput.parameters` contains two entries with the same `name`. |
| `DUPLICATE_COMPONENT_NAME` | `DuplicateComponentNameError` | `UpdateDeploymentInput.components` contains two entries with the same `name`. |

Both classes are new and inherit from `ServiceError`. Both are raised from `update_deployment_input_to_dict` before the resolver forwards anything to the service function.

## 4. Propagation-test matrix (FR-001, FR-002, FR-005; SC-001)

Every row maps to one mandatory unit test under `backend/tests/functional/graphql/test_update_deployment_input_propagation.py` (or a sibling file — name resolved at implementation time). The test pattern is the standard one from `dev/guides/graphql-propagation-tests.md`: submit a real GraphQL mutation, assert the value reaches the persisted `Deployment.config` (or `Deployment.parameters`, `Deployment.name`, `Deployment.service_name_overrides`) dict, then read it back through the `Deployment` query and assert it round-trips.

| # | Input field (GraphQL) | Pydantic destination | Test name suffix |
|---|---|---|---|
| 01 | `name` | `Deployment.name` | `_name` |
| 02 | `parameters[*].name`/`value` (merge) | `Deployment.parameters` | `_parameters_merge` |
| 03 | `serviceNameOverrides[*]` | `Deployment.service_name_overrides` | `_service_name_overrides` |
| 04 | `components[*].name`/`envVars` | `Deployment.config.components` | `_components_env_vars` |
| 05 | `envVars` (top-level) | `Deployment.config.env_vars` | `_env_vars` |
| 06 | `ipWhitelist` | `Deployment.config.ip_whitelist` | `_ip_whitelist` |
| 07 | `dedicatedIngress` | `Deployment.config.dedicated_ingress` | `_dedicated_ingress` |
| 08 | `scheduling.resources.requests` | `Deployment.config.scheduling.resources.requests` | `_scheduling_resources_requests` |
| 09 | `scheduling.tolerations` | `Deployment.config.scheduling.tolerations` | `_scheduling_tolerations` |
| 10 | `scheduling.topologySpreadConstraints` | `Deployment.config.scheduling.topology_spread_constraints` | `_scheduling_topology_spread` |
| 11 | `scheduling.podAffinity` | `Deployment.config.scheduling.pod_affinity` | `_scheduling_pod_affinity` |
| 12 | `scheduling.runtimeClass` | `Deployment.config.scheduling.runtime_class` | `_scheduling_runtime_class` |
| 13 | `scheduling.inject` | `Deployment.config.scheduling.inject` | `_scheduling_inject` |
| 14 | `fqdnSuffix` | `Deployment.config.fqdn_suffix` | `_fqdn_suffix` |
| 15 | `externalUrlScheme` | `Deployment.config.external_url_scheme` | `_external_url_scheme` |
| 16 | `externalUrlPort` | `Deployment.config.external_url_port` | `_external_url_port` |
| 17 | `externalDnsEndpointsType` | `Deployment.config.external_dns_endpoints_type` | `_external_dns_endpoints_type` |
| 18 | `ingressClass` | `Deployment.config.ingress_class` | `_ingress_class` |
| 19 | `dbSize` | `Deployment.config.db_size` | `_db_size` |
| 20 | `runtimeClass` | `Deployment.config.runtime_class` | `_runtime_class` |
| 21 | `nodeSelector` | `Deployment.config.node_selector` | `_node_selector` |
| 22 | `standardStorage.storageClass` | `Deployment.config.standard_storage.storage_class` | `_standard_storage` |

Rows 02 (parameters merge) and 04 (components.envVars) need the test body to **also** assert the merge / flatten semantics, not just round-trip.

## 5. Error-propagation matrix (FR-008, FR-009; SC-002)

| # | Input scope | Trigger | Expected `extensions.code` |
|---|---|---|---|
| E1 | Top-level `envVars` | invalid name (e.g. `1invalid`) | `INVALID_ENV_VAR_NAME` |
| E2 | `components[].envVars` | invalid name | `INVALID_ENV_VAR_NAME` (with component scope in payload) |
| E3 | Top-level `envVars` | duplicate name | `DUPLICATE_ENV_VAR_NAME` |
| E4 | `components[].envVars` | duplicate name | `DUPLICATE_ENV_VAR_NAME` (with component scope in payload) |
| E5 | Top-level `envVars` | value exceeds size limit | `ENV_VAR_SIZE_LIMIT_EXCEEDED` |
| E6 | `components[].envVars` | value exceeds size limit | `ENV_VAR_SIZE_LIMIT_EXCEEDED` (with component scope in payload) |
| E7 | `components[]` | unknown component name (not declared by driver version) | `UNKNOWN_COMPONENT_ENV_VAR` |
| E8 | `parameters` | duplicate name | `DUPLICATE_PARAMETER_NAME` |
| E9 | `components[]` | duplicate `name` | `DUPLICATE_COMPONENT_NAME` |

Each row is one mandatory test under `backend/tests/functional/graphql/test_update_deployment_input_errors.py`.

## 6. Schema-introspection assertions (SC-001, SC-003)

Add two unit tests under `backend/tests/functional/graphql/test_update_deployment_input_introspection.py`:

- **`test_update_deployment_input_field_coverage`** — asserts the set of fields on `UpdateDeploymentInput` (camelCase) equals `set(DeploymentConfig.model_fields) ∪ {"name", "parameters", "serviceNameOverrides"}` (snake_case → camelCase normalized).
- **`test_update_deployment_arguments_have_no_json_typed_args`** — asserts the `updateDeployment` mutation argument list contains zero arguments whose GraphQL type is `JSON` (the previous `config: JSON` and `parameters: JSON` are gone).

## 7. Behaviour-regression coverage (SC-004)

The existing functional tests in `backend/tests/functional/graphql/test_deployment.py` and `backend/tests/functional/graphql/test_env_vars_propagation.py` are retargeted to the new input shape and must continue to pass unchanged-in-meaning. No new tests required for SC-004; the existing ones, plus the propagation matrix above, plus the E2E from §7 of `research.md`, together satisfy the criterion.

## 8. SDK contract (FR-010)

After `uv run invoke generate`, the SDK exposes:

```python
class UpdateDeploymentInput(BaseModel):
    name: str | None = None
    parameters: list[ParameterValueInput] | None = None
    service_name_overrides: list[ServiceNameOverrideInput] | None = None
    components: list[ComponentConfigInput] | None = None
    env_vars: list[EnvVarInput] | None = None
    # ... all other fields from §1.1

class StyrminClient:
    class deployments:
        async def update(
            self, deployment_id: UUID, *, input: UpdateDeploymentInput
        ) -> Task: ...
```

No `dict`-typed `config` or `parameters` parameters on the SDK method (FR-010 assertion).

## 9. Frontend contract (FR-011)

After `pnpm run codegen`:

- `useUpdateDeploymentMutation()` accepts `{ deploymentId: string; input: UpdateDeploymentInput }` instead of the previous `{ deploymentId; name?; config?; parameters?; serviceNameOverrides? }`.
- `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx` is updated to construct the typed input via a new helper `deploymentConfigToInput(config)` in `frontend/src/lib/deployment-input.ts`. The helper converts the read-API config dict (with dict-shaped `envVars` and `components`) to the input list-shape; the dialog then mutates the scheduling field on the converted input and submits.
