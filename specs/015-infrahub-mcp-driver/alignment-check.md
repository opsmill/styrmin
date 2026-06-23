# Spec/Ask Alignment Check: Infrahub MCP Server Application Driver

**Feature**: 015-infrahub-mcp-driver
**Date**: 2026-06-21
**Compared**: source PRD ↔ `spec.md`

## 1. Source

- **URL**: https://github.com/opsmill/styrmin/issues/271#issuecomment-4762259894 (comment ID 4762259894 on issue #271).
- **Resolution**: fetched the comment body via `gh api repos/opsmill/styrmin/issues/comments/4762259894` (121 lines). This is a complete, structured PRD (Problem Statement, Solution Overview, 7 User Stories, P1 Journey, FR-001..007, Key Entities, Edge Cases, SC-001..003, Implementation/Testing Decisions, Out of Scope, Open Questions, Governance Gates). Web-fetch capability present; no gating/auth issues.

## 2. Verdict

✅ **ALIGNED** — proceeding.

## 3. Findings

| Severity | Category | PRD reference | Spec reference | Description |
|----------|----------|---------------|----------------|-------------|
| ℹ️ Info | added (benign) | FR-006 ("rendered values MUST contain no `infrahub.apiToken`") | spec SC-004 | Spec adds SC-004 ("Rendered Helm values … contain no `apiToken` key") as a **measurable** success criterion. This is a restatement of the PRD's own FR-006 to make it verifiable — explicitly allowed (fleshing out an implicit requirement), not new scope. |
| ℹ️ Info | structure (not drift) | PRD's 7 User Stories | spec's 4 User Stories (US1–US4) | Spec consolidates the PRD's 7 stories into 4 prioritized, independently-testable stories with no loss: PRD#1+#2→US1 (deploy + passthrough/no stored token), PRD#3→US2 (read-only), PRD#4→US3 (log level), PRD#5+#7→US4 (clean load + catalogue), PRD#6→US1/FR-002 (internal http Service). Cosmetic restructuring, not drift. |

**No 🛑 / ⚠️ findings.** Specifically verified absent:

- **Missing**: none. FR-001..007 appear verbatim; SC-001..003 preserved; P1 journey + acceptance preserved; all 4 edge cases preserved; all 5 Out-of-Scope items preserved; Key Entities preserved.
- **Added (scope creep)**: none beyond the benign SC-004 restatement above. No new requirement, parameter, auth mode, or capability introduced.
- **Changed semantics**: none. `token-passthrough` still fixed; `infrahub_address` still required/no-default; `mcp_read_only` default `false`; `mcp_log_level` enum default `info`; port 8001 internal http; `supported_versions: >=1.1,<2.0`; no `actions`.
- **Dropped/softened acceptance**: none.
- **Contradicted constraints**: none. The owner-approved E2E skip and new-dependency gate are honored, not re-litigated; the PRD Open Question (chart coordinates + selector label) is preserved as a spec Assumption and an ordered task (T002).

## 4. Action

Proceed. No remediation pass required (alignment is clean). `tasks.md` already generated and committed. The feature is ready for review / implementation.
