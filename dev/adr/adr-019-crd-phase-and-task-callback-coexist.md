# ADR-019: CRD phase reports coexist with task callbacks via last-write-wins

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-crd-status-reporting/research.md (R3)

## Context

Before this decision, the `Deployment.status` field was updated only when a Prefect task completed via its callback. Between task start and completion — while the StyrminDeployment CRD progressed through phases `CreatingPrerequisites → CreatingHelmRelease → CreatingServices → Ready` — the backend had no visibility into the actual cluster state. This left operators unable to distinguish "still deploying" from "stuck", and meant a CRD that recovered after a Prefect failure could leave `Deployment.status = failed` even though the workload was healthy.

A second, agent-driven status update path was needed. The question was how to combine it with the existing task callback without inventing precedence rules.

## Decision

Add a service function `update_deployment_from_crd_phase()` that maps CRD phase to `DeploymentStatus` and persists via the existing UnitOfWork. Both the Prefect task callback **and** the agent's `reportCrdStatuses` mutation write to `Deployment.status`. The most recent write wins; no precedence system is introduced.

Phase → status mapping:

| CRD Phase | Deployment Status |
|-----------|------------------|
| `Pending`, `CreatingPrerequisites`, `CreatingHelmRelease`, `CreatingServices` | `pending` |
| `Ready` | `running` |
| `Failed` | `failed` |
| `Deleting` | (no change — preserve in-flight intent) |

## Consequences

- The CRD phase becomes the eventual ground truth: a transient task failure no longer pins `status = failed` indefinitely, because the next poll cycle observes `Ready` and overwrites it.
- Status visibility now refreshes on the agent's polling cadence (default 60s) instead of only at task boundaries, satisfying SC-002.
- Two writers to one field means brief flapping is possible if a task and a poll cycle disagree. This is acceptable: both writers converge on the same value within one poll interval, and the CRD-driven write is the one that reflects reality.
- The task callback path is preserved unchanged — it still updates `Task` and `ApplicationInstance` status, which the agent does not touch.
- `Deleting` is explicitly a no-op so an intentional teardown doesn't get overwritten back to `pending`.

## Alternatives Considered

- **Replace the task callback entirely with CRD-driven updates**: rejected. The callback also updates `Task` and `ApplicationInstance` state; ripping it out for one field would force a much larger refactor and remove a useful low-latency signal at task completion.
- **Add a priority/precedence system between writers**: rejected as over-engineering. The system is polling-based and eventually consistent by construction. Last-write-wins is simpler and produces the same end state.
