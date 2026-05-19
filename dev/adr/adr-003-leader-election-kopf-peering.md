# ADR-003: Priority-Based Leader Election via Kopf Peering

**Status**: Accepted
**Date**: 2026-04-06
**Source**: specs/archive/001-k8s-operator/research.md (R3)

## Context

The operator must ensure only one active reconciliation instance runs at a time in multi-replica deployments. Without this, multiple replicas could simultaneously reconcile the same resources, causing conflicts and flapping.

## Decision

Use kopf's built-in peering mechanism with `ClusterKopfPeering` CRD. This is a priority-based conflict resolution system where the highest-priority operator instance runs while others pause.

Configuration is done via `@kopf.on.startup()` handler: `settings.peering.name`, `settings.peering.mandatory`, `settings.peering.priority`.

## Consequences

- No custom leader election code needed — kopf peering is built-in and well-tested.
- Requires deploying the `ClusterKopfPeering` CRD and creating a peering object.
- This is priority-based pause/resume, not true leader election — the highest priority operator wins.
- Peer records expire after a configurable `lifetime` (default 60s), so a crashed operator is eventually superseded.

## Alternatives Considered

- **Kubernetes Lease-based leader election**: Standard K8s pattern but requires custom implementation. kopf's peering is built-in. Rejected for unnecessary complexity.
- **`standalone=True` (no peering)**: Simplest option but unsafe with multiple replicas. Rejected.
