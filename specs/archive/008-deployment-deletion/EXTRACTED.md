# Extraction Record

**Extracted on**: 2026-05-02
**Extracted by**: speckit.extract

## ADRs Created

- `dev/adr/adr-015-deployment-soft-delete-tombstoning.md` (from research.md R3 + namespace co-location finding)
- `dev/adr/adr-016-forensic-cr-retention-janitor.md` (from research.md R4)
- `dev/adr/adr-017-tombstone-visibility-conflation.md` (from research.md R5 + R6)
- `dev/adr/adr-018-scoped-tombstone-aware-name-uniqueness.md` (from spec.md FR-034/FR-035 + follow-on commit f14dcaa)

## Knowledge Updated

- `dev/knowledge/backend/services.md` — new "Deployment Lifecycle (incl. tombstoning)" subsection under "Deployment Service" section.
- `dev/knowledge/backend/orchestration-flows.md` — new "Lifecycles without Prefect" section.

(`dev/knowledge/backend/data-models.md`, `dev/knowledge/backend/api.md`, `dev/knowledge/agent/operator.md`, and `dev/knowledge/backend/e2e-testing.md` were updated mid-session during the spec-008 PR work and the retrospective fix-now bucket; they were not re-touched here.)

## Guidelines Updated

- `dev/guidelines/backend/python.md` — new "Soft-delete and partial unique indexes" subsection under "Database Models (SQLModel)".

## Archive

Spec directory moved to `specs/archive/008-deployment-deletion/` as a historical record.
