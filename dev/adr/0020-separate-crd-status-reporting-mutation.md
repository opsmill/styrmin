# ADR-020: Separate `reportCrdStatuses` mutation from pod status reporting

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-crd-status-reporting/research.md (R4)

## Context

The agent already polls pod statuses and reports them to the backend via a dedicated `reportPodStatuses` GraphQL mutation. Extending the agent to also collect StyrminDeployment CRD status raised the question of transport: bundle the CRD payload into `reportPodStatuses`, or add a companion mutation?

Pod status and CRD status are observed-state snapshots of two different Kubernetes object kinds. They share a polling cadence but nothing else — their schemas are unrelated, their failure modes are independent (a missing CRD does not stop pod observation, and vice versa), and they are consumed by different parts of the backend (pod statuses update component state; CRD status updates `Deployment.status` per [[0019-crd-phase-and-task-callback-coexist]]).

## Decision

Add a dedicated `reportCrdStatuses(reports: [DeploymentCrdStatusReport!]!)` mutation alongside `reportPodStatuses`. Each polling cycle invokes both mutations independently. The CRD mutation handles both upserting the `DeploymentCrdStatus` snapshot **and** applying the phase → `Deployment.status` update in the same transaction.

## Consequences

- Pod status collection and CRD status collection can fail independently. If `kubectl get pods` succeeds but listing the CRD fails (or vice versa), the surviving channel still delivers its data.
- Each mutation evolves independently — new fields on `DeploymentCrdStatusReport` don't ripple into pod reporting, and pod-status schema changes don't risk breaking CRD agents.
- The agent gains a slightly heavier per-cycle cost (two mutations instead of one), accepted because both are batched and the backend transaction boundaries are clearer.
- A future addition (e.g. middleware status, HelmRelease status) would follow the same pattern: a dedicated `report<Kind>Statuses` mutation rather than overloading an existing one.

## Alternatives Considered

- **Bundle CRD payload into `reportPodStatuses`**: rejected. Conflates two distinct observed-state types into one envelope, makes the mutation grow without bound as new resource kinds are observed, and entangles failure modes that should stay orthogonal.
- **Direct DB access from the agent**: rejected — breaks the layered architecture. The agent must go through the GraphQL API like every other client; the API layer is where authorization, validation, and the Deployment-status update transaction live.
