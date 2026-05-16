# Extraction Record

**Extracted on**: 2026-05-15
**Extracted by**: speckit.extract

## ADRs Created

None — the architectural decisions in this feature are direct applications of the existing
[ADR-014: Pod-status records reflect observed state, not declared state](../../dev/adr/adr-014-pod-status-records-observed-state-not-declared-state.md).
The three-bucket grouping (declared / drifting / unlabeled) is that ADR applied at the UI
boundary; staleness thresholds and the `ui_only` E2E marking are reversible UX defaults.
`plan.md` §6 explicitly recorded that "none of the choices warrant a new ADR."

## Knowledge Updated

- `dev/knowledge/frontend/ui-primitives.md` — new sections: "Clipboard hook" (the shared
  `useCopyToClipboard` API at `frontend/src/hooks/use-copy-to-clipboard.ts`) and
  "Hand-rolled collapsible-section pattern" (when to reach for the pattern used by
  `PodSection` + `KubectlCommands` instead of the Base UI `Collapsible` wrapper).
- `dev/knowledge/backend/e2e-testing.md` — new section: "Testing clipboard interactions"
  (Chromium's `grant_permissions(["clipboard-read", "clipboard-write"])` requirement,
  read-back via `page.evaluate`, and a pointer to `tests/e2e/pages/pods_tab.py` as the
  canonical example).

## Guidelines Updated

- `dev/guidelines/frontend/data-fetching.md` — new section: "Tab-scoped polling"
  (prescriptive rule: gate both `enabled` and `refetchInterval` on the active-tab boolean;
  why `refetchIntervalInBackground: false` alone is insufficient).
- `dev/guidelines/frontend/ui-primitives.md` — new section: "Clipboard" (use the shared
  hook, surface `copied` in the UI).

## Skipped Content

- `plan.md` §3 Phases & sequencing — execution artifact, no durable knowledge.
- `plan.md` §5 Visual contract — implementation detail captured in the source.
- `plan.md` §6 Open questions / defaults — UX preferences resolved during implementation.
- `plan.md` §4 Test plan summary — captured in the actual test files.
- The `shouldSectionAutoExpand` heuristic — feature-specific UX policy documented in the
  function's own JSDoc.
- Reference to issue #207 (last-terminated context) — tracked as its own follow-up.

## Notes

This spec is non-standard: only `plan.md` exists (no `spec.md` or `research.md`). The
PRD lives on opsmill/styrmin#204 (comment 4412816851); the implementation lives in the
merged commits on `feature/012-deployment-pods-tab`.

## Archive

Spec directory moved to `specs/archive/012-deployment-pods-tab/` as a historical record.
