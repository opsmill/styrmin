# Extraction Record

**Extracted on**: 2026-10-21
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- dev/adr/0082-recorded-demos-reuse-e2e-page-objects.md (from R-006, R-012; Clarifications of 2026-10-17 and 2026-10-21; FR-003, FR-004, FR-014; SC-004)
- dev/adr/0083-demo-waits-sped-up-after-recording.md (from the third-party dependency evaluation, R-001 to R-005 and R-016; FR-024; spike notes "One screencast records both origins")
- dev/adr/0084-record-command-deletes-only-environments-it-created.md (from R-014; Clarifications of 2026-10-21; FR-009; data-model.md "Created environments file")

## Knowledge Updated

- dev/knowledge/backend/backup-restore.md (Backup Strategies: the `neo4j` row of the table and the strategy list said `neo4j-admin dump`; the code runs `neo4j-admin database backup`. New subsection "The neo4j backup needs Neo4j Enterprise", from R-007)
- dev/knowledge/backend/backup-restore.md (Restore Lifecycle: new subsection "The application can still be unavailable when its restore completes", from the spike notes)
- dev/knowledge/backend/data-models.md (Task result: the example of an upgrade that runs a driver's core upgrade action, from the Clarifications of 2026-10-21 and the spike notes)
- dev/knowledge/backend/e2e-testing.md (Debugging: new subsection "Operations fail with "An internal error occurred" when the host disk is nearly full")

Updated during implementation, before extraction: dev/guides/local-demo.md ("Recording the demos") and dev/knowledge/backend/e2e-testing.md ("Page objects shared with the recorded demos", Key Files).

## Guidelines Updated

- dev/guidelines/backend/python.md (Testing: enter text in an E2E page object with `enter_text()` and pass `keystroke_delay_ms` on)
- dev/guidelines/backend/python.md (Testing: a recorded demo holds no selector for a Styrmin page, and checks the result it shows)
- dev/guidelines/backend/python.md (Testing: to prove that an upgrade ran, check what the upgrade task did, not the deployment's version or status)

## Not Extracted

- R-007's choice of driver for demos 3 and 4, R-008 to R-011, R-015 and R-017, data-model.md and contracts/record-command.md: the code and dev/guides/local-demo.md cover them.
- R-013: the defect [#530](https://github.com/opsmill/styrmin/issues/530), fixed by [PR #531](https://github.com/opsmill/styrmin/pull/531); dev/knowledge/backend/orchestration-flows.md ("Aliases of a cross-target restore") covers the fix.
- Spike notes, "Semaphore reads the devices from Infrahub": a Semaphore deployed at the same time as Infrahub got no `infrahub` alias. This was observed on commit `60d82a86`, which does not contain the fix of [ADR-078](../../../dev/adr/0078-alias-step-reads-current-services-from-server.md) (commit `f4e60189`), and was not checked again. The comment "Semaphore gets the `infrahub` alias only if Infrahub runs when it is deployed" in three scenarios under `backend/tests/e2e/demos/scenarios/` may be out of date.
- Spike notes, "Service URLs of the deployments": the `primaryUrl` of the `task-manager` service was the same as that of the `infrahub` service. Observed, not investigated.
- plan.md, tasks.md, quickstart.md, alignment-check.md, critiques/, checklists/, e2e-evidence.md, opsmill-implement-report.md and the rest of spike-notes.md: records of the work.

## Links Updated

The "Active plan" link in CLAUDE.md now points to `specs/archive/031-recorded-feature-demos/plan.md`. The new ADRs and knowledge sections link to the archive path. Relative links inside the moved spec were not changed, as for the archive of spec 029.

## Archive

Spec directory moved to `specs/archive/031-recorded-feature-demos/` as a historical record.
