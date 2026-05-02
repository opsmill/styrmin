---
description: "Task list for deployment deletion (008)"
---

# Tasks: Deployment Deletion

**Input**: Design documents from `/specs/008-deployment-deletion/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: User story this task belongs to (US1–US6 from spec.md)
- File paths are absolute relative to repo root

## Path conventions

Web application layout (`backend/`, `frontend/`, `python_sdk/`, `helm/`) per `plan.md` § *Project Structure*.

---

## Phase 1: Setup

No new dependencies, lockfile changes, or scaffolding are required by this feature. The existing `uv sync` / `pnpm install` are the only setup steps and are assumed to have been run already.

- [ ] T001 [P] Verify dev env: `uv sync --all-groups --all-packages` and `cd frontend && pnpm install` complete cleanly on this branch (no Phase-2 work depends on a fresh install, but all `uv run invoke generate` and codegen steps require these to have run).

---

## Phase 2: Foundational (blocking prerequisites)

**⚠️ CRITICAL**: Every user story below depends on these landing first. They establish the lifecycle states, the CRD shape, and the data column that all higher-level work reads from.

### CRD schema delta

- [ ] T002 Add `spec.deletionRequested: bool` (default `false`) with `x-kubernetes-validations` CEL rule `!has(oldSelf.deletionRequested) || oldSelf.deletionRequested == false || self.deletionRequested == true` to `helm/agent/crds/styrmin.io_styrmindeployments.yaml`. (Contract: `specs/008-deployment-deletion/contracts/crd.md`.)
- [ ] T003 Add `Deleted` to `status.phase` enum and `Deleting` + `Deleted` to `status.displayState` enum in `helm/agent/crds/styrmin.io_styrmindeployments.yaml`. (`Deleting` is already present in `phase`.)
- [ ] T004 Re-apply the CRD on local dev cluster (`kubectl apply -f helm/agent/crds/styrmin.io_styrmindeployments.yaml`); confirm the API server accepts the new schema and the CEL rule rejects a `true → false` patch on a hand-crafted CR.

### CRD-side Pydantic models

- [ ] T005 Extend `DisplayState` with `DELETING = "Deleting"` and `DELETED = "Deleted"`, extend `DeploymentPhase` with `DELETED = "Deleted"`, and add `DELETED = "Deleted"` to `ConditionType` in `backend/styrmin_backend/operator/crd/schema.py`.
- [ ] T006 Add `deletion_requested: bool = Field(default=False, alias="deletionRequested")` to `StyrminDeploymentSpec` in `backend/styrmin_backend/operator/crd/schema.py`.

### DB enum + column + migration

- [ ] T007 Add `DELETING = "deleting"` and `DELETED = "deleted"` to `DeploymentState` in `backend/styrmin_backend/db/models.py`. Add `DELETE_DEPLOYMENT = "delete_deployment"` to `TaskType` in the same file. Add `deleted_at: datetime | None = Field(sa_type=DateTime(timezone=True), default=None, index=True)` (with `# type: ignore[call-overload]` matching the existing pattern) to the `Deployment` table.
- [ ] T008 Mirror the same enum additions and the `deleted_at` field onto the domain `Deployment` model in `backend/styrmin_backend/domain/models.py`. Add `is_deleted` and `can_be_deleted()` helpers per `data-model.md` § *Domain Layer*.
- [ ] T009 Generate alembic migration `backend/styrmin_backend/db/migrations/versions/<rev>_deployment_deletion.py`: add `deleted_at` column + index, extend `DeploymentState` enum (`DELETING`, `DELETED`), extend `TaskType` enum (`DELETE_DEPLOYMENT`). No backfill. Down-revision must point to the latest existing migration on `develop`.
- [ ] T010 Run `uv run invoke migrate` against a clean dev DB; confirm the upgrade succeeds and the downgrade is reversible (where Postgres allows it — enum-value adds typically only support the upgrade direction; document if so).

### Repository helpers

- [ ] T011 In `backend/styrmin_backend/repository/deployment.py`: extend the list query to accept an `include_deleted: bool = False` parameter. When `False`, apply `WHERE deleted_at IS NULL`. Keep `find(id=...)` unchanged (must remain unfiltered, per spec FR-022 / R6 in research.md).
- [ ] T012 Add a helper to set `deleted_at = now()` atomically with a status flip (or document that the existing `save(deployment)` call covers both fields in the same UnitOfWork commit, which is the actual mechanism).

**Checkpoint**: foundation ready — CRD knows the new field, DB knows the new states + column, repository can filter on `deleted_at`. User stories may now begin.

---

## Phase 3: User Story 1 — Delete a running deployment end-to-end (Priority: P1) 🎯 MVP

**Goal**: An operator can trigger deletion via the GraphQL API; the operator on the cluster tears down all owned resources; the platform record is tombstoned only after the namespace is gone; the timeline records the action.

**Independent test**: Deploy a sample app, call `deleteDeployment(id)` over GraphQL, observe `Deployment.status` go `RUNNING → DELETING → DELETED` with `deletedAt` populated and the namespace `styrmin-{id}` removed from the cluster.

### Service layer

- [ ] T013 [US1] Add `delete_deployment(deployment_id, uow) -> Task` to `backend/styrmin_backend/services/deployment.py` per `plan.md` and `research.md` R5. Implements: (a) lookup deployment (`DeploymentNotFoundError` if not found OR `deleted_at IS NOT NULL`), (b) reject `RESTORING` with `DeploymentRestoringError`, (c) on `DELETING` return the most recent existing `DELETE_DEPLOYMENT` task without re-patching, (d) on `PENDING/DEPLOYING/RUNNING/FAILED` patch `spec.deletionRequested=true` on the CR via `kr8s`, create a `DELETE_DEPLOYMENT` task with `status=SUCCESS`, emit a timeline event in the same UnitOfWork, return the task.
- [ ] T014 [US1] Add `DeploymentRestoringError` to `backend/styrmin_backend/services/exceptions.py` (sibling of `DeploymentNotFoundError`) with `error_code = "DEPLOYMENT_RESTORING"`. Reuse existing `DeploymentNotFoundError` for the `DELETED` and unknown-id cases (intentional conflation per research.md R5/R6).

### Status reporter mapping

- [ ] T015 [US1] Extend `_DISPLAY_STATE_TO_STATUS` in `backend/styrmin_backend/services/deployment_status.py` with `"Deleting": DeploymentState.DELETING` and `"Deleted": DeploymentState.DELETED`. When the projected target state is `DELETED` and the row's current `status != DELETED`, set `deployment.deleted_at = datetime.now(tz=timezone.utc)` in the same loop iteration before `await uow.deployments.save(deployment)`. This is the **only** code path that writes `deleted_at`.

### Operator reconciliation

- [ ] T016 [US1] In `backend/styrmin_backend/operator/handlers/styrmin_deployment.py`, observe `spec.deletionRequested` on update events. When the flip is observed and `status.phase != Deleted`, run the teardown pipeline in reverse order: delete owned `Service`s → delete the `HelmRelease` → delete `NetworkPolicies` and `Secrets` → delete the namespace `styrmin-{id}`. Update `phase` and `displayState` to `Deleting` while in flight. Emit per-step conditions on completion.
- [ ] T017 [US1] In the same handler, when the namespace is verified gone (kr8s GET → 404), set `phase: Deleted`, `displayState: Deleted`, and append a `Deleted` condition with `lastTransitionTime = now()` and `reason: NamespaceGone`. The `@kopf.on.delete` safety-net handler stays unchanged but must short-circuit cleanly when teardown has already happened.

### GraphQL surface (mutation)

- [ ] T018 [US1] In `backend/styrmin_backend/api/schema/mutation.py`, add `delete_deployment(self, deployment_id: UUID, uow: UnitOfWork) -> Task` resolver decorated as a `strawberry.mutation`. Wires through `services.deployment.delete_deployment`. Errors propagate via `StructuredErrorExtension` (codes: `DEPLOYMENT_NOT_FOUND`, `DEPLOYMENT_RESTORING`).

### Timeline rendering

- [ ] T019 [US1] In `backend/styrmin_backend/services/deployment_timeline.py` (and any frontend timeline label table), register `DELETE_DEPLOYMENT` as a renderable task type with a human-readable label and an icon hint. The event payload reuses the `Task` row.

### GraphQL propagation tests (mandatory — Constitution §V)

- [ ] T020 [US1] Create `backend/tests/unit/api/schema/test_propagation_delete_deployment.py` covering full propagation per `dev/guides/graphql-propagation-tests.md`:
  - mutation `deleteDeployment` write path → resolver → service → repository → DB; assert `Deployment.status` becomes `DELETING` after status reporter projects the displayState back, `Task` row created with `type=DELETE_DEPLOYMENT`, timeline event present.
  - guard rails: `RESTORING` deployment → `DEPLOYMENT_RESTORING` code; tombstoned (`DELETED`) deployment → `DEPLOYMENT_NOT_FOUND`; unknown id → `DEPLOYMENT_NOT_FOUND`.
  - idempotency: second call while `DELETING` returns the same task id.

### E2E test (mandatory — Constitution §V)

- [ ] T021 [US1] Create `backend/tests/e2e/test_delete_deployment_api.py` with `@pytest.mark.api_only(reason=...)` and `@pytest.mark.ci`. Drives via the SDK. Steps: deploy a sample driver → wait `RUNNING` → create a backup → call `delete_deployment(id)` → assert the returned `DELETE_DEPLOYMENT` task is `SUCCESS` → poll until `Deployment.status == DELETING` → wait until namespace `styrmin-{deployment_id}` no longer exists (`kubectl get ns ...` returns 404) → assert `Deployment.status == DELETED` and `deletedAt is not None` → assert `deployments(includeDeleted=False)` does not include the id and `deployments(includeDeleted=True)` does → assert the previously-created `Backup` row is still resolvable → assert the deployment's timeline contains a `DELETE_DEPLOYMENT` event.
- [ ] T022 [US1] Run `sleep infinity | uv run pytest backend/tests/e2e/test_delete_deployment_api.py -v -s --pdb 2>&1 | tee /tmp/pdb.log` and observe a green pass. (Per `AGENTS.md`: `--pdb` is mandatory; the dummy stdin keeps the cluster alive on failure.)

**Checkpoint**: User Story 1 fully functional and testable independently. The MVP is shippable here — the destructive path works end-to-end through the API; subsequent stories add UI, list filtering, audit guarantees, SDK ergonomics, and forensic GC.

---

## Phase 4: User Story 2 — Confirm before destroying (Priority: P1)

**Goal**: An operator using the UI cannot accidentally delete a deployment with a misclick — they must type the deployment name exactly to enable the destructive button.

**Independent test**: With US1 in place, open the new dialog, attempt to confirm with empty/wrong/case-mismatched input, then with the exact name; verify the destructive button gates accordingly.

### Frontend dialog

- [ ] T023 [P] [US2] Create `frontend/src/pages/deployments/components/DeleteDeploymentDialog.tsx`. Type-to-confirm pattern (case-sensitive `===`, no trim, no normalisation). Body copy enumerates: workload + namespace teardown, retained backups, "Show deleted" reveal window. On confirm: fire the `deleteDeployment` mutation (urql), close dialog, navigate to `/deployments` list (`replace`, not `push`).
- [ ] T024 [US2] Add a **Delete** button to `frontend/src/pages/deployments/DeploymentDetailPage.tsx` beside the existing Upgrade/Redeploy actions. Hidden/disabled when `deployment.status` is `DELETING` or `DELETED`. Clicking opens `DeleteDeploymentDialog`.

### Frontend unit tests

- [ ] T025 [P] [US2] Add Vitest + React Testing Library coverage for `DeleteDeploymentDialog.tsx`: button disabled with empty / wrong / case-mismatched / trimmed-whitespace input; enabled only on exact match; clicking the destructive button fires the mutation.

**Checkpoint**: US2 ready in isolation — operator can no longer trigger deletion without explicit confirmation.

---

## Phase 5: User Story 3 — See deletion progress and find deleted deployments later (Priority: P2)

**Goal**: Default list view excludes tombstoned deployments but keeps `DELETING` rows visible with a badge; a `Show deleted` toggle reveals greyed-out tombstones.

**Independent test**: Trigger a delete and watch the list — `Deleting...` badge during teardown, row disappears once `DELETED`. Toggle Show deleted; row reappears greyed. Toggle off; row disappears again. No page reload.

### GraphQL surface (query argument + scalar field)

- [ ] T026 [P] [US3] In `backend/styrmin_backend/api/schema/query.py`, extend the `deployments` resolver with `include_deleted: bool = False`. Pass through to `repository.deployment.list(..., include_deleted=...)`. Default applies `WHERE deleted_at IS NULL`.
- [ ] T027 [P] [US3] In `backend/styrmin_backend/api/definitions/deployment/model.py`, expose `deleted_at` as the GraphQL scalar field `deletedAt: DateTime` (nullable).

### GraphQL propagation tests (mandatory — Constitution §V)

- [ ] T028 [US3] Extend `backend/tests/unit/api/schema/test_propagation_delete_deployment.py` (or add a sibling file `test_propagation_deployments_include_deleted.py`) covering: read of `Deployment.deletedAt`; `deployments(includeDeleted=False)` excludes tombstoned rows; `deployments(includeDeleted=True)` includes them; `deployment(id)` returns tombstoned rows unfiltered.

### Frontend list

- [ ] T029 [US3] Update `frontend/src/pages/deployments/DeploymentList.tsx`: add `Show deleted` toggle on the right side of the page header. Toggle drives the `includeDeleted` urql variable. Render `Deleting...` badge when `deployment.status === "DELETING"`. Render greyed-out row with a relative-time timestamp (computed from `deletedAt`) and no inline action menu when `deployment.status === "DELETED"`.
- [ ] T030 [P] [US3] Vitest coverage: list shows `Deleting...` badge for `DELETING`, hides `DELETED` by default, reveals greyed `DELETED` row when toggle is on.

**Checkpoint**: US3 ready — list-level visibility matches the spec.

---

## Phase 6: User Story 4 — Inspect a deleted deployment forever (Priority: P2)

**Goal**: Direct id → tombstoned detail page renders forever, with `Deleted at <timestamp>` banner and disabled action buttons.

**Independent test**: Open `/deployments/<deleted-id>` directly. Verify banner, disabled action area with explanatory tooltips, intact timeline, and any associated backups still listed.

### Frontend detail page

- [ ] T031 [US4] Update `frontend/src/pages/deployments/DeploymentDetailPage.tsx`: when `deployment.deletedAt` is non-null, render a banner ("Deleted at \<timestamp\>") at the top of the page; disable every lifecycle action button (Delete, Upgrade, Redeploy, Stop, Start, Run Job, Restore, etc.) with a tooltip explaining the deployment is retired. The page MUST NOT short-circuit to a 404 — all sub-views (timeline, backups, status snapshots) must continue to render their available data.
- [ ] T032 [P] [US4] Vitest coverage for the tombstoned detail page: banner present when `deletedAt != null`; every action button disabled and carries a tooltip; backup list still rendered; timeline still rendered.

**Checkpoint**: US4 ready — forensic reachability of tombstoned deployments is provable.

---

## Phase 7: User Story 5 — Automate deletion safely from a script (Priority: P3)

**Goal**: SDK exposes `delete_deployment(id)` with idempotent semantics, returns immediately, surfaces clear errors for `RESTORING` and `DELETED` cases.

**Independent test**: From a Python script, drive the same flow as the E2E API test using only the SDK. Verify idempotent retry, "not found" on already-deleted, refusal during restore.

### SDK GraphQL operation

- [ ] T033 [P] [US5] Create `python_sdk/src/styrmin_sdk/graphql/delete_deployment.graphql` with the operation body in `contracts/sdk.md`. Single named operation `DeleteDeployment`.

### SDK exception type

- [ ] T034 [P] [US5] Add `DeploymentRestoringError` to the SDK exceptions module (sibling of `DeploymentNotFoundError`); register `extensions.code == "DEPLOYMENT_RESTORING"` in the structured-error decoder.

### SDK high-level method

- [ ] T035 [US5] Add `async def delete_deployment(self, deployment_id: UUID) -> Task` to the deployment-facing client surface in `python_sdk/src/styrmin_sdk/client/...`. Loads the operation via `load_query("delete_deployment")`, executes, decodes errors, returns a Pydantic-validated `Task`.

### Type regeneration

- [ ] T036 [US5] Run `uv run invoke generate`. Commit the regenerated `python_sdk/src/styrmin_sdk/graphql/_generated/...` and `frontend/src/graphql/_generated/...` diff. CI's "validate-graphql" check must pass.

### GraphQL validation gate

- [ ] T037 [US5] Run `uv run invoke validate-graphql` and confirm it passes against the new query.

**Checkpoint**: US5 ready — automation can drive deletion idempotently and observe the failure modes the spec promises.

---

## Phase 8: User Story 6 — Forensic retention of cluster-side state (Priority: P3)

**Goal**: Cluster-side CR lingers for `DELETED_CR_TTL_HOURS` (default 6) after `phase: Deleted`, then is garbage-collected by a kopf timer. Stuck-in-`Deleting` CRs are never auto-reaped.

**Independent test**: Configure `DELETED_CR_TTL_HOURS=0`, restart the operator, delete a deployment to terminal state, observe the next janitor sweep (≤ 30 min) reap the CR. Configure to a large value and confirm the CR persists.

### Configuration constant

- [ ] T038 [P] [US6] Add `DELETED_CR_TTL_HOURS: int = int(os.environ.get("DELETED_CR_TTL_HOURS", "6"))` to `backend/styrmin_backend/operator/config.py`.

### Janitor timer

- [ ] T039 [US6] Create `backend/styrmin_backend/operator/janitor.py` with a `@kopf.timer` (interval `1800.0` seconds). Selection rule per `contracts/crd.md` § *Janitor*: act only when `status.phase == "Deleted"` and the `Deleted` condition's `lastTransitionTime` is older than `DELETED_CR_TTL_HOURS` hours. Issue a `kr8s` delete on the CR; the existing `@kopf.on.delete` will short-circuit. Wire the module into the operator's import list (so kopf registers the handler at boot).
- [ ] T040 [P] [US6] Unit tests in `backend/tests/unit/operator/test_janitor.py`: TTL-not-expired → no-op; TTL-expired and `phase == Deleted` → delete issued; `phase == Deleting` (stuck) → no-op even if `lastTransitionTime` is old; missing `Deleted` condition → no-op.

**Checkpoint**: US6 ready — forensic window is real and configurable.

---

## Phase 9: E2E UI variant (mandatory — Constitution §V)

This phase is split out because it depends on **all** of US1, US2, US3, US4 being merged.

- [ ] T041 Create `backend/tests/e2e/test_delete_deployment_ui.py` with `@pytest.mark.ui_only(reason=...)` and `@pytest.mark.ci`. Drives via Playwright. Steps: deploy a sample app → open detail page → click `Delete` → assert dialog opens → assert button disabled with mismatched input, enabled with exact-match input → click destructive `Delete` → assert redirect to list → assert row shows `Deleting...` badge → wait for row to vanish from the default list → toggle `Show deleted` → assert row reappears greyed-out → click into the deleted-state detail page → assert banner present and every action button disabled.
- [ ] T042 Run `sleep infinity | uv run pytest backend/tests/e2e/test_delete_deployment_ui.py -v -s --pdb 2>&1 | tee /tmp/pdb.log`; iterate via the Playwright MCP server (per `AGENTS.md` § *UI-variant troubleshooting*) until green.

**Checkpoint**: full constitutional E2E coverage achieved.

---

## Phase 10: Schema export, codegen, and lint

These are gates rather than implementation — they must run successfully to commit.

- [ ] T043 Run `uv run styrmin export graphql-schema schema.graphql`. Commit the regenerated `schema.graphql`.
- [ ] T044 Re-run `uv run invoke generate` to make sure SDK + frontend codegen reflects the final schema. Commit the diff.
- [ ] T045 Run `uv run invoke format lint` until clean. Run `cd frontend && pnpm lint` until clean.
- [ ] T046 Run all GraphQL propagation unit tests (`backend/tests/unit/api/schema/test_propagation_delete_deployment.py` and any sibling files added in T028) and confirm they all pass.

---

## Phase 11: Polish & cross-cutting

- [ ] T047 [P] Update `dev/guides/...` with a short pointer to `specs/008-deployment-deletion/quickstart.md` if the project's developer-guide index lists feature walkthroughs (otherwise no action — `quickstart.md` lives with the spec).
- [ ] T048 [P] If `dev/adr/` indexes architectural decisions, draft an ADR titled "State-driven deployment deletion" capturing the *no Prefect flow / observe via reconciler* trade-off (this also feeds Phase 6 of `/speckit-auto-run`).
- [ ] T049 Walk the `quickstart.md` end-to-end manually on a fresh dev cluster as a final sanity check; record any gaps in the spec or plan.
- [ ] T050 Verify success-criteria SC-001…SC-012 from `spec.md` are observable in the implemented system (most are covered by E2E + propagation tests; SC-011 is covered by the manual env-var override walkthrough in `quickstart.md`).

---

## Dependencies & execution order

### Phase dependencies

- **Phase 1 (Setup)** → **Phase 2 (Foundational)** → **Phase 3+ (User Stories)** → **Phase 9 (E2E UI)** → **Phase 10 (gates)** → **Phase 11 (polish)**.
- US1 (Phase 3) is the MVP — every other story depends on the lifecycle states + service + status reporter landing first.
- US2, US3, US4 depend only on US1.
- US5 depends on US1 (mutation must exist before SDK method is meaningful).
- US6 depends on US1 + the operator handler advancing CRs to `phase: Deleted`.
- E2E UI (Phase 9) depends on US1 + US2 + US3 + US4.

### Within each user story

- Schema/contract additions (T011–T012, T018, T026–T027, T033) before propagation tests (T020, T028).
- Service-layer code before resolver code (already reflected in numbering).
- Tests after the path they test exists; E2Es last.

### Parallel opportunities

- Phase 2 (Foundational): T002–T010 are mostly serial (CRD → Pydantic → DB → migration); T011–T012 can run in parallel with each other once T007 lands.
- Within US1: T013–T019 can be staged in parallel by file (`services/deployment.py`, `services/deployment_status.py`, `operator/handlers/styrmin_deployment.py`, `api/schema/mutation.py`, `services/deployment_timeline.py`) once T007/T008 are merged.
- Across stories: US2 (Phase 4), US3 (Phase 5), US4 (Phase 6), US5 (Phase 7), and US6 (Phase 8) can be worked in parallel by different developers once US1 is merged.

---

## Independent test summary

| Story | Independent verification |
|-------|--------------------------|
| US1 | `test_delete_deployment_api.py` passes (api_only, ci). |
| US2 | Vitest dialog tests pass (T025); destructive button gating provable in isolation. |
| US3 | `deployments(includeDeleted)` propagation test (T028) + Vitest list tests (T030) cover behaviour. |
| US4 | Vitest tombstone-detail tests (T032) cover banner + disabled buttons. |
| US5 | Re-run the E2E API flow using only the SDK (covered by T021 since the E2E uses the SDK as its driver). |
| US6 | Operator unit tests (T040) cover the selection rule; manual `DELETED_CR_TTL_HOURS=0` walkthrough covers the timing. |

---

## Suggested MVP scope

Phase 1 + Phase 2 + Phase 3 (US1). Ships the destructive-path-end-to-end through the API and the audit trail; everything else is additive. The constitutional E2E gate (`test_delete_deployment_api.py`) is satisfied at the MVP.
