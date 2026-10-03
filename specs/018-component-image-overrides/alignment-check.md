# Spec/Ask Alignment Check: 018-component-image-overrides

**Date**: 2026-10-03

## 1. Source

- Idea brief "per-component image overrides (post-render)":
  [opsmill/styrmin#20 (comment 5973303433)](https://github.com/opsmill/styrmin/issues/20#issuecomment-5973303433),
  fetched with `gh api repos/opsmill/styrmin/issues/comments/5973303433`.
- Context only (superseded by the brief, not used as requirements): the issue body, the values-path
  PRD comment, and the direction-change comment on #20.

## 2. Verdict

⚠️ **MINOR DRIFT (proceeding)**

Every brief journey, FR-001 to FR-012, edge case, success criterion, assumption, out-of-scope item,
governance gate, and test is present in `spec.md` with the same semantics. The brief's one open
question is resolved as the brief recommended. The differences below are clarifications forced by
the codebase, or additions that protect the brief's own success criteria. None removes or softens a
requirement.

## 3. Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | changed | FR-008 "`styrminctl apply` impact output MUST list … before the user confirms" | FR-008, Clarifications Q2, Assumptions | `styrminctl apply` has no impact preview and no confirmation step today. The spec prints the pinned-override warning in `apply`'s output and adds no interactive prompt, so it never blocks a CI apply. The UI upgrade dialog warns before Confirm, as the brief says. Adding a confirmation to `apply` would be a larger, unrequested change. |
| Minor | added | FR-009 (write-time and render-time rejection) | FR-009, User Story 4 Sc.5, edge cases | A version change that would make a stored reference invalid after substitution is rejected before any task starts (critique E2). Without it, the driver's upgrade action stops components before the render fails, which works against SC-004 ("rejected before any pod restarts"). Strictly stronger than the brief. |
| Minor | added | FR-007 "fail the reconcile visibly" | FR-007, plan D-004 | Making the failure visible needs the operator to read the HelmRelease's failure and fail the deployment with a new typed `COMPONENT_CONTAINER_NOT_FOUND`. Today a failed HelmRelease surfaces only as a generic timeout, or not at all after an update. A necessary implementation consequence of the brief's FR-007 and SC-005. |
| Minor | added | FR-012 "upgrade actions select by the component container" | FR-012, plan D-010 | `get_component_images` now returns the component container's image first, so actions can select it without a new primitive (still out of scope). The return type and contents are unchanged. |
| Minor | added | Open question (shared FR-007 guard) | Clarifications Q1, FR-007 | Resolved "yes", as the brief recommended: the guard also runs for env-var-only patches. |
| Minor | added | Edge cases | Edge cases | New documented edge cases: image pull failures (Pods tab), rebuilt images under the same tag, stranded overrides on an environment clone source, and an override plus a version change in one `apply`. Documentation only; no new behaviour. |
| Minor | added | FR-006 "stranded by a driver upgrade" | FR-006 | Also covers an override whose component the driver no longer declares (orphaned), with the same "kept, not applicable, never injected" rule env vars use. |
| — | — | Testing (3 E2E tests, `shard_configuration`, entrypoints, re-tagged `simple-app` 0.1.0/0.2.0) | Dependencies; tasks T036, T050, T054, T065 | Matches the brief exactly. |
| — | — | Governance gates (no migration, GraphQL yes, no dependency, no CI change, no auth change) | Assumptions; plan Constitution Check | Matches. The critique deliberately placed the Kustomize tests in the existing integration job so CI stays unchanged. |

## 4. Action

Proceed. No remediation pass needed (0 of 2 used). The `apply` warning timing (first finding) is the
one point the issue author may want to confirm before implementation.
