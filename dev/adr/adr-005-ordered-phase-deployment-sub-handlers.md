# ADR-005: Ordered Phase-Based Deployment via Kopf Sub-Handlers

**Status**: Accepted
**Date**: 2026-04-06
**Source**: specs/archive/001-deployment-crd/research.md (R3, R4)

## Context

Applications must not start without their security boundaries (NetworkPolicies) and credentials (Secrets) in place. Service discovery (Services, Middlewares) should only be configured after the application is running. This requires guaranteed ordering of resource creation during deployment.

## Decision

Use kopf sub-handlers for the initial deployment flow with three phases:

1. **Phase 1 (prerequisites)**: Create NetworkPolicies + Secrets, verify all applied
2. **Phase 2 (helm)**: Create HelmRelease, wait for FluxCD Ready condition
3. **Phase 3 (services)**: Create Services + Middlewares, verify all applied

Sub-handlers provide: automatic idempotency tracking (no re-execution of completed phases), native retry with `kopf.TemporaryError(message, delay=N)`, phase ordering via status checks, and resume-from-interruption for free (kopf tracks handler state on the resource).

Deletion uses reverse-order sub-handlers in `@kopf.on.delete`, combined with `kopf.adopt()` owner references as a safety net. Deletion phases: Services/Middlewares first, then HelmRelease (wait for termination), then NetworkPolicies/Secrets.

A timer handler provides ongoing drift detection post-deployment (every 60s).

## Consequences

- Applications never start without NetworkPolicies — security boundaries are guaranteed before HelmRelease creation.
- Operator restarts mid-deployment resume from the last completed phase automatically.
- Already-succeeded sub-handlers are never re-executed on retry (idempotent by design).
- Sub-handler return values are stored in `status.<parent_handler_id>.<subhandler_id>` automatically.
- Owner references provide eventual cleanup if the operator misses a deletion event.

## Alternatives Considered

- **Single handler with manual state tracking**: Would require custom idempotency logic and manual resume-from-interruption. Rejected because kopf sub-handlers provide this for free.
- **Separate watchers per resource type**: Would lose ordering guarantees and make the deployment sequence harder to reason about. Rejected.
