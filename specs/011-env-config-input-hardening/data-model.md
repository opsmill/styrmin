# Data Model: Env-Config Input Completeness + Validator Hardening

## 1. GraphQL input type changes

### 1.1 `UpdateEnvironmentInput` — two new scalar fields

```graphql
extend input UpdateEnvironmentInput {
  ingressClass: String
  dbSize: String
}
```

Both fields are nullable (the existing convention for full-replacement input fields). They map directly to `EnvironmentConfig.ingress_class` and `EnvironmentConfig.db_size` (both inherited from `BaseConfigSection`).

The Strawberry input → dict converter (`update_environment_input_to_dict` from 009) handles them via the same generic `__strawberry_definition__.fields` recursion that handles every other scalar field. **No converter change required.**

### 1.2 The full `UpdateEnvironmentInput` after this feature

```graphql
input UpdateEnvironmentInput {
  envVars: [EnvVarInput!]                          # 008+009
  ipWhitelist: [String!]                           # 009
  dedicatedIngress: DedicatedIngressInput          # 009
  scheduling: SchedulingInput                      # 009
  fqdnSuffix: String                               # 009
  externalUrlScheme: ExternalUrlScheme             # 009
  externalUrlPort: Int                             # 009
  externalDnsEndpointsType: ExternalDnsEndpointsType  # 009
  ingressClass: String                             # NEW (011)
  dbSize: String                                   # NEW (011)
}
```

Every public field of `EnvironmentConfig` now has a corresponding input field. The schema-walking propagation test (US1 / FR-002) enforces this invariant going forward.

## 2. New error type

### 2.1 `InvalidEnvVarValueError`

```python
# backend/styrmin_backend/services/env_vars/exceptions.py (addition)

class InvalidEnvVarValueError(ServiceError):
    """Raised when an env-var value is not a string.

    The value-side counterpart to InvalidEnvVarNameError. The validator
    cannot proceed with type-dependent operations (UTF-8 byte counting,
    size cap checks) on non-string values; rather than letting an
    AttributeError surface as a 500, we surface a typed error code at
    the GraphQL boundary.
    """

    error_code = "INVALID_ENV_VAR_VALUE"
    default_message = "env var value must be a string"

    def __init__(
        self,
        *,
        name: str,
        value_type: str,
        scope: str | None = None,
        message: str | None = None,
    ) -> None:
        self.name = name
        self.value_type = value_type
        self.scope = scope
        super().__init__(
            message
            or f"env var {name!r} (scope={scope!r}): expected str, got {value_type}",
        )

    @property
    def error_metadata(self) -> dict[str, str]:
        meta = {"name": self.name, "value_type": self.value_type}
        if self.scope is not None:
            meta["scope"] = self.scope
        return meta
```

Registered in `backend/styrmin_backend/api/errors.py:ErrorCode` enum as `INVALID_ENV_VAR_VALUE = "INVALID_ENV_VAR_VALUE"` so `StructuredErrorExtension` projects it.

### 2.2 Validator changes

```python
# backend/styrmin_backend/services/env_vars/validator.py (addition + entry-point guard)

def validate_env_var_value(name: str, value: str, scope: str | None = None) -> None:
    """Validate a single env var value. Raises InvalidEnvVarValueError when
    `value` is not a string; raises EnvVarSizeLimitExceededError when the
    UTF-8 byte length exceeds the 64 KiB cap.
    """
    if not isinstance(value, str):
        raise InvalidEnvVarValueError(
            name=name,
            value_type=type(value).__name__,
            scope=scope,
        )
    size = _utf8_bytes(value)
    if size > _PER_VALUE_BYTE_CAP:
        raise EnvVarSizeLimitExceededError(...)
```

Plus a parallel guard in `validate_env_vars_dict` for the dict iteration path (key check uses the existing name regex, which already rejects non-strings via TypeError; the typed error makes that path friendlier too — implementer adds `if not isinstance(name, str)` upstream of the regex).

## 3. Frontend value-transform layer

### 3.1 The transform helper

```typescript
// frontend/src/pages/environments/EnvironmentConfigurationTab.tsx (addition)

const EXTERNAL_URL_SCHEME_MAP: Record<string, ExternalUrlScheme> = {
    "http": ExternalUrlScheme.HTTP,
    "https": ExternalUrlScheme.HTTPS,
};

const EXTERNAL_DNS_ENDPOINTS_TYPE_MAP: Record<string, ExternalDnsEndpointsType> = {
    "NodeExternalIP": ExternalDnsEndpointsType.NODE_EXTERNAL_IP,
    "ClusterIP": ExternalDnsEndpointsType.CLUSTER_IP,
};

function transformEnumValue<E extends string>(
    field: string,
    value: unknown,
    mapping: Record<string, E>,
): E | null {
    if (value == null) return null;
    if (typeof value !== "string") {
        throw new Error(
            `Field ${field}: expected string, got ${typeof value}`,
        );
    }
    const transformed = mapping[value];
    if (transformed === undefined) {
        throw new Error(
            `Field ${field}: unrecognised value "${value}". ` +
            `Expected one of: ${Object.keys(mapping).join(", ")}`,
        );
    }
    return transformed;
}
```

### 3.2 `buildFullReplacementInput` after the change

```typescript
// frontend/src/pages/environments/EnvironmentConfigurationTab.tsx (modification)

function buildFullReplacementInput(
    config: Record<string, unknown>,
    envVars: EnvVar[],
): UpdateEnvironmentInput {
    return {
        envVars: envVars.map(({ name, value }) => ({ name, value })),
        ipWhitelist: (config.ip_whitelist as string[] | null | undefined) ?? null,
        dedicatedIngress: null,                                // unchanged 009 H2
        scheduling: null,                                       // unchanged 009 H2
        fqdnSuffix: (config.fqdn_suffix as string | null | undefined) ?? null,
        externalUrlScheme: transformEnumValue(                  // NEW (US2)
            "externalUrlScheme",
            config.external_url_scheme,
            EXTERNAL_URL_SCHEME_MAP,
        ),
        externalUrlPort: (config.external_url_port as number | null | undefined) ?? null,
        externalDnsEndpointsType: transformEnumValue(           // NEW (US2)
            "externalDnsEndpointsType",
            config.external_dns_endpoints_type,
            EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
        ),
        ingressClass: (config.ingress_class as string | null | undefined) ?? null,  // NEW (US1)
        dbSize: (config.db_size as string | null | undefined) ?? null,              // NEW (US1)
    };
}
```

The `dedicatedIngress` and `scheduling` fields stay at `null` per the 009 H2 contract (the form blocks submission when those are non-empty in the persisted config). `ingressClass` and `dbSize` move FROM "blocked by H2 because they were silently cleared" TO "carried through unchanged" — which the 009 H2 block must update to reflect (its set of blocked fields shrinks).

## 4. UI driver method (US4)

### 4.1 Protocol addition

```python
# backend/tests/e2e/drivers/protocol.py (addition)

class ScenarioDriver(Protocol):
    # ... existing methods ...

    async def update_environment_via_form(
        self,
        *,
        environment_id: str,
        env_vars: dict[str, str],
    ) -> None:
        """Update env vars on an environment.

        UI driver: drives the env-vars form on the Configuration tab.
        API driver: submits through the typed updateEnvironment mutation.

        Both implementations result in the same persisted state and the
        same per-deployment redeploy fanout per 009.
        """
        ...
```

### 4.2 `ui_driver.py` implementation

Drives the Playwright flow:
1. `page.goto("/environments/{environment_id}")`
2. `page.click("[role=tab]:has-text('Configuration')")`
3. For each `(name, value)`:
   - `page.click("button:has-text('Add Variable')")`
   - Fill the new row's `name` + `value` inputs
4. `page.click("button:has-text('Save')")`
5. Wait for the redeploy confirm dialog: `page.wait_for_selector("dialog:has-text('redeployed')")`
6. `page.click("dialog button:has-text('Redeploy')")`
7. Wait for the page to return to the read state with the new env vars visible.

### 4.3 `api_driver.py` implementation (parity contract per critique E1)

Reads the existing config, **round-trips it through `EnvironmentConfig.model_validate(config)`**, modifies the env_vars field, then constructs an `UpdateEnvironmentInput` from the validated Pydantic model and submits via `client.environments.update`. **No manual value-transform is required** — Pydantic's `Literal["http", "https"]` and `Literal["NodeExternalIP", "ClusterIP"]` types coerce the raw JSON strings into proper enum values automatically during `model_validate`. The frontend can't do this (TypeScript has no Pydantic equivalent), which is exactly why US2's manual transform exists in `buildFullReplacementInput`.

This means the api_driver and ui_driver reach the same persisted state through different mechanisms — the api_driver via Pydantic coercion, the ui_driver via the form's manual transform. **Any test parametrised over both drivers (notably T061) is the dual-entrypoint parity check** (per critique E2 — the parametrisation IS the parity verification; no separate parity test is needed).

Implementer note: the api_driver's read of existing config goes through `client.environments.get(...)` which post-009 returns a typed Pydantic model. The explicit `model_validate` round-trip in this driver is therefore mostly redundant but documents the contract that the driver tolerates raw-JSON config inputs and produces validated `UpdateEnvironmentInput` outputs.

## 5. Storage

No schema/DB changes. No migrations.

## 6. Errors

The error catalog after this feature:

| Error | Code | When |
|---|---|---|
| `InvalidEnvVarNameError` | `INVALID_ENV_VAR_NAME` | name regex fails (008) |
| `EnvVarSizeLimitExceededError` | `ENV_VAR_SIZE_LIMIT_EXCEEDED` | size cap exceeded (008) |
| `DuplicateEnvVarNameError` | `DUPLICATE_ENV_VAR_NAME` | duplicate name in input list (008) |
| `UnknownComponentEnvVarError` | `UNKNOWN_COMPONENT_ENV_VAR` | mutation references unknown component (008) |
| **`InvalidEnvVarValueError`** | **`INVALID_ENV_VAR_VALUE`** | **value is not a string (NEW — 011)** |
