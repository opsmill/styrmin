# Spec/Ask Alignment Check — `011-styrminctl-auth`

**Date**: 2026-05-17
**Source PRD**: [opsmill/styrmin#234 comment 4470324108](https://github.com/opsmill/styrmin/issues/234#issuecomment-4470324108) (fetched via `gh api repos/opsmill/styrmin/issues/comments/4470324108`).
**Compared against**: `specs/011-styrminctl-auth/spec.md` (commit `4d8a953`, updated by critique pass in `12027f3`).

## Verdict

✅ **ALIGNED** — proceed to implementation. No remediation passes required.

The spec faithfully reflects the PRD's intent. Every PRD goal, FR, user story, edge case, SC, assumption, out-of-scope, and open question is preserved or sharpened — none is missing, contradicted, or semantically changed. The spec adds two FRs and one SC, all of which are *sharpenings* (testable rewrites of statements that are present in the PRD as user stories or success criteria).

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| ℹ️ Info | added (sharpening) | PRD User Story #3 ("print the server address it is logging in against") | spec FR-012 | Spec promotes a PRD user-story line into a testable functional requirement. Same semantics; no scope change. |
| ℹ️ Info | added (sharpening) | PRD SC-005 ("Tokens for distinct backends never collide") | spec FR-013 | Spec restates SC-005 as a functional requirement with an explicit verification idea. SC-005 itself is retained verbatim. Same semantics. |
| ℹ️ Info | added (sharpening) | PRD Solution Overview ("one-time login … entire ceremony") | spec SC-006 | Spec adds an onboarding-time SC ("first-time user reaches authenticated `clusters list` in under 30 seconds"). Aligned with the PRD's spirit but not literally present. Acceptable: an additional measurable target with no scope cost. |
| ✅ | unchanged | PRD FR-001..FR-011 | spec FR-001..FR-011 | One-to-one correspondence. |
| ✅ | unchanged | PRD User Stories 1–14 | spec User Stories 1–3 (P1/P2/P3) | The PRD's flat list of 14 stories is regrouped into three prioritised journeys — the expected PRD→spec transformation. All 14 sub-themes appear in the journey narratives or acceptance scenarios. |
| ✅ | unchanged | PRD Edge Cases | spec Edge Cases | Verbatim or near-verbatim. |
| ✅ | unchanged | PRD Out of Scope | spec Out of Scope | Verbatim. |
| ✅ | unchanged | PRD Open Questions (3) | spec Open Questions (3) | Identical wording. |
| ✅ | unchanged | PRD Constitution alignment | spec carries through plan.md Constitution Check + research.md R10/R11 | The "no GraphQL schema change", "no new dependency", "single api_only E2E" and propagation-tests-N/A claims all match. |
| ✅ | unchanged | PRD Governance Gates (auth-UX only) | spec dependencies + plan.md Constitution Check | Same conclusion: auth-UX is the only gate crossed; the PRD-on-#234 is the authorisation. |

## Source coverage notes

- Inline PRD body in the user's argument was the URL itself; we fetched the full body via `gh api repos/opsmill/styrmin/issues/comments/4470324108`. 162-line PRD captured to `/tmp/source-prd.md` for the comparison. The fetch succeeded without auth failure or 404.
- No fallback to inline content was needed.
- No remediation passes were required (verdict ✅ ALIGNED on the first pass). Retry budget unused.

## Action

Proceed. The prep pipeline ends here; `tasks.md` is ready for `/speckit-implement` or `/speckit-auto-implement` when the user is ready.
