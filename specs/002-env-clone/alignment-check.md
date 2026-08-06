# Spec/Ask Alignment Check: Environment Clone

**Feature**: `specs/002-env-clone` | **Date**: 2026-08-06

## Source

The source-of-truth PRD is the grilled idea brief for issue #6, confirmed decision-by-decision with the user in the grilling session and published at
<https://github.com/opsmill/styrmin/issues/6#issuecomment-5208479529> (verbatim local copy used for comparison). The brief supersedes the raw issue body where they differ — notably the issue's "same or different cluster" phrase, which the brief already scoped to same-cluster only (ADR-0039), with explicit user confirmation.

## Verdict

⚠️ **MINOR DRIFT (proceeding)** — one deliberate, documented semantic deviation; everything else is faithful or an allowed expansion of detail.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| ⚠️ Minor | changed | Edge case 4: "Concurrent clones of one source → allowed, independent backups, no lock" | spec.md Edge Cases, bullet "Concurrent clones of the same source" | Amended at plan time: a second concurrent clone of the same source now **fails fast** with the typed `ALREADY_IN_PROGRESS` error (zero side effects, retryable) instead of running concurrently. Reason: allowing it would weaken the shipped one-environment-level-operation guard on environment backups (ADR-0055 D6). The amendment is annotated inside the spec itself and in research.md D4 and plan.md (documented deviation 2). Workaround cost is low (wait for the first clone, retry). **Flagged for user review — easy to revert if concurrency matters more than guard reuse.** |
| ✓ None | added (allowed clarification) | — | FR-008/US4, `deleteEnvironmentClone` | The clone-record escape hatch is a necessary consequence of the brief's own FR-008 (backup-deletion guard) plus crash semantics — without it a crashed clone would pin its backup undeletable forever. Consistent with the brief's ADR-0055-style deletability philosophy. |
| ✓ None | added (allowed clarification) | — | research.md D2 phase 0 (deny-all scratch policy), bounded waits, strategy-less outcome | Critique-driven hardening; the deny-all scratch isolation directly *serves* the brief's confirmed non-interference motive. |

Checked with no drift found: users/value framing; P1 journey and Given/When/Then; FR-001–FR-010 of the brief (all present, some split/renumbered into spec FR-001–FR-015); eligibility rule; copy/override split (env-level override only); capture-time consistency; failure semantics (backup-first, PARTIAL attribution, discard-and-retry); all five success criteria (verbatim); all Out-of-Scope items (cross-cluster, network isolation as P2 environment property, point-in-time clone, per-deployment overrides, config-only mode, per-deployment repair, rollback); governance gates incl. the ADMIN role.

## Action

Proceed. The single drift item is deliberate, visible in three artifacts, and cheap to reverse; it is surfaced prominently in the prep-run summary for the user's judgment rather than silently absorbed.
