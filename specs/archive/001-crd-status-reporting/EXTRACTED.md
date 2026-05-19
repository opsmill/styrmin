# Extraction Record

**Extracted on**: 2026-05-17
**Extracted by**: speckit.extract

## ADRs Created

- [`dev/adr/adr-019-crd-phase-and-task-callback-coexist.md`](../../dev/adr/adr-019-crd-phase-and-task-callback-coexist.md) (from R3)
- [`dev/adr/adr-020-separate-crd-status-reporting-mutation.md`](../../dev/adr/adr-020-separate-crd-status-reporting-mutation.md) (from R4)
- [`dev/adr/adr-021-deployment-crd-status-snapshot-table.md`](../../dev/adr/adr-021-deployment-crd-status-snapshot-table.md) (from R5)

## Knowledge Updated

- [`dev/knowledge/backend/api.md`](../../dev/knowledge/backend/api.md) (GraphQL Types → DeploymentStatusType, CrdCondition, ManagedResourceCounts)

## Guidelines Updated

None.

## Items not applied (already covered)

- `dev/knowledge/backend/data-models.md` (Observed State Models → `DeploymentStatus`) — already documents the evolved model under the post-rename name `DeploymentStatus`; not duplicated.
- `dev/knowledge/agent/operator.md` (StyrminDeployment CRD → Status) — already documents `phase`, `displayState`, `conditions`, `managedResources` and the status reporter flow; not duplicated.

## Naming note

The spec authored the wire surface as `DeploymentCrdStatus` / `reportCrdStatuses` / `DeploymentCrdStatusReport`. The shipped code uses `DeploymentStatus` / `reportDeploymentStatuses` / `DeploymentStatusReportInput` and adds two wire-only fields (`displayState`, `instanceId`). The ADRs preserve the original names as a point-in-time record; the knowledge updates use the current names.

## Archive

Spec directory moved to `specs/archive/001-crd-status-reporting/` as a historical record.
