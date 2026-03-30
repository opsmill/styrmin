# Quickstart: Include Service FQDNs in Deployment Context

**Phase 1 output** | **Date**: 2026-03-28

## Implementation Order

The implementation follows the user story priority order, with shared infrastructure built first.

### Step 1: Extract FQDN Utilities (Foundation)

**Create** `backend/styrmin_backend/context/fqdn.py`:
- Move `to_fqdn_label()` from `agent/service/kubernetes/resources/builders/application.py`
- Add `compute_primary_fqdn(app_name, deployment_id, fqdn_suffix) -> str | None`
- Add `compute_human_readable_fqdn(service_host, environment_name, fqdn_suffix) -> str | None`
- Both return `None` when `fqdn_suffix` is `None` or empty (FR-006)

**Modify** `agent/service/kubernetes/resources/builders/application.py`:
- Import `to_fqdn_label` from `context.fqdn` instead of defining locally
- Keep the Jinja2 filter registration unchanged

**Test**: `backend/tests/unit/context/test_fqdn.py`
- DNS sanitization edge cases (special chars, length, empty string)
- FQDN computation with valid suffix
- FQDN computation with `None`/empty suffix → returns `None`
- Truncation at 63-char DNS label limit

### Step 2: Add FQDNs to ServiceReference (Story 2 — P2)

**Modify** `backend/styrmin_backend/context/models/services.py`:
- Add `primary_fqdn: str | None = None` field
- Add `human_readable_fqdn: str | None = None` field

**Modify** `backend/styrmin_backend/services/context.py` in `generate_context_from_deployment()`:
- After building the `GlobalContext`, compute FQDNs for each service
- Use `context.instance.config.fqdn_suffix`, `context.app.name`, `context.instance.deployment_id`, `context.environment.name`
- Populate `ServiceReference.primary_fqdn` and `.human_readable_fqdn`

**Test**: Verify deployment context includes FQDN fields for services when suffix is configured, and `None` when not.

### Step 3: Expose FQDNs in GraphQL API (Story 1 — P1, depends on Step 1)

**Modify** `backend/styrmin_backend/api/definitions/service/model.py`:
- Add `primary_fqdn: str | None` and `human_readable_fqdn: str | None` private attributes to `DeployedService`
- Expose as Strawberry fields `primaryFqdn` and `humanReadableFqdn`

**Modify** `backend/styrmin_backend/api/definitions/deployment/model.py`:
- In `deployed_services()` resolver, load environment and cluster
- Resolve config hierarchy to get `fqdn_suffix`
- Load app name from deployment's driver version
- Compute FQDNs using shared utilities
- Pass to `DeployedService` instances

**Regenerate**:
```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
```

**Test**: Query deployment's `deployedServices` and verify `primaryFqdn` / `humanReadableFqdn` fields are returned correctly.

### Step 4: Display FQDNs in Frontend (Story 1 — P1, depends on Step 3)

**Modify** `frontend/src/pages/deployments/DeploymentDetailPage.tsx`:
- Add "Services" card section displaying each service's:
  - Service name (`driverServiceName`)
  - Primary FQDN (with "Not configured" fallback)
  - Human-readable FQDN (with "Not configured" fallback)
  - Port and kind
- Add query fields: `primaryFqdn`, `humanReadableFqdn`

**Test**: Visual verification and frontend unit test that the services card renders with/without FQDNs.

### Step 5: Migrate Driver Templates (Story 3 — P3, depends on Step 2)

**Modify** each driver template to replace inline FQDN construction with context fields:

| Driver | Current Pattern | New Pattern |
|--------|----------------|-------------|
| `infrahub` | `{{ app.name }}-{{ instance.deployment_id }}.{{ instance.config.fqdn_suffix }}` | `{{ services.infrahub.primary_fqdn }}` |
| `infrahub` | `{{ services.infrahub.host \| to_fqdn_label }}-{{ environment.name \| to_fqdn_label }}.{{ instance.config.fqdn_suffix }}` | `{{ services.infrahub.human_readable_fqdn }}` |
| `semaphore` | Same patterns with `services.semaphore` | Same approach |
| `simple-app` | Primary FQDN only | `{{ services.<name>.primary_fqdn }}` |
| `slurpit` | Primary FQDN only | `{{ services.<name>.primary_fqdn }}` |

**Note**: The `to_fqdn_label` filter remains available (FR-008) for any non-FQDN sanitization use cases.

**Test**: E2E — deploy each driver and verify rendered FQDN values are identical to pre-migration output.

## Key Design Decisions

1. **Compute, don't store**: FQDNs are derived from config hierarchy at runtime. No database migration needed.
2. **Shared utility**: `context/fqdn.py` is the single source of truth for FQDN computation, used by both context generation and API resolution.
3. **Nullable fields**: FQDNs are `None` when `fqdn_suffix` is unconfigured, not empty strings or error values.
4. **Parent resolver pattern**: The `Deployment.deployed_services()` resolver computes FQDNs once and injects them into all `DeployedService` instances, avoiding N+1 queries.

## Commands Reference

```bash
# Run backend tests
uv run invoke test

# Format and lint
uv run invoke format lint

# Regenerate GraphQL schema (after modifying Strawberry types)
uv run styrmin export graphql-schema schema.graphql

# Regenerate SDK types (after schema changes)
uv run invoke generate

# Run frontend tests
cd frontend && pnpm test
```
