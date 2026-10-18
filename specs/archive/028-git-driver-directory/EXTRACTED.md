# Extraction Record

**Extracted on**: 2026-10-18
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- dev/adr/0080-action-deployments-keyed-by-driver-directory.md (from R-003)

ADR-079 (dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md) was written during implementation and already records R-001 and R-004.

## Knowledge Updated

- dev/knowledge/backend/data-models.md (ApplicationDriverVersion: `source_path` for git and local rows)
- dev/knowledge/backend/services.md (Applications Service: git loader signature; Driver Services → Provider: the git load steps and checks)
- dev/knowledge/frontend/driver-pages.md (Driver directory; Attributes for E2E tests; Tests; Key Files)
- dev/knowledge/cli/overview.md (Loading a driver from a driver directory)

Updated during implementation, before extraction: dev/knowledge/backend/api.md, dev/knowledge/backend/hooks-and-actions.md, dev/knowledge/backend/e2e-testing.md, CONTEXT.md.

## Guidelines Updated

- dev/guidelines/backend/python.md (Logging → Remove the user info from repository URLs in messages and logs)
- dev/guidelines/backend/python.md (Error Handling → Check the real path of each file you read from a repository a user controls)
- dev/guidelines/backend/python.md (Prefect Flows & Tasks → Refuse `{` and `}` in a user value that goes into a Prefect pull step)
- dev/guidelines/backend/python.md (Python SDK → Send a new optional GraphQL argument in its own operation)

## Archive

Spec directory moved to `specs/archive/028-git-driver-directory/` as a historical record.
