# Extraction Record

**Extracted on**: 2026-10-16
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-070](../../../dev/adr/0070-replica-overrides-and-retired-parameters.md) was written
during implementation and records research D-001 to D-007 and D-009.

## ADRs Updated

- dev/adr/0070-replica-overrides-and-retired-parameters.md (source path moved to the archive; §4:
  the readiness polls of the agent's Helm release flows wait while `status.replicas` is above
  `spec.replicas`)

## Knowledge Updated

- dev/knowledge/cli/overview.md (Declarative apply: `replicas` among the override kinds that are
  read back, `ApplyOutcome.applicability_check_error` and its warning)
- dev/knowledge/cli/overview.md (Replica counts: `check_replica_counts`, `deployments scale`, the
  `replicas` column of `deployments get`, server compatibility)
- dev/knowledge/backend/services.md (Replica counts: `max_replica_count` and
  `REPLICA_COUNT_ABOVE_MAXIMUM` in `validator.py`)
- dev/knowledge/backend/overview.md (configuration: `STYRMIN_MAX_REPLICA_COUNT`)
- dev/knowledge/agent/overview.md (Readiness polls of the Helm release flows)

The other knowledge pages and `CONTEXT.md` were updated during implementation.

## Guidelines Updated

- dev/guidelines/backend/python.md (Validate config writes by delta: rules of the bound driver
  version check unchanged values; server-setting limits check only changes and stay in the service
  layer)
- dev/guidelines/backend/python.md (Validator entry-point type guards: integers, `bool` and numeric
  strings, Kubernetes field bounds, comparing a value with a default by type)
- dev/guidelines/backend/python.md (Add a typed field to a stored model without changing its dump
  at the default)
- dev/guidelines/backend/python.md (Check driver data strictly at load, and drop only the invalid
  key on read)
- dev/guidelines/backend/python.md (Per-component pod overrides go through post-render: one patch
  per workload field, JSON6902 `add`, no fallback patch)
- dev/guidelines/backend/python.md (Testing: read the workload once after the task completes)

## Archive

Spec directory moved to `specs/archive/023-per-component-replicas/` as a historical record.
