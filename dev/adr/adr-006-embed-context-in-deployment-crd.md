# ADR-006: Embed GlobalContext in StyrminDeployment CRD for Autonomous Reconciliation

**Status**: Accepted
**Date**: 2026-04-06
**Source**: specs/archive/001-deployment-crd/research.md (R2)

## Context

The operator needs access to the full deployment configuration (GlobalContext) to compute desired resource specifications. The initial approach (001-k8s-operator R4) had the operator query the backend REST API at reconciliation time. This made the backend API a runtime dependency — if the API was unavailable, the operator could not reconcile.

## Decision

Embed the serialized GlobalContext directly in the StyrminDeployment CRD spec using `x-kubernetes-preserve-unknown-fields: true`. The Prefect flow computes the GlobalContext before creating the CRD, making the operator fully autonomous at reconciliation time.

Key CRD spec fields: `deploymentId`, `releaseReference`, `appName`, `appVersion`, `context` (full GlobalContext), `helm` (chart and repository specs).

## Consequences

- The operator is fully autonomous — no backend API calls needed during reconciliation.
- Eliminates API availability as a runtime failure mode for the operator.
- The CRD becomes larger (carries the full context), but `x-kubernetes-preserve-unknown-fields` avoids schema validation issues.
- Context updates require a CRD spec update (via Prefect flow), which naturally triggers operator reconciliation.
- Supersedes the earlier decision to fetch context from `GET /deployments/{deployment_id}/context` at reconciliation time.

## Alternatives Considered

- **Store only deployment_id and fetch context from API**: Adds latency and a failure mode to every reconciliation cycle. Rejected because it makes reconciliation fragile.
- **Store rendered resource manifests in the CRD**: Too large and couples the CRD to specific resource shapes. Rejected for maintainability.
