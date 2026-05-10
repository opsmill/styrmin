# Quickstart: Env-Config Input Completeness + Validator Hardening

This walk-through validates 011 end-to-end. Each step has a corresponding assertion in the test suite.

## Prerequisites

- A running Styrmin dev stack (`uv run invoke dev-validate`).
- `kubectl` pointed at the dev cluster.

## Step 1 — `ingressClass` + `dbSize` round-trip (US1)

Through the SDK:

```python
await client.environments.update(
    environment_id=staging_id,
    input=UpdateEnvironmentInput(
        env_vars=[EnvVarInput(name="LOG_LEVEL", value="debug")],
        ingress_class="nginx",
        db_size="10Gi",
    ),
)
```

Then read back:

```python
env = await client.environments.get(environment_id=staging_id)
assert env.config["ingress_class"] == "nginx"
assert env.config["db_size"] == "10Gi"
assert env.config["env_vars"] == {"LOG_LEVEL": "debug"}
```

**Expected**: all three fields persist. Pre-011, omitting `ingress_class` from a subsequent update would silently clear it; post-011, it persists when carried through.

## Step 2 — Schema-walking propagation test prevents future drift (US1 / FR-002)

Run the propagation suite:

```bash
uv run pytest backend/tests/functional/graphql/test_environment_update_propagation.py::test_update_environment_input_covers_every_environment_config_field -v
```

**Expected**: green. To exercise the failure mode, temporarily add a field to `EnvironmentConfig` without adding the corresponding input field. The test fails with `UpdateEnvironmentInput is missing {'<new_field>'} — every EnvironmentConfig field MUST have a corresponding input field`.

Revert the temporary change before continuing.

## Step 3 — Frontend enum value-transform (US2)

Pre-seed an environment with the enum fields set:

```python
await client.environments.update(
    environment_id=staging_id,
    input=UpdateEnvironmentInput(
        env_vars=[],
        external_url_scheme=ExternalUrlScheme.HTTPS,
        external_dns_endpoints_type=ExternalDnsEndpointsType.NODE_EXTERNAL_IP,
    ),
)
```

Read back; persisted JSON config now has `external_url_scheme: "https"` and `external_dns_endpoints_type: "NodeExternalIP"` (Pydantic-side raw strings).

Open the Configuration tab in a browser, add an env var, click Save and confirm the redeploy dialog.

**Expected**: the mutation succeeds. Post-reconcile, the persisted config still has the same enum values (`"https"` and `"NodeExternalIP"`). Pre-011, the form would have submitted `externalUrlScheme: "https"` (lowercase string) which the GraphQL enum would reject.

To exercise the unrecognised-value path: in the browser console (post-form-render), inject a corrupt config value (e.g., `external_url_scheme: "wss"`). Click Save. **Expected**: an inline error appears — "Field externalUrlScheme: unrecognised value 'wss'" — and the form does not submit.

## Step 4 — Validator type-check (US3)

Through the SDK against the JSON config write path:

```python
try:
    await client.deployments.deploy(
        driver="simple-app",
        environment_id=staging_id,
        config={"env_vars": {"BAD": 1}},  # int value
    )
except ServiceError as e:
    assert e.error_code == "INVALID_ENV_VAR_VALUE"
    assert e.error_metadata["name"] == "BAD"
    assert e.error_metadata["value_type"] == "int"
```

**Expected**: typed error code surfaced; no 500.

Variations to verify the same path:

- `{"BAD": None}` → `value_type: "NoneType"`
- `{"BAD": [1, 2]}` → `value_type: "list"`
- `{"BAD": {"a": 1}}` → `value_type: "dict"`
- `{"BAD": True}` → `value_type: "bool"`
- `{"BAD": 1.5}` → `value_type: "float"`
- `{"BAD": b"bytes"}` → `value_type: "bytes"`

Each surfaces `extensions.code = "INVALID_ENV_VAR_VALUE"` at the GraphQL boundary.

## Step 5 — UI E2E unblocked (US4)

Run T061:

```bash
uv run pytest backend/tests/e2e/test_environment_update.py::test_us4_env_vars_form_redeploys_environment -v -s
```

**Expected**: both `[api-chromium]` and `[ui-chromium]` variants pass. The UI variant exercises the full Playwright form flow via the new `update_environment_via_form` driver method.

## Step 6 — `api_only` marker audit (US4)

Count the markers:

```bash
grep -c "@pytest.mark.api_only" backend/tests/e2e/test_deployment_env_vars.py backend/tests/e2e/test_environment_update.py
```

**Expected**: substantially fewer than today's 9 (target ≥50% reduction per SC-005). Each retained marker has an inline justification comment.

Verify the dual-entrypoint runs are working:

```bash
uv run pytest backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var -v
```

**Expected**: collected under both `[api-chromium]` and `[ui-chromium]` variants (not just `[api-chromium]` as pre-011).

## Failure-mode checklist

| Symptom | Likely cause |
|---|---|
| Propagation test `test_update_environment_input_covers_every_environment_config_field` fails after a Pydantic model change | A new `EnvironmentConfig` field was added without a corresponding `UpdateEnvironmentInput` field. Add the input field. |
| Frontend form submission fails with "Field externalUrlScheme: unrecognised value" | The persisted config has a corrupt or future-added enum value not in the frontend's mapping table. Update the mapping in `EnvironmentConfigurationTab.tsx`. |
| Validator returns `INVALID_CONTEXT` instead of `INVALID_ENV_VAR_VALUE` | Type guard isn't running before Pydantic validation — check the entry-point order in `validate_env_vars_dict`. |
| T061 collects under `[api-chromium]` only | The `api_only` marker on T061 wasn't removed during the audit; or the `update_environment_via_form` method isn't on both `api_driver` and `ui_driver`. |
