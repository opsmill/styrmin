# GraphQL Contract: Env-Config Input Completeness + Validator Hardening

This contract is **additive** for the schema (two new input fields, no removals) and **purely-additive** for the propagation matrix (three new rows; no removals).

## 1. New input fields on `UpdateEnvironmentInput`

```graphql
extend input UpdateEnvironmentInput {
  ingressClass: String
  dbSize: String
}
```

These map to `EnvironmentConfig.ingress_class` and `EnvironmentConfig.db_size` (both inherited from `BaseConfigSection`). Nullable per the existing convention; null = "field unset on persisted config" under full-replacement semantics.

## 2. New error code

```python
# Added to backend/styrmin_backend/api/errors.py:ErrorCode enum
INVALID_ENV_VAR_VALUE = "INVALID_ENV_VAR_VALUE"
```

Surfaces at the GraphQL boundary as `extensions.code = "INVALID_ENV_VAR_VALUE"` for any `validate_env_vars_dict` invocation that receives a non-string value. The error is raised by `services/env_vars/validator.py` and projected by `StructuredErrorExtension` (no `INVALID_CONTEXT` collapse — the entry-point type guard prevents reaching the wrapping path).

## 3. Preserved schema (no changes)

Every other env-vars-related GraphQL surface from 008+009+010 stays exactly as it was:

- `EnvVar` / `EnvVarInput` / `ComponentEnvVars` / `DriverEnvVarDoc` / `DriverEnvVarLevel`.
- `Environment.envVars`, `Deployment.envVars`, `Deployment.componentEnvVars`, `ApplicationDriverVersion.envVars`.
- `UpdateEnvironmentInput.envVars`, `.ipWhitelist`, `.dedicatedIngress`, `.scheduling`, `.fqdnSuffix`, `.externalUrlScheme`, `.externalUrlPort`, `.externalDnsEndpointsType`.
- `Mutation.updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!): Environment`.

## 4. Propagation matrix delta

Three new rows added; no rows removed.

| Row | Type | Test name | Assertion |
|---|---|---|---|
| `UpdateEnvironmentInput.ingressClass` round-trip | per-field | `test_update_environment_ingress_class_round_trip` | Submit `{ ingressClass: "nginx" }` → query `Environment.config.ingressClass = "nginx"`. |
| `UpdateEnvironmentInput.dbSize` round-trip | per-field | `test_update_environment_db_size_round_trip` | Submit `{ dbSize: "10Gi" }` → query `Environment.config.dbSize = "10Gi"`. |
| Schema-walking input completeness | structural | `test_update_environment_input_covers_every_environment_config_field` | Every public `EnvironmentConfig` Pydantic field has a corresponding camelCase Strawberry input field. Fails on future drift. |
| `INVALID_ENV_VAR_VALUE` rejection (deploy) | rejection-path | `test_deploy_rejects_non_string_env_var_value` | `deploy(config: { env_vars: { X: 1 } })` → `extensions.code = "INVALID_ENV_VAR_VALUE"`. |
| `INVALID_ENV_VAR_VALUE` rejection (updateDeployment) | rejection-path | `test_update_deployment_rejects_non_string_env_var_value` | Same shape, on the still-active JSON config write path. |

The third row (schema-walking completeness) is the load-bearing one for FR-002 — it prevents future drift from re-introducing 011's exact bug.

## 5. Backwards compatibility

This is a **purely additive schema change**. Existing callers that submitted `UpdateEnvironmentInput` without `ingressClass` / `dbSize` still work — those fields default to null per Strawberry's nullable-input semantics. Existing callers that didn't trigger the validator type-check bug see no behaviour change.

## 6. SDK + frontend regen

After the schema addition (US1), the standard `uv run invoke generate` regenerates:

- `python_sdk/src/styrmin_sdk/graphql/_generated/input_types.py` — `UpdateEnvironmentInput` Pydantic mirror gains `ingress_class` + `db_size`.
- `frontend/src/generated/graphql.ts` — TypeScript `UpdateEnvironmentInput` type gains the two fields.

The frontend's `buildFullReplacementInput` is updated by hand (US2) to USE the new fields and to apply the enum value-transform — the codegen produces the type definitions but doesn't touch the form's submit logic.
