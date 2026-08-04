# Phase 1 Data Model: Infrahub MCP Server Application Driver

No new persisted entity types are introduced. This Driver instantiates **existing** concepts. The "data model" here is the structure of the Driver manifest as parsed into existing Pydantic models.

## Entities (all existing types; new instances only)

### Driver (`DriverSpec`) — new instance `infrahub-mcp`

| Field | Value | Source model |
|-------|-------|--------------|
| `metadata.name` | `infrahub-mcp` | `DriverSpec` |
| `spec.version` | `"1"` | `DriverSpec.spec` |
| `spec.supported_versions` | `">=1.1,<2.0"` | semver specifier |
| `spec.info` | description + upstream links (Homepage, Docs, GitHub) | `info` block |
| `spec.helm.main.location` | `oci://registry.opsmill.io/opsmill/chart/infrahub-mcp` *(confirm at impl)* | `helm.main` |
| `spec.helm.main.version` | `0.1.0` *(confirm at impl)* | `helm.main` |
| `spec.actions` | `[]` (none) | deserializes to empty list |

### Component — single `server`

| Field | Value |
|-------|-------|
| name | `server` |
| `identifier.label` | `app.kubernetes.io/name: infrahub-mcp` *(confirm selector at impl)* |
| backup | none (not declared) |

### Service — single `infrahub-mcp`

| Field | Value |
|-------|-------|
| `name` | `infrahub-mcp` |
| `kind` | `http` |
| `scope` | `internal` |
| `port` | `8001` |
| `component` | `server` |

Materialises as a `DeployedService` + Kubernetes Service via existing machinery.

### Parameters (`DriverParameterDefinition` × 3)

| `name` | `kind` | `default` | `values` | Required? | Maps to (rendered) |
|--------|--------|-----------|----------|-----------|--------------------|
| `infrahub_address` | `string` | *(none)* | — | **Yes** (no default ⇒ required) | `infrahub.address` |
| `mcp_read_only` | `boolean` | `false` | — | No | `mcp.readOnly` |
| `mcp_log_level` | `enum` | `info` | `["debug","info","warning","error"]` | No | `mcp.logLevel` |

**Validation rules** (all enforced by existing `validate_parameter_values`):

- `infrahub_address` omitted → `ServiceError: Missing required parameter: 'infrahub_address'`.
- Unknown parameter name → `ServiceError: Unknown parameter: '<name>'`.
- `mcp_read_only` non-boolean → `ServiceError` (type mismatch).
- `mcp_log_level` outside the enum → `ServiceError` (value not in allowed values).
- Defaults applied when omitted: `mcp_read_only=false`, `mcp_log_level="info"`.

**Manifest-load rules** (enforced by `DriverParameterDefinition.validate_parameter`):

- `mcp_log_level` enum requires non-empty `values`; default `"info"` must be a member (it is).
- Non-enum params must not declare `values` (none do).

### Fixed, non-parameter values (rendered, not operator-settable)

| Rendered key | Value | Rationale |
|--------------|-------|-----------|
| `fullnameOverride` | `styrmin-infrahub-mcp` | `DRIVERS.md` naming convention |
| `mcp.authMode` | `token-passthrough` | FR-004 fixed; FR-006 no stored credential |

### Explicitly absent

- **No** token parameter; **no** `infrahub.apiToken` (or any `apiToken`) key in rendered values (FR-006, SC-004).
- **No** `actions` / `actions.py` (FR-005).
- **No** `container_overrides`, **no** `backup`, **no** external/ingress Service.
