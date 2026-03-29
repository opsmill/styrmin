# Research: Include Service FQDNs in Deployment Context

**Phase 0 output** | **Date**: 2026-03-28

## Research Tasks

### 1. Where are FQDNs currently constructed?

**Decision**: FQDNs are constructed inline in four driver templates using Jinja2 string concatenation.

**Findings**:
- `driver/examples/infrahub/chart_values.j2.yaml` — Both primary and human-readable FQDNs
- `driver/examples/semaphore/chart_values.j2.yaml` — Both primary and human-readable FQDNs
- `driver/examples/simple-app/chart_values.j2.yaml` — Primary FQDN only
- `driver/examples/slurpit/chart_values.j2.yaml` — Primary FQDN only
- `driver/examples/db-test/chart_values.j2.yaml` — No FQDN usage (database driver)

**Patterns found** (exactly two):
1. Primary (UUID-based): `{{ app.name }}-{{ instance.deployment_id }}.{{ instance.config.fqdn_suffix }}`
2. Human-readable: `{{ services.<name>.host | to_fqdn_label }}-{{ environment.name | to_fqdn_label }}.{{ instance.config.fqdn_suffix }}`

### 2. Where does `to_fqdn_label` live and how does it work?

**Decision**: Reuse existing implementation, extract to shared module.

**Findings**:
- Defined in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` (lines 40-46)
- Registered as Jinja2 filter in `get_jinja_environment()` (lines 54-59)
- Implementation: lowercase → replace non-alphanumeric with hyphens → collapse consecutive hyphens → strip leading/trailing hyphens → truncate to 63 chars
- Fully compliant with RFC 1035 DNS label rules

**Rationale**: The function is correct and complete. Extract to `context/fqdn.py` so it can be imported by both the builder (Jinja2 filter) and the context/API layer (FQDN computation). The builder will import from the new location.

### 3. Should FQDNs be stored in the database or computed at runtime?

**Decision**: Compute at runtime. No database changes.

**Rationale**:
- FQDNs depend on the `fqdn_suffix` from the resolved config hierarchy (cluster → environment → deployment)
- Config values can change independently of deployments (e.g., admin updates cluster config)
- Computed FQDNs are always fresh; stored FQDNs would need cache invalidation
- Avoids database migration and the associated governance gate
- FQDN computation is trivial (string concatenation + sanitization) — no performance concern

**Alternatives considered**:
- Store FQDNs on `DeployedService` in the database: Rejected because it introduces sync concerns when config hierarchy changes, requires migration, and adds no meaningful performance benefit.
- Store FQDNs only on `ApplicationInstance.context` JSON: Rejected because this only captures the snapshot at deployment time, not the current resolved state, and the frontend would need a different query path.

### 4. Where should FQDN computation happen in the architecture?

**Decision**: Two computation points, one shared utility.

**Findings**:
- **Context generation** (`services/context.py`): Compute FQDNs when building `ServiceReference` objects for the deployment context. This serves driver templates.
- **API resolution** (`api/definitions/service/model.py`): Compute FQDNs as Strawberry resolver fields on `DeployedService`. This serves the frontend.
- **Shared utility** (`context/fqdn.py`): Single function `compute_service_fqdns()` used by both paths. Contains `to_fqdn_label` and FQDN assembly logic.

**Rationale**: Follows the layered architecture principle. The context layer computes for drivers, the API layer computes for the frontend. Both use the same shared utility to ensure consistency (SC-003).

**Alternatives considered**:
- Compute only in context generation, then store for API: Rejected — couples two layers and reintroduces storage concerns.
- Compute in a service-layer function called by both: Considered, but the context generation already IS in the service layer, and the API resolver is a thin computation. A shared utility function is sufficient without a dedicated service method.

### 5. How should the API resolver access config hierarchy data?

**Decision**: Resolve config hierarchy in the `deployed_services` resolver on the `Deployment` type.

**Findings**:
- The `Deployment` Strawberry type's `deployed_services(info)` resolver already has access to the deployment entity
- From the deployment, we can load environment → cluster to resolve the config hierarchy
- The resolver can compute FQDNs for all services in one pass and inject them into the `DeployedService` instances
- This avoids N+1 queries (computing per-service would reload the same deployment/environment/cluster)

**Implementation approach**:
1. In `Deployment.deployed_services()`, load environment and cluster (2 queries total)
2. Resolve config hierarchy → get `fqdn_suffix`
3. Get app name from the deployment's driver version
4. Compute FQDNs for each service
5. Pass FQDNs to `DeployedService` instances via a private field

### 6. What data is needed for FQDN computation and where does it come from?

**Decision**: Document the data flow for both FQDN patterns.

**Primary FQDN** (`{sanitized-app-name}-{deployment-id}.{fqdn-suffix}`):
- `app.name` → From `ApplicationDriverVersion.application.name` (loaded via deployment's `application_driver_version_id`)
- `deployment-id` → From `Deployment.id` (UUID, used directly as string)
- `fqdn-suffix` → From `ResolvedConfig.fqdn_suffix` (merged cluster → environment → deployment config)

**Human-readable FQDN** (`{sanitized-service-host}-{sanitized-environment-name}.{fqdn-suffix}`):
- `service-host` → From `DeployedService.resolved_name` (the service's resolved DNS name)
- `environment-name` → From `Environment.name`
- `fqdn-suffix` → Same as above

**Sanitization**: Both patterns apply `to_fqdn_label` to variable components (app name, service host, environment name). The deployment ID (UUID) is already DNS-safe.

### 7. How should the frontend display FQDNs?

**Decision**: Add a "Services" card to the deployment detail page showing FQDNs for each service.

**Findings**:
- `DeploymentDetailPage.tsx` currently queries `deployedServices` but doesn't display them prominently
- The page uses card-based sections (Overview, Instance, Components, Configuration, Parameters, Backups)
- A new "Services" card fits naturally in this layout
- Each service should show: name, primary FQDN, human-readable FQDN, port, kind
- FQDNs should be copyable (click-to-copy or selectable text)
- When FQDNs are null (no suffix configured), show a clear "Not configured" indicator

**Alternatives considered**:
- Show FQDNs inline in existing sections: Rejected — services deserve their own focused section.
- Only show human-readable FQDN: Rejected — both variants serve different purposes (UUID-based is stable, human-readable is descriptive).
