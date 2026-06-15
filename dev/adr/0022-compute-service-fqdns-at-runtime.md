# ADR-022: Compute service FQDNs at runtime instead of persisting

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-service-fqdn-context/research.md (R3)

## Context

A deployed service exposes two FQDNs:

- **Primary** (UUID-based, stable): `{sanitized-app-name}-{deployment-id}.{fqdn-suffix}`
- **Human-readable** (environment-based, descriptive): `{sanitized-service-host}-{sanitized-environment-name}.{fqdn-suffix}`

Both depend on `fqdn_suffix`, which is resolved through the cluster → environment → deployment config hierarchy. The hierarchy can change independently of the deployment (an admin updating cluster config retroactively changes every deployed service's FQDN). FQDNs are also needed in two places: driver templates (Jinja2 rendering) and the frontend UI (via GraphQL).

The question: persist FQDNs on `DeployedService`, or compute them on demand from the current resolved config?

## Decision

Compute FQDNs at runtime in every call site. No database column for FQDNs, no migration, no `DeployedService.primary_fqdn` storage. Both the context-generation path (for driver templates) and the GraphQL resolver path (for the frontend) call the shared `context/fqdn.py` utility.

When `fqdn_suffix` is unresolved, both FQDN fields return `None` rather than constructing malformed addresses.

## Consequences

- FQDNs always reflect the current config hierarchy. An admin changing cluster `fqdn_suffix` is visible on the next page load without a re-deploy or cache invalidation.
- No database migration is required for this feature, sidestepping the migration-governance gate.
- No cache invalidation logic; no risk of a stored FQDN going stale and silently misrepresenting reality.
- Computation is trivial (string concat + sanitization) — no measurable performance cost even with batched per-service computation in the resolver.
- The cost is paid on every read instead of being amortized at write. Acceptable because the workload is read-light (UI queries, occasional driver renders), and the resolver computes all services in one pass to avoid N+1 on the underlying environment/cluster lookups.
- Backward-compatibility guarantee for driver migration (SC-002, SC-003): the runtime computation reuses the exact `to_fqdn_label` logic that drivers used inline, producing identical output.

## Alternatives Considered

- **Persist FQDNs on `DeployedService`**: rejected. Introduces sync concerns when the config hierarchy changes (an admin edit to cluster config silently desyncs every stored FQDN), requires a migration, and adds storage for derivable data. Performance gain is negligible since computation is string-only.
- **Persist FQDNs only in `ApplicationInstance.context` JSON**: rejected. Captures only the deploy-time snapshot, not the current resolved state; the frontend would need a different read path that diverges from driver templates and violates SC-003 (consistency between UI and driver output).
