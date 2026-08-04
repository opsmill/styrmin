# Feature Specification: Backend No-Op Detection for Deployment Updates

**Feature Branch**: `009-deployments-apply` (redesign lands on the existing branch before merge)
**Created**: 2026-05-27
**Status**: Extracted
**Input**: User description: "Make `styrminctl deployments apply` idempotent without putting change-detection logic in the CLI. The CLI sends the full desired state every time; the backend decides whether anything actually changed and only then creates a new ApplicationInstance + dispatches a reconcile Task. A no-op update must not error and must not produce side effects." (full grilled brief in `.specify/idea-brief.md`)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Idempotent re-apply is a clean no-op (Priority: P1)

An operator (or a CI pipeline) applies a deployment manifest, then re-applies the identical manifest as part of the normal declarative loop ("make sure the live state matches my file"). The second apply must do nothing and say so — no error, no churn.

**Why this priority**: This is the headline defect. Today a re-apply either errors outright (manifest with no config/parameters) or silently churns (creates a throwaway `Instance` and dispatches a reconcile `Task` that is then discovered to be a no-op). Idempotent re-apply is the core promise of a declarative `apply` command; without it the command is unsafe to run repeatedly, which defeats its purpose.

**Independent Test**: Create a deployment from a manifest, let it settle, then re-apply the identical manifest. Verify no new `Instance` is created, no reconcile `Task` is dispatched, the deployment's active instance and status are unchanged, and the command exits successfully reporting the deployment as unchanged.

**Acceptance Scenarios**:

1. **Given** a `Deployment` created from `app.yaml` that has reached a steady state, **When** the operator runs `apply -f app.yaml` again with no change to the manifest, **Then** no new `Instance` is created, no reconcile `Task` is dispatched, the active instance and deployment status are untouched, and the command exits 0 reporting the deployment as `unchanged`.
2. **Given** a manifest that carries no `spec.config` and no `spec.parameters`, **When** it is applied to an already-existing deployment with the same driver and version, **Then** the update is accepted as a no-op (no error) rather than rejected.

---

### User Story 2 - A real change dispatches exactly one reconcile (Priority: P2)

An operator edits one part of the manifest and re-applies. Only the slice that actually changed should drive work; the unchanged slice must stay a no-op.

**Why this priority**: Protects against regression — the no-op detection must not suppress legitimate changes, and a partial edit must not over-dispatch (e.g. trigger both a config update and a version upgrade when only one changed).

**Independent Test**: Apply a baseline, then re-apply with only `spec.config` changed; verify exactly one config-update reconcile is dispatched and the version path stays a no-op. Repeat with only `spec.version` changed.

**Acceptance Scenarios**:

1. **Given** a steady-state deployment, **When** the operator changes only `spec.config` (version unchanged) and re-applies, **Then** exactly one config-update reconcile is dispatched and the version path is a no-op.
2. **Given** a steady-state deployment, **When** the operator changes only `spec.version` (config unchanged) and re-applies, **Then** exactly one version-upgrade reconcile is dispatched and the config path is a no-op.

---

### Edge Cases

- **No active instance** (e.g. a failed initial deploy left the deployment with none): the comparison has no current instance to compare against, so the apply is treated as a creation of the realised state and a reconcile is dispatched — not a no-op.
- **Effective change via inherited context**: the manifest's `spec.config` is byte-identical to before, but the deployment's `Environment` or `Cluster` configuration has changed such that the *resolved* desired state differs. This MUST be detected as a change (reconcile dispatched), because the comparison is against the fully-resolved desired state, not the raw manifest fields.
- **`parameters` (merge semantics)**: a parameter re-submitted at its existing value is a no-op; a new or changed parameter value is a change.
- **Failed deployment, unchanged manifest**: re-applying an unchanged manifest to a deployment in a terminal-failure state remains a no-op (the comparison is desired-vs-current *intent*, not health). Recovering a broken-but-unchanged deployment is explicitly out of scope (see Out of Scope).
- **Concurrent re-applies**: behaviour is unchanged from the existing apply implementation (last writer wins on the realised state); no-op detection neither introduces nor resolves concurrency races.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When a deployment update is requested, the system MUST compare the requested desired state against the deployment's current realised state **before** creating a new realised instance or dispatching reconciliation work. If the comparison finds no difference, the system MUST NOT create a new instance, MUST NOT dispatch a reconcile task, MUST NOT change the deployment's status, MUST NOT move the active-instance pointer, and MUST report the update as a no-op. *(Scope note: the no-op guarantee covers realised instances, reconcile tasks, status, and the active-instance pointer. The deployment record's own `updated_on` timestamp may still change, because the desired-state intent is persisted before the comparison runs — see plan.md M2. "No side effects" in this spec means "no realised-state churn," not "zero database writes.")*
- **FR-002**: The same no-op detection MUST apply to a deployment *version* update: requesting the deployment's current version (with no other change) MUST be a no-op (no new instance, no task), and requesting a different version MUST proceed as an upgrade.
- **FR-003**: The system MUST NOT reject a deployment update that resolves to no change. The previous "at least one of config, parameters, name, or service-name overrides must be provided" rejection is removed; an update that turns out to be a no-op succeeds quietly.
- **FR-004**: The command-line tool MUST send the full desired state on every apply and MUST NOT perform client-side change detection (it MUST NOT decide locally whether to skip the update, and MUST NOT compare versions locally). The prior client-side stopgap that skipped empty updates and compared versions is removed.
- **FR-005**: The system MUST report back to the caller whether an update resulted in work or was a no-op, and the command-line tool MUST render that distinction to the operator (e.g. `unchanged <name>`) using only the backend's signal — it MUST NOT derive "unchanged" by inspecting the deployment itself.
- **FR-006**: A no-op apply against a deployment in a terminal-failure state MUST remain a no-op (no reconcile dispatched).
- **FR-007**: The batch/idempotency summary the command prints MUST account for no-op outcomes distinctly from created and updated outcomes, and a run consisting solely of no-ops MUST exit successfully (non-error).

### Key Entities

- **Deployment**: the desired-state record identified by `(name, environment)`. Its status is left untouched by a no-op update.
- **Instance** (`ApplicationInstance`): the realised snapshot generated from a deployment. The defect this feature fixes is that a no-op update currently creates a throwaway instance; after this feature, no instance is created for a no-op.
- **Task**: the reconcile-tracking record. None is created for a no-op; the absence of a task is the signal the caller reads to distinguish "unchanged" from "updated".

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Re-applying an unchanged manifest creates **0** new realised instances and **0** new reconcile tasks, and leaves the active-instance pointer and deployment status unchanged (measured by comparing instance/task counts and the deployment's active-instance + status immediately before and after the re-apply). The deployment's `updated_on` timestamp is explicitly *not* part of this criterion.
- **SC-002**: Re-applying an unchanged manifest completes successfully (success exit code) and reports the deployment as unchanged — it never returns an error.
- **SC-003**: No regression on real changes — a config-only change drives exactly **1** reconcile and a version-only change drives exactly **1** upgrade.
- **SC-004**: A no-op apply against a failed deployment drives **0** reconciles.
- **SC-005**: An operator can run the same `apply` command repeatedly any number of times and observe steady-state convergence — the first run reports created/updated, every subsequent unchanged run reports unchanged with no side effects.

## Assumptions

- The existing desired-vs-current instance comparison (which excludes volatile fields such as identity, generated name, and status) is the correct definition of "no change" for an apply. A no-op means "the resolved desired state equals the current realised state," not "the manifest text is identical."
- Recovery of a broken-but-unchanged deployment is performed through a separate mechanism (a future redeploy/refresh operation), not through `apply`.
- This feature replaces a client-side stopgap already committed on the `009-deployments-apply` branch; that stopgap is reverted as part of implementing FR-004.

## Limitations

- **Rebuilt image under an unchanged version**: `apply` compares the *resolved desired state*, which is keyed on the application version (and driver version), not on image content. An application image rebuilt and re-pushed under the **same** version, with unchanged config, resolves to an identical instance and is therefore a no-op — `apply` will not redeploy it. This is consistent with the version model; forcing a redeploy in that situation is the future refresh path (out of scope).

## Out of Scope (v1)

- A field-level "what changed" report beyond the created / updated / unchanged distinction.
- Exposing a user-facing redeploy/refresh operation to force-reconcile a failed-but-unchanged deployment.
- Collapsing the separate config-update and version-upgrade reconciles into a single pass when both change at once (behaviour is unchanged from the existing apply: config first, then version).

## Dependencies

- Builds on the existing `009-deployments-apply` declarative apply feature (manifest schema, `apply`/`apply_files`, the `(name, environment)` lookup) and the existing server-side desired-vs-current comparison and reconciliation machinery.
