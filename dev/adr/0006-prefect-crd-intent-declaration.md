# ADR-006: Prefect Flows Declare Intent via CRD Instead of Direct Resource Management

**Status**: Accepted
**Date**: 2026-04-06
**Source**: specs/archive/001-deployment-crd/research.md (R5)

## Context

Prefect deployment flows (`create_instance`, `update_instance`, `upgrade_instance`) previously managed Kubernetes resources directly — creating HelmReleases, installing utility resources (NetworkPolicies, Services, Secrets, Middlewares), managing namespace labels, and polling HelmRelease status. This coupled the orchestration layer tightly to Kubernetes resource management and split resource ownership between Prefect and the operator.

## Decision

Refactor Prefect flows to create/update/delete StyrminDeployment CRDs instead of directly managing Kubernetes resources. The operator becomes the sole owner of all Kubernetes resources.

**What the Prefect flow does after refactoring:**
1. Compute GlobalContext from deployment configuration
2. Render Helm chart/repository specifications
3. Serialize context into StyrminDeployment CRD spec
4. Create/update/delete the CRD via kubernetes-asyncio API
5. Run driver pre/post hooks (unchanged — these are imperative actions)
6. Callback to update task status (unchanged)

**What is removed from Prefect:**
- Direct HelmRelease creation/update
- Direct utility resource creation/update (`install_utility`, `update_utility`)
- Namespace label management
- HelmRelease polling

## Consequences

- Clear separation of concerns: Prefect declares intent, operator manages Kubernetes resources.
- Single source of truth for resource lifecycle — no split ownership between Prefect and operator.
- Prefect flows become simpler (CRD create/update/delete vs. multi-step resource management).
- The CRD serves as a durable record of deployment intent — if Prefect crashes after creating the CRD, the operator still processes it.
- Pre-existing deployments without a StyrminDeployment CRD continue to work unchanged (forward-only).

## Alternatives Considered

- **Keep split ownership** (Prefect creates resources, operator reconciles): Maintains complexity of two systems managing overlapping resources. Rejected because it creates conflict potential and makes reasoning about resource state harder.
- **Move everything to operator** (no Prefect involvement): Driver hooks are imperative actions that don't fit the declarative operator model. Rejected because hooks need Prefect's workflow execution capabilities.
