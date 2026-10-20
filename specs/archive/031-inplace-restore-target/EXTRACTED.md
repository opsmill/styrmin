# Extraction Record

**Extracted on**: 2026-10-20
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- dev/adr/0085-restore-target-derived-from-the-backups-deployment.md (from R-001 to R-006, R-010, R-016, and review findings 3, 7 and 14 of PR #536)
- dev/adr/0086-removed-graphql-arguments-explained-to-older-clients.md (from R-006 and review finding 8 of PR #536)

The numbers start at 0085 because develop already has dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md and dev/adr/0082 to 0084, which the recorded demos work (#518) adds.

## Knowledge Updated

- dev/knowledge/cli/overview.md (Restoring a backup)
- dev/knowledge/backend/backup-restore.md (Velero Integration → Builders: the Velero Restore and the restore flow agree on whether a restore is cross-target)
- dev/knowledge/backend/api.md (error handling: the instruction to add a removed argument to `REMOVED_ARGUMENTS` now links to the guideline and ADR-086)

Updated during implementation, before extraction: dev/knowledge/backend/api.md, dev/knowledge/backend/backup-restore.md, CONTEXT.md.

## Guidelines Updated

- dev/guidelines/backend/python.md (Rendering Kubernetes manifests → Derive the namespace that a flow deletes on the server, and check it again in the flow)
- dev/guidelines/backend/python.md (GraphQL (Strawberry) → Remove an argument that released clients send)
- dev/guidelines/backend/python.md (Python SDK → Report an older server that still requires an argument the SDK no longer sends)
- dev/guidelines/cyclopts.md (Validators → Refuse an option combination in the command body)
- dev/guides/graphql-propagation-tests.md (Test that a removed argument is refused)

## Archive

Spec directory moved to `specs/archive/031-inplace-restore-target/` as a historical record.
