# Spec / Ask Alignment Check

**Date**: 2026-05-14
**Feature**: [spec.md](./spec.md)
**Verdict**: ✅ ALIGNED

## Source

The source-of-truth PRD for this feature is the union of:

1. **[GitHub issue #219](https://github.com/opsmill/styrmin/issues/219)** — original platform-engineer request. Provides: problem statement, scope, acceptance criteria, non-goals, references to prior 009-environment-update pattern. Fetched at the start of the session.
2. **`.specify/idea-brief.md`** — augmented PRD produced by `/grill-idea` against the same issue. Adds: locked decisions from the grilling session (scope = single P1, parameters = merge, parameters shape = list of ParameterValueInput, components = list + full-replacement + DuplicateComponentNameError, E2E scope, success criteria), plus the constitution-alignment and governance-gate checklists.

Both documents agree on intent; the idea-brief simply makes the implicit decisions in #219 explicit.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| — | (none) | — | — | No significant drift detected. |
| ✓ (added refinement) | added (in-spirit) | Issue #219 "discoverable, schema-validated input surface" + idea-brief SC-001 (discoverability) | spec.md FR-012, contracts §6 (`test_update_deployment_input_fields_have_descriptions`) | Spec added FR-012 requiring non-empty `description` on every new input field. Not in the original PRD's literal text but a direct refinement of the discoverability goal that PRD's SC-001 already encoded. Added during critique phase as a clear-fix recommendation (P1 + X2). Operationalizes "discoverable" beyond field presence into field comprehension. Treated as expansion-of-detail, not drift. |
| ✓ (correctly removed) | removed | (not in PRD) | plan.md, contracts §1.4 | Plan initially proposed renaming `ServiceNameOverride` → `ServiceNameOverrideInput` for naming-convention consistency. PRD did not call for this rename. Critique phase (E1) caught that the type is shared with the out-of-scope `Deploy` mutation and the rename would ripple beyond feature bounds. Rename was removed; the type is now reused unchanged. Brings the plan back into alignment with PRD's "Non-Goals: migrating deployDeployment is out of scope". |

### PRD acceptance criteria coverage (Issue #219)

| PRD AC | Spec coverage | Status |
|--------|---------------|--------|
| `UpdateDeploymentInput` and nested types under `backend/styrmin_backend/api/definitions/deployment/` | FR-001, plan.md "Project Structure" | ✅ |
| Every writable field reachable through typed input | FR-001, SC-001, contracts §4 (22-row matrix) | ✅ |
| Shared leaf inputs reused across env + deployment, no duplication | FR-002, research.md §2, plan.md "Project Structure" | ✅ |
| `update_deployment_input_to_dict()` ports env-input semantics 1:1 | FR-004, data-model.md §4 (pseudocode) | ✅ |
| Resolver accepts single `input` argument and forwards plain dict to unchanged service function | FR-003, FR-005, data-model.md §5 | ✅ |
| Typed env-var errors continue to reach GraphQL boundary | FR-008, contracts §5 (rows E1-E7) | ✅ |
| SDK + CLI regenerated | FR-010, tasks T013-T015 | ✅ |
| Frontend codegen regenerated; callers updated | FR-011, tasks T016-T019 | ✅ |
| GraphQL propagation unit test per new field | SC-002, contracts §4 (22 rows), tasks T030 | ✅ |
| E2E test for components.envVars + scheduling | research.md §7, tasks T032 | ✅ |
| `ruff` + `ty` + `pnpm lint` clean | tasks T036, T037 | ✅ |
| `uv run invoke validate-graphql` passes | tasks T035 | ✅ |

### PRD non-goals respected

| PRD non-goal | Spec disposition | Status |
|--------------|------------------|--------|
| Changing underlying `update_deployment` service signature | Spec Assumptions: "service function signature stays unchanged"; FR-005 enforces forwarding to unchanged signature | ✅ |
| Migrating `deployDeployment` (create) to typed input | Spec Out of Scope §1; critique E1 caught + reverted a plan change that would have rippled into Deploy | ✅ |
| Typing arbitrary driver-defined parameters deeper than schema allows | Spec Out of Scope §2 + Assumption clarifying parameter-value validation contract is preserved | ✅ |

### Idea-brief grilled decisions, all locked into spec

| Decision | Spec encoding | Status |
|----------|---------------|--------|
| Scope = single P1 (typed input only) | spec.md User Story 1 (no P2/P3) | ✅ |
| Parameters semantics = merge (preserve today) | FR-006, acceptance scenario 6, data-model.md §1.1 note, research.md §3 | ✅ |
| Parameters shape = `[ParameterValueInput!]` | Key Entities, contracts §1.3 | ✅ |
| Components shape = `[ComponentConfigInput!]` + full-replacement + `DuplicateComponentNameError` | Key Entities, contracts §1.2, FR-009, acceptance scenarios 4 + 7 | ✅ |
| E2E = single api_only covering env-var + scheduling + typed error | research.md §7, tasks T032 | ✅ |
| Two new typed errors with stable codes | FR-009, contracts §3, data-model.md §3 | ✅ |
| Hard cutover (no transitional period) | FR-003, plan.md "Rollout & Rollback" | ✅ |
| Idea-brief Open Question (no external consumers) | Spec Assumption; verified by repo-wide grep in research.md §6 | ✅ Resolved |

## Action

✅ **PROCEED** — alignment is solid. The spec faithfully encodes both the GitHub issue's acceptance criteria and the idea-brief's locked grilling decisions. The two changes that happened during prep (FR-012 added, ServiceNameOverride rename dropped) both pulled the spec/plan closer to PRD intent rather than away from it.

No remediation pass required. Phase 5 closes with verdict ✅ ALIGNED. The full auto-prep pipeline is complete; `tasks.md` is ready for review and either manual implementation or `/speckit-auto-implement` to execute.
