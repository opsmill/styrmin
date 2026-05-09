# Phase 0 Research: Env-Config Input Completeness + Validator Hardening

## 1. Schema-walking input completeness propagation test (US1 / FR-002)

**Decision**: Implement the propagation test as a runtime assertion that introspects both `EnvironmentConfig` (Pydantic model) and `UpdateEnvironmentInput` (Strawberry input) and asserts every public Pydantic field has a corresponding Strawberry input field with the same camelCase name. The test lives at `backend/tests/functional/graphql/test_environment_update_propagation.py` next to the existing per-field propagation tests.

**Mechanism**:

```python
def test_update_environment_input_covers_every_environment_config_field():
    """Schema-walking completeness check (FR-002).

    Walks `EnvironmentConfig.model_fields` (Pydantic) and asserts that for every
    field, an equivalently-named Strawberry field exists on `UpdateEnvironmentInput`.
    Future schema drift — e.g., adding a field to `BaseConfigSection` without
    updating the input — fails this test with a precise message.
    """
    from styrmin_backend.context.models.config import EnvironmentConfig
    from styrmin_backend.api.definitions.environment.inputs import UpdateEnvironmentInput

    # Strawberry exposes its field names via __strawberry_definition__.
    input_field_names = {
        f.python_name for f in UpdateEnvironmentInput.__strawberry_definition__.fields
    }
    pydantic_field_names = set(EnvironmentConfig.model_fields.keys())

    # The input may have additional fields (e.g. helper inputs) but every
    # Pydantic field MUST have a corresponding input field.
    missing = pydantic_field_names - input_field_names
    assert not missing, (
        f"UpdateEnvironmentInput is missing {missing} — every EnvironmentConfig "
        f"field MUST have a corresponding input field (FR-002). Add the field to "
        f"backend/styrmin_backend/api/definitions/environment/inputs.py."
    )
```

**Rationale**: This is a structural guarantee, not a per-field per-value test. It cheaply prevents the exact class of bug 011 fixes (a field on Pydantic with no Strawberry counterpart) from recurring. The test runs as part of the propagation suite; failure messages name the missing field explicitly.

**Alternatives considered**:

- *Static analysis via a custom ruff/ty rule*: rejected — too much infrastructure for a single check.
- *Add a CI step that diffs the schema*: rejected — schema regen catches the field at codegen time but doesn't enforce that every Pydantic field IS in the schema; the test catches both directions.
- *Per-field manual propagation test*: rejected — the existing per-field tests stay (per FR-018 of 009), but adding a per-field test for every future Pydantic field puts the maintenance burden on the wrong side. The schema-walk is fail-on-drift; per-field tests are fail-on-regression.

**Reference**: `backend/styrmin_backend/api/definitions/environment/inputs.py` (the input being asserted against), `backend/styrmin_backend/context/models/config.py` (`EnvironmentConfig` and `BaseConfigSection`).

## 2. Page-object vs UI-driver-method (US4 / FR-012)

**Decision**: Extend the existing `ui_driver.py` (`backend/tests/e2e/drivers/ui_driver.py`) with `update_environment_via_form(environment_id, env_vars)` method. Do NOT introduce a separate `EnvironmentDetailPage` Playwright page object class.

**Rationale**: The project's established pattern is the `ScenarioDriver` Protocol with `api_driver.py` + `ui_driver.py` implementations. Both implementations expose the SAME method signatures (e.g., `create_deployment`, `update_deployment`); tests parametrise over the protocol and run under both variants automatically. Introducing a separate `EnvironmentDetailPage` class would:

- Break the dual-entrypoint pattern — the `api_driver` doesn't have a "detail page", so tests using `EnvironmentDetailPage` couldn't be parametrised.
- Add a new infrastructure surface for one method's worth of work.
- Violate AGENTS.md's "tests calling `scenario_driver.*` exercise both UI and API code paths" — a separate page object would be UI-only by construction.

The spec uses the name `EnvironmentDetailPage` illustratively (it's how 009's T061 phrased the dependency); the implementer lands the actual capability as a `ui_driver` method matching the existing protocol shape. The `api_driver`'s parallel implementation may simply call `client.environments.update(input=...)` — the parametrisation lets T061 run under both variants.

**Method shape**:

```python
# backend/tests/e2e/drivers/ui_driver.py
async def update_environment_via_form(
    self,
    *,
    environment_id: str,
    env_vars: dict[str, str],
) -> None:
    """Drive the env-vars edit form on the Configuration tab.

    Steps:
    1. Navigate to /environments/{environment_id}.
    2. Click the Configuration tab.
    3. For each (name, value): click "Add Variable", fill the row.
    4. Click Save; the redeploy confirm dialog opens.
    5. Click "Redeploy" in the dialog.
    6. Wait for the page to refresh with the new state visible.
    """
```

The `api_driver`'s parallel:

```python
# backend/tests/e2e/drivers/api_driver.py
async def update_environment_via_form(
    self,
    *,
    environment_id: str,
    env_vars: dict[str, str],
) -> None:
    """API-side equivalent: submit through the typed mutation."""
    # Construct UpdateEnvironmentInput from existing config + env_vars
    # and submit via client.environments.update.
```

**Alternatives considered**:

- *Separate `EnvironmentDetailPage` class instantiated by the test*: rejected — breaks the dual-entrypoint protocol, see above.
- *Page-object methods on `ui_driver` BUT NOT on `api_driver`* (so the test runs only under `[ui-chromium]`): rejected — that's the same shape as the broken `api_only` markers we're trying to clean up. Symmetric methods on both drivers IS the pattern.

**Reference**: `backend/tests/e2e/drivers/protocol.py` (the protocol the methods must satisfy), `backend/tests/e2e/drivers/ui_driver.py` (existing page-object-style methods to mirror), `backend/tests/e2e/drivers/api_driver.py` (existing API-side parallel).

## 3. The `api_only` marker audit landscape

**Decision**: Apply AGENTS.md's heuristic literally. Walk every E2E in `backend/tests/e2e/` (not just env-vars-related); any test that calls a `scenario_driver.*` method that's listed in the heuristic ("`create_deployment` / `upgrade_deployment` / `create_backup` / `start_components` / etc.") AND is currently marked `api_only` has the marker removed.

**Initial inventory** (from recon in Phase 0):

| File | api_only marker count | Likely-misapplied count |
|---|---|---|
| `backend/tests/e2e/test_deployment_env_vars.py` | 5 (4 active + 1 inside the skipped US5 block) | 4-5 (most call `scenario_driver.update_deployment`) |
| `backend/tests/e2e/test_environment_update.py` | 4 (3 active + 1 inside the skipped T061 block) | 3-4 (most call `scenario_driver.update_environment` once added) |

**Total**: 9 markers; conservative estimate 7-9 are misapplied.

**Audit procedure** (codified in `tasks.md`):

1. For each `@pytest.mark.api_only` decorator in `backend/tests/e2e/`, inspect the wrapped test body.
2. If the test body calls any method on `scenario_driver` from the heuristic list (search for `scenario_driver.create_*`, `.update_*`, `.upgrade_*`, `.start_*`, `.stop_*`, `.run_*`, `.create_backup`, `.delete_*`), the marker is misapplied → remove it.
3. If the test body does NOT call those methods (e.g., it only uses `client.X.Y()` SDK calls or `kubectl`/`kr8s` directly), the marker stays — and the implementer adds an inline comment per FR-015 documenting WHY this specific test is api-only.
4. Document the resulting marker landscape in the auto-implement report.

**Alternatives considered**:

- *Audit only env-vars-related E2Es*: rejected — the policy applies project-wide; doing the cleanup in scope means future env-config tests don't inherit the same bug.
- *Replace `api_only` with `skip_ui_chromium` for tests where the UI variant genuinely doesn't add coverage*: deferred to a future infrastructure-level decision; out of scope here.

**Reference**: `AGENTS.md` § "Dual-entrypoint scope — mark `api_only` when there's no UI flow".

## 4. Validator type-check shape (US3 / FR-008..FR-011)

**Decision**: Add the type guard at the top of `validate_env_var_value` (before any encoding or size computation):

```python
def validate_env_var_value(name: str, value: str, scope: str | None = None) -> None:
    if not isinstance(value, str):
        raise InvalidEnvVarValueError(
            name=name,
            value_type=type(value).__name__,
            scope=scope,
        )
    # ... existing 64 KiB cap check ...
```

Plus a parallel guard in `validate_env_vars_dict` if dict-level callers can bypass `validate_env_var_value`. Also a guard on the dict KEYS (the existing name regex catches non-string keys via `re.match`'s TypeError, but the typed error would be friendlier).

**Rationale**: The check is at the entry point so every downstream operation (encoding, size summation, byte total) runs against typed-correct inputs. The new typed error matches the 008 catalog's shape — `error_code` + `error_metadata` projected through `StructuredErrorExtension`.

**Edge case — `bool` is `int`**: `True` and `False` are instances of `int` (not `str`). `isinstance(value, str)` correctly rejects them.

**Edge case — the existing JSON parser at the GraphQL layer might already coerce some values**: per the spec FR-011, the validator is the canonical type-check site. Even if upstream layers happen to coerce, the validator MUST type-check independently — defense in depth.

**Alternatives considered**:

- *Coerce non-string values to strings (`str(value)`)*: rejected — silently corrupts intent. An operator who passes `1` likely meant `"1"`, but maybe meant `1` and didn't realise env var values must be strings — the typed error tells them.
- *Catch `AttributeError` and re-raise as the typed error*: rejected — the intent is to never reach `_utf8_bytes` with a non-string. Catching after the fact relies on `AttributeError` semantics that could shift if Python's str-protocol changes.

**Reference**: `backend/styrmin_backend/services/env_vars/validator.py` (the function being modified), `backend/styrmin_backend/services/env_vars/exceptions.py` (error catalog).

## 5. Frontend enum value-transform implementation shape

**Decision**: Add a private helper `transformEnumValue<E extends string>(field: string, value: unknown, mapping: Record<string, E>): E | null` in `EnvironmentConfigurationTab.tsx`, called from `buildFullReplacementInput` for each enum field. The mapping is the explicit Pydantic-string → GraphQL-literal table:

```typescript
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
    if (value == null) return null;  // unset
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

Used in `buildFullReplacementInput`:

```typescript
externalUrlScheme: transformEnumValue(
    "externalUrlScheme",
    config.external_url_scheme,
    EXTERNAL_URL_SCHEME_MAP,
),
externalDnsEndpointsType: transformEnumValue(
    "externalDnsEndpointsType",
    config.external_dns_endpoints_type,
    EXTERNAL_DNS_ENDPOINTS_TYPE_MAP,
),
```

The throw-on-unrecognised-value ensures FR-006: the form raises a clear error before submitting corrupt data. The form's existing error-display path catches the throw and shows the message to the operator.

**Rationale**: A single helper covers both enum fields (and any future enum field added to the input). The mappings are declarative tables that future maintainers update when new enum values land — matched to the Pydantic source of truth.

**Alternatives considered**:

- *Generated enum-value-mapping table from the schema codegen*: rejected — adds codegen complexity for a 4-entry mapping. Manually maintained tables are clearer.
- *Try/catch around the throw and submit anyway with `null`*: rejected — silent corruption is exactly the bug we're fixing.

**Reference**: `frontend/src/pages/environments/EnvironmentConfigurationTab.tsx:165` (the existing `buildFullReplacementInput`), `frontend/src/generated/graphql.ts` (regenerated TypeScript enums).

## 6. Testing strategy

| Test bundle | Layer | Coverage |
|---|---|---|
| `test_environment_update_propagation.py` (extend) | Propagation | Per-field round-trip for `ingressClass` + `dbSize` (US1); the schema-walking completeness test (FR-002); `INVALID_ENV_VAR_VALUE` rejection on JSON config write paths (US3 / FR-011). |
| `test_validator.py` (extend) | Unit | Type-check rejection for `int`, `float`, `bool`, `None`, `bytes`, `list`, `dict` values (US3 / FR-009). String values continue to pass through. |
| `EnvironmentConfigurationTab.test.tsx` (extend) | Frontend Vitest | `buildFullReplacementInput` correctly transforms `external_url_scheme: "https"` → `HTTPS`; same for `external_dns_endpoints_type`; unrecognised value throws; `null`/missing values produce `null` in the input (US2 / FR-004..FR-007). |
| `test_environment_update.py::test_us4_env_vars_form_redeploys_environment` (un-skip) | E2E `[ui-chromium]` + `[api-chromium]` | T061 from 009 runs against a real cluster (US4 / FR-013). Uses the new `update_environment_via_form` driver method. |
| Marker audit (`backend/tests/e2e/test_*env*.py`) | E2E | After cleanup, marker count drops by ≥50% from today's 9 (US4 / FR-014); each retained marker has an inline justification (FR-015). |

**Prior art**: 008's E2E + propagation patterns; 009's `EnvironmentConfigurationTab.test.tsx`; the existing `ui_driver.py` driver methods.

## 7. Out of scope (explicit)

- Backwards-compat shims for the prior incomplete `UpdateEnvironmentInput`. Clean schema addition; existing callers that didn't write these fields keep working.
- Read-side enum value transformation in the frontend.
- Reverting the 009 H2 nested-clearing block on the form (still guards `dedicatedIngress`/`scheduling`).
- Inverse direction tests (backend → frontend value mapping for read display).
- Migration of `updateDeployment(config: JSON)` to a typed input. The validator hardening (US3) protects this still-active write path; converting it to typed input is a separate scope.
- Per-field propagation test additions for `ip_whitelist`, `fqdn_suffix`, etc. — those are covered by 009's existing per-field propagation tests; only the new fields (`ingressClass`, `dbSize`) get new per-field tests in 011.
