# Spec/PRD Alignment Check: 022 Post-Render Container Overrides

**Date**: 2026-10-14

## Source

- PRD "Container overrides applied by a post-render patch": [opsmill/styrmin#457 (comment 6166451728)](https://github.com/opsmill/styrmin/issues/457#issuecomment-6166451728), fetched with `gh api repos/opsmill/styrmin/issues/comments/6166451728`.
- Seed issue for context: [#457](https://github.com/opsmill/styrmin/issues/457).

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD requirement, user story, journey, acceptance criterion, functional requirement, success criterion, edge case, assumption, out-of-scope item and governance gate is present in [spec.md](spec.md). The differences are one narrowed success criterion and additions that make PRD decisions explicit. No remediation pass was needed.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | changed | SC-004 | SC-004 | The PRD says no override is reported as applicable "without reaching the pod". The spec scopes this to the pods of the component's `Deployment` or `StatefulSet` workloads (critique P6). This matches PRD FR-001 ("in its `Deployment` and `StatefulSet` workloads") and the PRD's out-of-scope list (`Job`, `CronJob`, `DaemonSet`), so the meaning for in-scope workloads is unchanged |
| Minor | added | Edge cases; Out of scope | Edge cases 4 and 7 | Two edge cases added by the critique: a component container on a `DaemonSet`/`Job`/`CronJob` is not patched, and pods on an unmigrated driver version keep running while their render fails. Both follow from PRD statements (out-of-scope list; P2 "Styrmin does not apply the HelmRelease") |
| Minor | added | Implementation decisions, Documentation | FR-012 | The migration guide also states that running pods keep running, and reference pages (`styrminctl` apply note, glossary Component container entry) are added to the documentation list. Expansion of the PRD's "updated concept pages and user-facing glossary entries" |
| None | added | Implementation decisions | FR-009 to FR-012 | PRD implementation decisions (example drivers, API and storage removal, no new error code, documentation) restated as testable requirements. Not drift |
| None | added | Journeys P1 and P3 | US1 scenarios 3–5, US3 scenarios 3–5 | Scenarios drawn from PRD user stories 2 and 8, the "only `args`" edge case, FR-004, FR-007 and FR-008. Not drift |
| None | added | — | Clarifications | Records how the PRD answers the four "Not decided" points of #457, plus that every existing write path carries the check (derived from the shared deployment service). Not drift |
| None | added (plan) | — | research D-009 | Example driver versions are bumped (`simple-app` 3, `infrahub` 4, `infrahub-enterprise` 3), following the env var migration precedent. Implementation detail needed for PRD journey P2, not a new requirement |
| None | added (plan) | — | research D-006, contracts/errors.md | `DRIVER_CONTAINER_OVERRIDE_DOC_COMPONENT_MISMATCH` is removed with the block it validated. The PRD forbids new error codes, not removals; listed in the `removed` changelog fragment |

No PRD requirement is missing, softened or contradicted.

## Action

Proceed. No remediation pass (0 of 2 used). The minor findings are recorded here for the reviewer.
