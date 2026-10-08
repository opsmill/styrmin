# Spec/Ask Alignment Check: Driver Logo, Description and Links

## Source

- GitHub issue [#272](https://github.com/opsmill/styrmin/issues/272), body read with `gh issue view 272` on 2026-10-08. The issue has no comments.
- The inline ask passed to `speckit-opsmill-auto`: the three user decisions (external http(s) URL, icon + description + links, generic-icon fallback), the current-state notes, and the acceptance criteria.

## Verdict

⚠️ MINOR DRIFT (proceeding)

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| Minor | added | — | US4, FR-006, SC-005 | The spec adds a reload backfill: reloading an unchanged driver fills in `icon`, `description` and `links` on a driver version stored before this feature. The PRD does not ask for it. It follows from "persisted on driver registration" for installations that already have drivers, since the identity fast path otherwise returns the old row unchanged. It changes no other behavior and adds no new interface. |
| Minor | added | "rendered on the driver list" | FR-012 | The flat list view also shows a per-row logo. This expands "driver list" to both of its views, and is not new scope. |
| Info | added | "docs/ pages and a towncrier changelog fragment" | FR-023 | Two fragments (`added` + `changed`) instead of one, so the stricter validation appears under "Changed" (critique X1). This is more detailed than the ask, not a change to it. |
| Info | — | Decision 1 "Validate it as an http(s) URL… reject other schemes" | FR-003, FR-004 | Matched. `http` and `https` are accepted, everything else is rejected, and the same rule applies to `links[].url` through `InfoLink`. |
| Info | — | Decision 2 "authors and license stay out of scope" | FR-008 | Matched: they are accepted and not stored. |
| Info | — | Decision 3 fallback on no icon or `onError` | FR-017, SC-002 | Matched. |
| Info | — | AC "DRIVERS.md documents the logo format with a working example; at least one example driver uses it" | FR-020, FR-021 | Matched (`infrahub`, `infrahub-enterprise`). |
| Info | — | AC "E2E coverage… prefer extending an existing E2E" | SC-006, plan step 8, tasks T019–T021, T026, T041 | Matched: it extends `test_ui_smoke.py` on the session `simple-app` driver. |

No requirement from the issue or the inline ask is missing, changed, softened or contradicted.

## Action

Proceed. The two added items are kept because they serve the stated outcome (logos visible on existing and new installations, on both list views) without new interfaces. The user can drop US4 (tasks T033–T035) at review time without affecting the other stories. Remediation passes used: 0.
