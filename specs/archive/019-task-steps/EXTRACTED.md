# Extraction Record

**Extracted on**: 2026-10-08
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-060](../../../dev/adr/0060-steps-and-derived-task-result.md) was written during
implementation and already records research.md D1–D19. Its `Source` line now points at
`specs/archive/019-task-steps/`.

## Knowledge Updated

Updated during implementation (2026-10-06, before this extraction):

- dev/knowledge/backend/data-models.md (Task, Step, Task result)
- dev/knowledge/backend/api.md (Task, Step)
- dev/knowledge/backend/orchestration-flows.md (Steps recorded by the flows)
- dev/knowledge/backend/backup-restore.md (Backup and restore steps)
- dev/knowledge/backend/hooks-and-actions.md (Tasks started by a hook step)
- dev/knowledge/agent/operator.md (Steps of a rollout)
- dev/knowledge/agent/overview.md (status reports and the phase history)
- dev/knowledge/architecture.md
- CONTEXT.md (Step, Task result)

Added by this extraction:

- dev/knowledge/backend/services.md (Step Services (`steps/`))
- dev/knowledge/cli/overview.md (Task steps)
- dev/knowledge/frontend/deployment-timeline.md (new file)

## Guidelines Updated

- dev/guidelines/backend/python.md (Service Layer → Calculate a status that several writers change; do not store it)
- dev/guidelines/backend/python.md (Admin & authorization mutations → mutations only Styrmin's flows may call)
- dev/guidelines/backend/python.md (GraphQL → Load list fields in a fixed number of queries)
- dev/guidelines/backend/python.md (Prefect Flows & Tasks → Record units of work as steps)

## Other Changes

- `backend/styrmin_backend/agent/steps/reporter.py` and
  `backend/styrmin_backend/agent/service/kubernetes/job_logs.py`: docstring paths point at
  `specs/archive/019-task-steps/`.
- `CLAUDE.md`: removed the "Active feature plan" line for this spec.

## Archive

Spec directory moved to `specs/archive/019-task-steps/` as a historical record.
