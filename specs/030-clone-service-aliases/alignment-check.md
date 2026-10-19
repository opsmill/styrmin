# Alignment Check: Spec 030 Against the PRD of #530

## Source

- PRD "A clone writes its own service aliases and restores none of the source's": [opsmill/styrmin#530 (comment)](https://github.com/opsmill/styrmin/issues/530#issuecomment-6248901847), read with `gh issue view 530 --json comments` on 2026-10-18. Its links point to `develop` at `5444f0e6`.
- Compared with [`spec.md`](spec.md) at commit `d8f130ee`, written against `develop` at `f4e60189`, which adds the fix for #503.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD requirement, user story, journey, edge case, success criterion and testing decision is in the spec with the same meaning. The differences below come from the #503 fix that `develop` gained after the PRD was written, from one PRD requirement that the code does not meet today (the clone entry of a failed restore), and from the critique. Each is recorded in the spec's Clarifications and flagged for the maintainer.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | changed | FR-002 ("whatever that deployment's state"); SC-001 | FR-002; SC-001; Clarifications (autonomous) | The spec keeps the #503 rule that the alias step skips a namespace that is missing or terminating (ADR-077), and SC-001 counts only deployments whose namespace exists. The PRD was written before that rule was on `develop`. The outcome of user story 6 holds: a counterpart's own alias step, or its next change, writes the skipped aliases. |
| Minor | added | User story 4, P3, FR-004 ("with the counterpart's entry set to failed and the reason given") | FR-007; SC-004; Clarifications (autonomous) | Today the entry of a counterpart whose restore failed reads `cloned`. To meet the PRD, the spec adds FR-007: the API reports such an entry as `failed` with the restore's error. It applies to every cause of a failed counterpart restore, not only the alias step. |
| Minor | changed | Implementation decisions, "API and interface surface: none" | Governance Gates; FR-007 | FR-007 changes what the existing fields `outcome` and `reason` return in one case, and their descriptions in `schema.graphql`. No field, type or argument changes. |
| Minor | added | FR-004 | FR-004; edge cases; Clarifications (critique) | The spec says that the counterpart's status, which the failed restore sets to `FAILED`, then follows its StyrminDeployment and can read `RUNNING`. The PRD does not state the counterpart's status after an alias failure; the critique found that keeping it `FAILED` races with the operator. Since the review of #531 (2026-10-19), the restore sets the counterpart to `RUNNING` when only the alias step failed. |
| Minor | changed | Implementation decisions, "Alias computation for the counterpart (the restore flow with database access)" | Plan, research R-002 | The plan computes the aliases in the restore's cluster-side flow, from the server's list read when it writes (ADR-078), with the counterpart's context passed by the database-side flow. The PRD placed the computation on the database side. This is a design choice, not a requirement; it follows the #503 decision that the alias step reads the services when it runs. |
| Minor | added | Testing decisions, "Integration tests: none needed" | Testing Decisions | The spec adds one functional GraphQL test for FR-007. |
| Minor | changed | Key entities, "Service alias: not in `CONTEXT.md` on `develop`" | Key Entities; Documentation | `develop` now has the entry (#503). The spec extends it instead of adding it. |
| Minor | added | Constitution alignment, VII | Documentation; research R-010 | The documentation list adds `ingress-and-networking.md`, two more sections of `backups-and-restores.md`, and `dev/knowledge/backend/orchestration-flows.md`. |

No PRD requirement, goal, non-goal or acceptance criterion is missing, dropped or contradicted.

## Action

Proceed. No remediation pass was needed. The PR notes (task T038) ask the maintainer to confirm the four autonomous answers: the #503 namespace rule in FR-002 and SC-001, FR-007 for every cause, the counterpart's status after an alias failure, and the description-only change of `schema.graphql`.
