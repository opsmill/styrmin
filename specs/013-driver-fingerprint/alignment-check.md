# Alignment Check — Feature 013

**Timestamp**: 2026-05-25T10:30:00Z
**Phase**: 5 (Spec/Ask Alignment Check)

## Source

The source-of-truth PRD was reconciled from two sources, both already in this conversation:

1. **`.specify/idea-brief.md`** — substantive PRD (8 decisions, 9 functional requirements drafted, full user-journey set), produced during the `/grill-idea` session immediately preceding `/speckit-auto-prep`.
2. **GitHub issue [opsmill/styrmin#262](https://github.com/opsmill/styrmin/issues/262)** — referenced by `.specify/idea-brief.md` as the seed. Body fetched via `gh issue view 262 --repo opsmill/styrmin` at the start of the grilling session.

Both sources are treated as the consolidated "ask" against which `spec.md` (plus its downstream `plan.md`, `tasks.md`) is compared.

## Verdict

✅ **ALIGNED**

Every requirement and acceptance criterion in issue #262 maps to a functional requirement in `spec.md` and to one or more tasks in `tasks.md`. The idea brief's scope refinements (git path coverage, UI/CLI label rule, two-column schema, no-backfill assumption, no-GC assumption) are explicitly traceable to the grilling session and are uniformly applied in `spec.md`. No must-fix drift detected.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| _none_ | — | — | — | No must-fix drift. |
| ℹ Informational | Scope expansion (issue → spec) | issue #262 covers local-path bug + content-hash upsert | spec.md adds US2 (git path) and US4 (UI/CLI labels) | Both additions are explicitly agreed during the grilling session (idea brief, "Scope" + "Decisions"). The user instructed "we need to support both" for git, and the issue's own acceptance criterion "Surface `content_hash` on the GraphQL `ApplicationDriverVersion` type so the frontend/SDK can show e.g. 'loaded from <short-hash>'" anticipates the UI rendering. Recorded for traceability, not as drift. |
| ℹ Informational | Vocabulary refinement | issue mentions "referenced action source files" (plural) | spec.md FR-003 + Assumptions: only `actions.py` for v1 | User-approved during grilling: "agreed". Future multi-file action support is filed as out-of-scope. Recorded for traceability. |
| ℹ Informational | Design choice not in issue | issue mentions only `content_hash` column | spec.md / data-model.md introduces two columns (`content_hash` + `source_commit_sha`) | Forced by the scope expansion to cover git. Decision D-001 in research.md, owner-approved during grilling. |
| ℹ Informational | Plan-level addition not in issue or brief | neither source mentions a DB UNIQUE index | tasks.md T006 adds it | Introduced as critique recommendation R-X-1; closes the concurrent-load race. Not drift — additive risk mitigation. |

## Issue #262 acceptance-criteria coverage matrix

| Acceptance criterion (issue #262) | Spec | Tasks |
|---|---|---|
| Add `cascade="all, delete-orphan"` to `ApplicationDriverVersion.actions` and `.component_configs` | FR-001, User Story 3 | T004, T005 |
| Audit `ApplicationDriverVersion` siblings (`deployments` intentionally non-cascading) | research.md D-005 | Captured |
| Regression test: load local driver twice with same content → idempotent | User Story 1 scenario 2, SC-003 | T021 |
| Add `content_hash: str` column | FR-002 | T003 |
| Hash over canonical bytes of `driver.styrmin.yml` + values template + action source files | FR-003 (one-file `actions.py` for v1) | T007 |
| Upsert key includes content_hash | FR-005 | T011 |
| Same triple → idempotent | FR-005, SC-003 | T011, T021 |
| Same `(path, version)` + new hash → new row, **no delete** | FR-005, FR-006, SC-002 | T011, T024 |
| Remove existing `delete(existing)` branch | FR-006 | T024 |
| Unit test: identical YAML → no-op | — | T021 |
| Unit test: whitespace-only edit to values template → new row | edge cases | T008, T020 |
| Unit test: component addition → new row | edge cases (any-content-change) | T008, T022 |
| Surface `content_hash` on GraphQL `ApplicationDriverVersion` | FR-007 | T013, T014 |
| Document dev loop in `dev/guides/` | Constitution-alignment §VII | T051 |
| Backend unit tests pass | — | T055 |
| Targeted integration test on upsert path | — | T021, T022 |
| No Alembic migration; document manual step | Assumptions | Implicit (T058 PR description) |

All 17 acceptance criteria from issue #262 are covered.

## Action

**Proceed**. No remediation pass required. Tasks.md is ready for user review.
