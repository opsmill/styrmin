# Spec/Ask Alignment Check

**Feature**: 011-admin-user-group-mgmt
**Date**: 2026-05-11
**Verdict**: ⚠️ MINOR DRIFT (proceeding)

## Source

- GitHub issue [opsmill/styrmin#180](https://github.com/opsmill/styrmin/issues/180), full body fetched at the start of Phase 1 via `gh issue view` (no auth gating, full body retrieved).
- The issue is a detailed PRD with: a Problem Statement, a Solution paragraph, 33 numbered User Stories, an Implementation Decisions section (GraphQL surface, admin guards, membership module, SDK, frontend, documentation, phasing), a Testing Decisions section (unit / integration / frontend / E2E / propagation / prior art), an Out of Scope list, and Further Notes.

## Coverage trace — 33 PRD user stories → spec.md

| PRD # | PRD intent (one-liner) | Spec coverage |
|---|---|---|
| 1 | Admin creates user (username, displayName, initial password, role, optional groups) | US2 Acceptance #3; FR-001 |
| 2 | Admin edits user (displayName, role, groups, active) | US2 Acceptance #4; FR-002 |
| 3 | Admin resets another user's password (no current pwd) | US2 Acceptance #5; FR-003 |
| 4 | Admin password reset invalidates target's existing sessions | US2 Acceptance #5; FR-003 explicit |
| 5 | Admin deactivates user (preserves attribution) | US2 Acceptance #6; FR-002, FR-009 |
| 6 | Deactivation reversible | US2 Acceptance #7 |
| 7 | Hard-delete only when no FK refs | US2 Acceptance #8/9; FR-004 |
| 8 | Refuses zero-active-admin operations (incl. self) | US2 Acceptance #10; Edge Cases; FR-010 |
| 9 | Paginated table of users | US2 Acceptance #1; FR-020 |
| 10 | Filter list by active / role / search | US2 Acceptance #2; FR-006, FR-020 |
| 11 | Groups admin page mirrors Users page | US3 Acceptance #1–4; FR-021 |
| 12 | Group edit: role + replace full member set in one submission | US3 Acceptance #3; FR-005 + set semantics |
| 13 | Login page when unauthenticated | US1 Acceptance #1; FR-024 |
| 14 | Generic "Invalid username or password." | US1 Acceptance #2; FR-024 |
| 15 | Display name + role badge in header | US1 Acceptance #3; FR-018 |
| 16 | Header menu with Profile + Logout | US1 Acceptance #4; FR-018 |
| 17 | Profile page (display name + password change) | US4 Acceptance #1–2; FR-019 |
| 18 | Password change requires current password | US4 Acceptance #3; FR-019 |
| 19 | Password change invalidates *other* sessions (preserves caller) | US4 Acceptance #2; FR-019 explicit |
| 20 | read_only users: mutation buttons hidden (not disabled) | US5 Acceptance #1; FR-022 |
| 21 | read_write users: admin-only buttons hidden | US5 Acceptance #3; FR-022 |
| 22 | read_only users: Users/Groups nav hidden | US5 Acceptance #2; FR-023 |
| 23 | Admin-via-group sees admin UI (effectiveRole) | US5 Acceptance #4; Assumptions |
| 24 | UNAUTHENTICATED → redirect to login | US1 Acceptance #6; FR-016 |
| 25 | FORBIDDEN → in-place error, no redirect | US1 Acceptance #7; FR-016 |
| 26 | Direct nav to /users or /groups without admin → / | US5 Acceptance #5; FR-017 |
| 27 | Authenticated nav to /login → / | US1 Acceptance #5; FR-017 |
| 28 | SDK client.users.* and client.groups.* | US6 Acceptance #1–3; FR-013, FR-014 |
| 29 | Deployment.createdBy.username for UiScenarioDriver | FR-028; Phase 11 (US11) |
| 30 | Lifecycle E2E api-mode + ui-mode | US8 Acceptance #1–2; FR-026 |
| 31 | User-facing guide in dev/guides/ | US7; FR-025 |
| 32 | Existing UI-mode E2E uses Playwright cookie injection at session start | US8 Acceptance #3; FR-027; SC-007 |
| 33 | Auth-lifecycle E2E drives the login form (no cookie injection) | US8 Acceptance #2; FR-026 |

**All 33 PRD user stories trace to the spec.** No missing requirements, no semantic changes, no acceptance-criterion softening.

## Coverage trace — PRD Out-of-Scope → spec.md Assumptions

| PRD OOS item | Spec coverage |
|---|---|
| All of #179's foundation work | Context paragraph + Assumptions #1 |
| SSO / OIDC / SAML | Assumptions |
| API tokens / service accounts | Assumptions |
| Per-resource ACLs / ABAC | Assumptions |
| Email-based password reset, MFA, session-revocation UI | Assumptions |
| Brute-force / lockout protection | Assumptions |
| Cursor / server-side pagination on users / groups | Assumptions |
| Dedicated "Users with FK references" UI | Assumptions + contracts/frontend.md (delete button + server error toast) |
| styrmin login CLI subcommand | Assumptions |
| Audit-log table; logs remain stdout-only | Assumptions + FR-030 (stdout-only audit log line, consistent with PRD) |

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| ⚠️ | added | not in PRD | FR-029 (password masking in request logs) | Spec adds a requirement that GraphQL request-logging masks `password`, `newPassword`, `currentPassword`. Not in the PRD. Engineering critique (E5) identified this as a security must-address. Compatible with PRD's overall "logs remain stdout-only" stance; closes a real cleartext-leak path. Documented in critique-20260511.md. |
| ⚠️ | added | not in PRD (compatible) | FR-030 (admin-mutation stdout audit log) | Spec adds a structured stdout log line per admin mutation. The PRD's Out-of-Scope is explicit: "Audit-log table; logs remain stdout-only." A stdout line is the documented mechanism — this is the PRD's "stdout-only" policy made concrete, not new scope. Recorded as drift only because the field-by-field detail is not literally in the PRD. |
| ⚠️ | added (engineering correctness, not user-visible) | PRD §"Implementation Decisions / Admin guards" | FR-010 (transactional last-admin guard) | PRD says the guard runs on each mutation; spec tightens this to require row-level locking or isolation guarantees so a concurrent demotion race cannot leave the system with zero admins. Engineering critique (E3). This is HOW the PRD's last-admin guarantee is honoured under concurrency — not a new user-visible requirement. |
| ⚠️ | clarification (no change) | PRD §32 ("do not slow down or flake") | SC-007 | Spec replaces the ≤ +5% wall-clock CI bound with a structural fixture-shape check. The PRD's intent is "existing tests don't pay a per-test login cost"; the structural check is the auditable form. |
| ✅ | aligned | PRD §3 (Profile) | US4 Acceptance #4 | Spec adds a Profile acceptance scenario for the read-only username field with helper text. PRD says "Profile lets the user change display name and password" and elsewhere mandates `username` immutable; the read-only display is the implementation of that policy. Not drift. |

**Significant-drift count**: 0. Three ⚠️ entries are "added requirements" but none of them change user-visible scope: FR-029 closes a defensive gap, FR-030 makes the PRD's stdout-only audit stance concrete, FR-010 tightens correctness on an already-listed guard. No PRD requirement is missing, weakened, or contradicted.

## Action

**Proceed.** No remediation pass required. The three ⚠️ entries are defensible engineering additions surfaced by the Phase 3 critique and explicitly recorded in `critiques/critique-20260511.md`. They strengthen the spec relative to the PRD without conflicting with any PRD intent.

For reviewer awareness: the deltas above are the only points where the spec goes beyond the literal PRD wording. They were applied autonomously per the speckit-auto-prep contract ("apply must-address findings inline"). If any reviewer prefers strict PRD literalism, FR-029 / FR-030 / FR-010's concurrency clause can be backed out and recorded as follow-ups to issue #180 — but doing so reintroduces the engineering risks captured in critique-20260511.md.
