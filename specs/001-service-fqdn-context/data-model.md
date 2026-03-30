# Data Model: Include Service FQDNs in Deployment Context

**Phase 1 output** | **Date**: 2026-03-28

## Entity Changes

### 1. ServiceReference (Context Model) — MODIFIED

**File**: `backend/styrmin_backend/context/models/services.py`

**Purpose**: Template-facing model used in deployment context. Accessed by driver templates via `{{ services['name'].primary_fqdn }}`.

| Field | Type | Change | Description |
|-------|------|--------|-------------|
| `host` | `str` | Existing | DNS name of the service |
| `port` | `int` | Existing | Service port number |
| `kind` | `str` | Existing | Service kind (http, https, tcp, udp) |
| `url` | `str` (computed) | Existing | Computed URL from kind + host + port |
| `primary_fqdn` | `str \| None` | **NEW** | UUID-based FQDN: `{sanitized-app-name}-{deployment-id}.{fqdn-suffix}` |
| `human_readable_fqdn` | `str \| None` | **NEW** | Environment-name-based FQDN: `{sanitized-host}-{sanitized-env}.{fqdn-suffix}` |

**Validation rules**:
- Both FQDN fields default to `None`
- `None` when `fqdn_suffix` is not configured (FR-006)
- When set, all label components are DNS-safe (FR-004)

### 2. DeployedService (GraphQL Type) — MODIFIED

**File**: `backend/styrmin_backend/api/definitions/service/model.py`

**Purpose**: Strawberry GraphQL type exposed to the frontend.

| Field | GraphQL Type | Change | Description |
|-------|-------------|--------|-------------|
| `id` | `UUID!` | Existing | |
| `driverServiceName` | `String!` | Existing | |
| `resolvedName` | `String!` | Existing | |
| `kind` | `String!` | Existing | |
| `scope` | `String!` | Existing | |
| `port` | `Int!` | Existing | |
| `component` | `String!` | Existing | |
| `deploymentId` | `UUID!` | Existing | |
| `primaryFqdn` | `String` | **NEW** | UUID-based FQDN (nullable) |
| `humanReadableFqdn` | `String` | **NEW** | Environment-name-based FQDN (nullable) |

**Resolution**: FQDNs are computed by the parent `Deployment.deployed_services()` resolver and injected into the type via a private attribute. No database column changes.

### 3. FQDN Utility Module — NEW

**File**: `backend/styrmin_backend/context/fqdn.py`

**Purpose**: Shared FQDN computation logic used by both context generation and API resolution.

**Functions**:

| Function | Signature | Description |
|----------|-----------|-------------|
| `to_fqdn_label` | `(value: str) -> str` | Sanitize string into valid DNS label. Extracted from `application.py`. |
| `compute_primary_fqdn` | `(app_name: str, deployment_id: str \| UUID, fqdn_suffix: str \| None) -> str \| None` | Compute UUID-based FQDN. Returns `None` if suffix is missing. |
| `compute_human_readable_fqdn` | `(service_host: str, environment_name: str, fqdn_suffix: str \| None) -> str \| None` | Compute environment-name-based FQDN. Returns `None` if suffix is missing. |

**Sanitization rules** (FR-004, implemented in `to_fqdn_label`):
1. Convert to lowercase
2. Replace non-alphanumeric characters (except hyphens) with hyphens
3. Collapse consecutive hyphens to single hyphen
4. Strip leading and trailing hyphens
5. Truncate to 63 characters

## Entities NOT Changed

### DeployedService (Database Model)

**File**: `backend/styrmin_backend/db/models.py`

**No changes**. FQDNs are computed at runtime, not stored. This avoids a database migration and ensures FQDNs always reflect the current config hierarchy.

### DeployedService (Domain Model)

**File**: `backend/styrmin_backend/domain/models.py`

**No changes**. The domain model represents persisted entity state. Since FQDNs are derived, they belong on the context model and API type, not the domain model.

### GlobalContext / InstanceContext / ResolvedConfig

**Files**: `backend/styrmin_backend/context/models/contexts.py`, `config.py`

**No changes**. The `fqdn_suffix` field already exists on `ResolvedConfig` and is correctly resolved through the config hierarchy. The context structure remains the same; only `ServiceReference` within it gains new fields.

## Data Flow

```text
Config hierarchy (cluster → environment → deployment)
        │
        ▼
  ResolvedConfig.fqdn_suffix
        │
        ├──────────────────────────┐
        ▼                          ▼
  Context Generation          API Resolution
  (services/context.py)       (api/definitions/service/model.py)
        │                          │
        ▼                          ▼
  ServiceReference             DeployedService (GraphQL)
  .primary_fqdn                .primaryFqdn
  .human_readable_fqdn         .humanReadableFqdn
        │                          │
        ▼                          ▼
  Driver Templates             Frontend UI
  (Jinja2 rendering)          (DeploymentDetailPage)
```

Both paths use `context/fqdn.py` for computation, ensuring consistency (SC-003).
