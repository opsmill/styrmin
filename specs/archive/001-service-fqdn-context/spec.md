# Feature Specification: Include Service FQDNs in Deployment Context

**Feature Branch**: `001-service-fqdn-context`
**Created**: 2026-03-28
**Status**: Extracted
**Input**: [GitHub Issue #38](https://github.com/opsmill/styrmin/issues/38) - feat: Include service FQDNs in deployment context

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Service Access Addresses in the UI (Priority: P1)

As a platform user managing deployments, I want to see the full access addresses (FQDNs) of my deployed services directly in the UI, so I can quickly find and share the URLs needed to reach each service without needing to inspect driver templates or Kubernetes resources.

Today, FQDNs are only computed inside driver templates during deployment. This means the UI has no access to these addresses, forcing users to look them up manually in cluster configurations or driver output.

**Why this priority**: This is the primary user-facing value of the feature. Without it, users have no self-service way to discover service addresses, leading to support requests and wasted time.

**Independent Test**: Can be fully tested by deploying a service and verifying its FQDNs appear in the UI deployment detail view, delivering immediate value to any user managing deployments.

**Acceptance Scenarios**:

1. **Given** a deployment with one or more services, **When** a user views the deployment details in the UI, **Then** each service displays both its primary (UUID-based) FQDN and its human-readable (environment-name-based) FQDN.
2. **Given** a deployment where the FQDN suffix is not configured, **When** a user views the deployment details, **Then** the system gracefully indicates that FQDNs are not available for that deployment rather than displaying broken or partial addresses.
3. **Given** a service whose name contains special characters (underscores, dots, uppercase), **When** the FQDNs are displayed, **Then** the addresses are properly sanitized to valid DNS labels.

---

### User Story 2 - Centralized FQDN Computation in Deployment Context (Priority: P2)

As a driver author, I want pre-computed FQDNs available as first-class fields in the deployment context, so I can reference them directly in my templates without having to manually construct FQDN strings or know the FQDN pattern conventions.

Currently, every driver template independently re-implements the same FQDN construction logic using Jinja2 string concatenation and the `to_fqdn_label` filter. This leads to inconsistency risk when patterns change and creates unnecessary boilerplate in every driver.

**Why this priority**: This is the core infrastructure change that enables Story 1 and Story 3. It eliminates duplicated logic across all drivers and establishes the single source of truth for FQDN computation.

**Independent Test**: Can be tested by verifying that the deployment context for any deployment includes correct FQDN fields for each service, and that a driver template can reference these fields directly.

**Acceptance Scenarios**:

1. **Given** a deployment with services, **When** the system generates the deployment context, **Then** each service in the context includes both a primary FQDN (UUID-based) and a human-readable FQDN (environment-name-based).
2. **Given** a deployment whose resolved configuration includes an FQDN suffix, **When** the context is generated, **Then** the FQDNs are constructed using the resolved suffix from the configuration hierarchy.
3. **Given** a deployment whose resolved configuration has no FQDN suffix, **When** the context is generated, **Then** the FQDN fields are empty or null rather than containing malformed addresses.
4. **Given** a service name or environment name with characters invalid for DNS labels, **When** the context is generated, **Then** the FQDN components are sanitized to valid DNS labels (lowercase, alphanumeric and hyphens only, max 63 characters per label).

---

### User Story 3 - Simplified Driver Templates (Priority: P3)

As a driver author, I want to update my existing templates to use the pre-computed FQDNs from context instead of constructing them inline, so my templates are simpler, less error-prone, and automatically consistent with the platform's FQDN conventions.

**Why this priority**: This is the migration step that realizes the full benefit of Story 2. It removes the duplicated FQDN logic from all existing drivers and serves as a reference for how new drivers should use FQDNs.

**Independent Test**: Can be tested by deploying each example driver and verifying that the resulting Kubernetes resources contain the same FQDN values as before the migration, confirming backward-compatible behavior.

**Acceptance Scenarios**:

1. **Given** an existing driver template that currently constructs FQDNs inline, **When** the template is updated to reference pre-computed FQDN fields, **Then** the rendered output produces identical FQDNs as the previous inline construction.
2. **Given** all example drivers in the platform, **When** they are updated, **Then** none of them contain inline FQDN construction patterns (string concatenation with `fqdn_suffix`).
3. **Given** a driver that uses the `to_fqdn_label` filter for non-FQDN purposes (e.g., sanitizing labels for other uses), **When** the migration is complete, **Then** the filter remains available and functional.

---

### Edge Cases

- What happens when a service name exceeds the DNS label length limit (63 characters) after sanitization? The system should truncate to 63 characters while preserving a valid label (no trailing hyphens).
- What happens when the FQDN suffix is configured at the cluster level but overridden to empty at the deployment level? The system should treat the resolved empty value as "no suffix configured" and not generate FQDNs.
- What happens when a deployment has no services? The context should simply contain no FQDN entries rather than erroring.
- What happens when the same service is deployed in multiple environments? Each environment's context should produce distinct environment-name-based FQDNs while sharing the same UUID-based primary FQDN pattern.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST compute a UUID-based primary FQDN for each service in a deployment, following the pattern `{sanitized-app-name}-{deployment-id}.{fqdn-suffix}`.
- **FR-002**: System MUST compute an environment-name-based human-readable FQDN for each service in a deployment, following the pattern `{sanitized-service-host}-{sanitized-environment-name}.{fqdn-suffix}`.
- **FR-003**: System MUST expose both FQDN variants as first-class fields on the service context model so they are part of the deployment context available to drivers.
- **FR-004**: System MUST apply DNS-safe sanitization to all FQDN label components (lowercase, replace non-alphanumeric with hyphens, collapse consecutive hyphens, strip leading/trailing hyphens, truncate to 63 characters).
- **FR-005**: System MUST expose FQDN data through the API so the frontend can retrieve and display service addresses.
- **FR-006**: System MUST handle missing FQDN suffix gracefully by leaving FQDN fields empty/null rather than constructing malformed addresses.
- **FR-007**: All existing example drivers MUST be updated to reference pre-computed FQDNs from context instead of constructing them inline.
- **FR-008**: The `to_fqdn_label` sanitization utility MUST remain available for edge-case usage in driver templates even after the migration.

### Key Entities

- **Service FQDN**: A fully qualified domain name for accessing a deployed service. Each service has two variants: a primary FQDN (UUID-based, unique per deployment) and a human-readable FQDN (environment-name-based, descriptive). Both are derived from the service identity, deployment context, and the resolved FQDN suffix configuration.
- **Service Reference (extended)**: The context model representing a service in a deployment, extended with FQDN fields. Contains the existing service connection information (host, port, protocol) plus the two new FQDN variants.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can view the access addresses for 100% of deployed services directly in the UI without consulting external resources.
- **SC-002**: Zero driver templates in the example set contain inline FQDN construction logic after migration.
- **SC-003**: FQDN values displayed in the UI are identical to the values used by drivers for the same deployment, achieving 100% consistency.
- **SC-004**: New driver templates require zero FQDN construction logic; they reference pre-computed context fields only.
- **SC-005**: All FQDN label components comply with DNS label standards (RFC 1035: lowercase alphanumeric and hyphens, max 63 characters, no leading/trailing hyphens).

## Assumptions

- The existing two FQDN patterns (UUID-based primary and environment-name-based) are the only patterns needed. No additional FQDN variants are required.
- The FQDN suffix is already correctly resolved through the existing configuration hierarchy (cluster -> environment -> deployment). No changes to the configuration resolution logic are needed.
- The existing `to_fqdn_label` sanitization logic is correct and complete for DNS label compliance. The same logic will be reused in the centralized computation.
- Driver templates that currently construct FQDNs inline will produce identical results when switched to the pre-computed context fields, requiring no behavioral changes in deployed applications.
