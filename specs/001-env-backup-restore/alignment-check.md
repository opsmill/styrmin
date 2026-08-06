# Spec/Ask Alignment Check: Environment-Level Backup and Restore

**Date**: 2026-08-06 | **Spec**: [spec.md](spec.md) (post-critique revision, commit `a7e9819`)

## Source

1. **GitHub issue [opsmill/styrmin#7](https://github.com/opsmill/styrmin/issues/7)** — "feat: Environment-level backup and restore operations" (fetched at session start; overview, problem statement, success metrics).
2. **Grilled idea brief** — produced in this conversation via the grilling-ideas interview (10 user-confirmed decisions: membership, status model, PARTIAL restorability, config+data restore contract, concurrency, empty-environment handling, lifecycle, surfaces, success criteria, glossary), passed verbatim as the specify-phase feature description.

## Verdict

**✅ ALIGNED**

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Info | added (necessary clarification) | — | FR-015, edge case "Environment deletion" | Critique found environment deletion would violate the new FK (crash today's bare row delete). Cascade rule added. Not in the brief because the interaction only surfaced during code-grounded planning; consistent with the brief's cascade-deletion lifecycle decision. |
| Info | added (necessary clarification) | Brief lifecycle decision (delete cascade) | FR-010 extension, edge case "Stuck constituent" | Deletion legal regardless of derived status — the escape hatch for a constituent stuck `PENDING`. Extends, does not change, the brief's deletion semantics. |
| Info | added (necessary clarification) | Brief restore rule "restore what's usable, report what isn't" | FR-007, edge case "Deployment busy at restore time" | "Deployment busy with another restore" added to the uniform skip reasons — a new instance of the brief's own uniform rule, not a semantic change. |
| Info | added (necessary clarification) | Brief governance note "follows ADR-0017, no new auth concepts" | Assumptions ("Authorization") | ADMIN gate on restore surfaced explicitly (config-revert privilege parity). Follows directly from the brief's own no-new-auth-concepts constraint. |
| Low | changed (gate bookkeeping, plan-level) | Brief governance table: "CI/CD change — none" | plan.md Constitution Check | Planning found one pre-authorized CI edit is required: removing the `{entrypoint: ui, shard: backup}` matrix exclusion so the dual-entrypoint E2E the brief itself demands actually runs under `[ui-chromium]`. The brief's "no CI change" was a gate assessment that proved incomplete, not a requirement; no spec requirement is affected. |

**Coverage sweep** (no missing/dropped/softened items found): membership rule → FR-001; config capture → FR-002; declared-state/clone-readiness → FR-003; derived status + PARTIAL → FR-004/SC-003; conflict-as-failed-child → FR-005; one-action restore of COMPLETED/PARTIAL → FR-006; zero silent skips → FR-007/SC-004; no topology changes → FR-008; concurrency + typed error → FR-009; cascade delete + individual child deletion → FR-010; empty environment → FR-011; four-surface parity → FR-012; list/inspect → FR-013; per-child TTL + persistent parent → FR-014; SC-001…SC-006 carried with identical semantics; all five out-of-scope items (clone/P2, topology reconstruction, env-level schedules, different existing environment, quiescing) preserved; issue #7's four success metrics all present (the "no duplication" metric deliberately recast as a design constraint, as the brief itself decided).

## Action

Proceed — no remediation passes needed (0 of 2 used).
