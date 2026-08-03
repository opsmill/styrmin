# Spec/Ask Alignment Check: Configurable Backup Retention TTL

**Date**: 2026-08-03 | **Checked**: `spec.md` (post-critique revision, commit e5a0e9b) against the source PRD

## Source

Inline PRD supplied with the `/speckit-opsmill-prep` invocation: "PRD: Configurable backup retention TTL" (grilled idea-brief on issue #305). No URLs to resolve; the inline document is complete and is the source of truth.

## Verdict

**✅ ALIGNED**

Every PRD requirement, journey, edge case, success criterion, assumption, and out-of-scope item is present in the spec with unchanged semantics. FR-001–FR-010 and SC-001–SC-005 carry over verbatim (one deliberate strengthening of FR-005, below). The PRD's 10 user stories consolidate into the spec's 4 prioritized stories with no story left unrepresented. The PRD's Implementation/Testing Decisions sections (which belong downstream of a spec) are honored in `plan.md`/`research.md`/`tasks.md`: same module list, same GraphQL surface (2 input + 2 output fields), no new error classes, E2E as an extension of the existing backup lifecycle node, the four named propagation tests, and unchanged api_only/ui_only marking.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Info | changed (strengthened) | FR-005 | FR-005 | Spec adds: first-party clients assembling full-replacement updates from persisted config (web UI env/deployment builders) must round-trip the field. Necessary clarification from critique M1 — without it, a UI env-var edit silently wipes the stored policy, violating the PRD's own FR-005 intent. Semantics strengthened, not altered. |
| Info | added | Frontend surface ("expiry column + tooltip" only) | plan.md R7 / tasks T016, T020 | Three small frontend files beyond the PRD's literal list (`EnvironmentConfigurationTab.helpers.ts`, `lib/deployment-input.ts`, `lib/config-diff.ts`) — all in service of FR-005 preservation and diff visibility, not new UX scope. No new routes, no editor UI (PRD scope respected; critique Q1 resolved "No"). |
| Info | added | CLI surface ("Expires column on list; no new commands") | tasks T024 | `backups get` additionally prints TTL/Expires lines. No new command; same contract as the list column. Two-line expansion serving PRD user story 5 (audit). |
| Info | added | E2E scenario | tasks T017 | E2E additionally asserts `Backup.ttl`/`expiresAt` via the SDK after completion — a superset of the PRD's Velero-CRD assertion, directly verifying SC-002's "verifiable from the backup's own record". |

No PRD requirement is missing, dropped, softened, or contradicted. User story coverage map (PRD № → spec story): 1→US1, 2→US2, 3→US2-AS2, 4→US1/FR-001 (+ very-short-TTL edge case), 5→US1-AS1/FR-006, 6→US3, 7→US4, 8→US4, 9→US1-AS2/FR-003, 10→US1-AS3/FR-006.

## Action

Proceed. No remediation passes needed (counter: 0 of 2 used). `tasks.md` is ready for review and implementation.
