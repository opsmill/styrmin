# Spec/Ask Alignment Check: 017-post-render-env-vars

**Date**: 2026-10-02

## 1. Source

- Idea brief "Platform-owned env var injection via post-render" —
  [opsmill/styrmin#385 (comment 5956413845)](https://github.com/opsmill/styrmin/issues/385#issuecomment-5956413845),
  fetched with `gh api repos/opsmill/styrmin/issues/comments/5956413845`.
- Context from the parent issue body (#385), same fetch.

## 2. Verdict

⚠️ **MINOR DRIFT (proceeding)** — remediation passes used: 0.

Every brief requirement, journey, success criterion, out-of-scope item, and documentation
obligation is present in `spec.md` and covered by `tasks.md`. The differences below are
refinements forced by verification or by internal consistency, each with a recorded rationale.
One wording narrowing (FR-008) was corrected in place during this check.

## 3. Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | added | — (SC-004, Constitution §I) | FR-011, Edge Cases | HelmRelease `spec` replaced on update instead of merge-patched, so values-template env entries written before migration don't linger. Not in the brief; needed for SC-004 on pre-existing deployments (research D-003). Touches the operator apply path — a high-risk area — scoped to the HelmRelease call only. |
| Minor | changed | Edge Cases: "Ordering → new entries are appended; a chart `$(USER_VAR)` reference won't expand" | Edge Cases: Ordering | The brief's assumption is wrong. kustomize v5.7.1 places patched entries **first** and moves the component container to index 0, so a chart `$(USER_VAR)` reference **does** expand and a user `$(CHART_VAR)` does not. The spec documents the verified behaviour (research D-002). |
| Minor | changed | FR-003 "reject a component-scope env var write on a component with no component container" | FR-003 | Narrowed to writes that **add or change** values, judged against the **target** driver version. Unchanged re-submissions and removals pass. Without this, FR-005's kept values would block every later full-config write, and a version-switching write could store inert values (critique E1/E2). |
| Minor | changed | FR-006 "MUST NOT be able to edit … in the frontend" | FR-006 | Adds that stored values on such a component are shown read-only and **can be removed**, so upgrade-orphaned values (FR-005) can be cleaned up. |
| Minor | added | Governance: "component container on the driver-version read path" | contracts/graphql-deltas.md | Also adds `Component.container` on the deployment type (the frontend editor's data source for FR-006) and shows the container on the driver detail Components tab (critique P4). Both additive. |
| Minor | changed | FR-005 open question (shape of the flag) | FR-005, research D-005 | Resolved: new `ComponentEnvVars.isApplicable`; `isOrphaned` keeps its meaning. The brief explicitly deferred this to planning. |
| Minor | changed | §V: "SC-003 as a read-only assertion in `test_infrahub_services.py`" | research D-011, T028/T031 | That test runs on the **enterprise** stack (chart 4.19.2), whose prefect env default is `PREFECT_UI_SERVE_BASE`, not `PROMETHEUS_MULTIPROC_DIR`. The E2E asserts the enterprise default; the community chart's `PROMETHEUS_MULTIPROC_DIR=/tmp` is pinned by a render unit test. Booting the community stack would resurrect a fixture whose only consumer is skipped. SC-003's wording is unchanged. |
| Fixed | changed | FR-008 "All in-repo example drivers MUST declare component containers" | FR-008 | Spec had narrowed this to "each component that receives env vars today" (would exempt infrahub-mcp). Restored to "every component" during this check; tasks already covered all 30 components. |

No requirement, goal, non-goal, acceptance scenario, or success criterion from the brief is
missing or softened; no out-of-scope item was pulled in.

## 4. Action

Proceed. No re-run of specify/plan/critique/tasks needed. Reviewers should look at the
FR-011 operator change and the FR-003/FR-006 refinements first, since they go beyond the brief.
