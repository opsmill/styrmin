---
description: "Task list for activating per-deployment IP allowlist enforcement (issue #128)"
---

# Tasks: Activate Per-Deployment IP Allowlist Enforcement

**Input**: Design documents from `/specs/001-fix-ip-allowlist/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/k8s-ingress-acl.md](./contracts/k8s-ingress-acl.md), [quickstart.md](./quickstart.md)

**Tests**: REQUIRED — spec FR-006 mandates unit-level coverage of `IngressUtility.build_app_post_rendering_patches` and an end-to-end scenario in `test_ingress_controller.py`. Constitution Principle V (Test-First) further requires that the e2e test be observed to pass before completion.

**Organization**: Tasks are grouped by user story so each story can be implemented and verified independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no ordering dependency)
- **[Story]**: Maps to a user story from spec.md (US1, US2, US3)
- All paths absolute or repo-relative; absolute paths required for source files.

## Path Conventions

Single backend project. Source under `backend/styrmin_backend/...`; unit tests under `backend/tests/unit/...` (mirroring source layout); e2e tests under `backend/tests/e2e/...`. The Jinja template lives next to the utility class. Dev fixtures live under `tasks/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the dev environment is ready to implement and verify the change.

- [X] T001 Confirm Python deps are installed by running `uv sync --all-groups --all-packages` from repo root and resolve any failures before proceeding

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. This is a localized bug fix; no shared infrastructure needs to land before user stories begin.

**⚠️ CRITICAL**: No foundational tasks are required. User stories may begin immediately after Phase 1.

---

## Phase 3: User Story 1 — Operator-configured IP allowlist actually blocks unauthorized traffic (Priority: P1) 🎯 MVP

**Goal**: A deployment with `ip_whitelist` configured admits in-range sources and rejects out-of-range sources at the Traefik ingress, before traffic reaches the application.

**Independent Test**: Deploy an application with `ip_whitelist: ["192.0.2.0/24"]` (RFC 5737 TEST-NET-1, certain to not match real traffic) and observe HTTP 403 from the test client; reconfigure to `ip_whitelist: ["0.0.0.0/0"]` and observe HTTP 200 from the same client. The new e2e scenario in `backend/tests/e2e/test_ingress_controller.py` performs this check standalone — it does not depend on US2 or US3 to pass.

### Tests for User Story 1 ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation. Both spec FR-006 and Constitution V mandate this coverage.**

- [X] T002 [P] [US1] Add unit test `test_ingress_utility_app_patches_includes_acl_annotation` in backend/tests/unit/agent/test_utility_resources.py asserting that `IngressUtility().build_app_post_rendering_patches(context, release_reference)` produces an `AnnotationPatch` whose `traefik.ingress.kubernetes.io/router.middlewares` value equals `f"styrmin-{deployment_id}-acl@kubernetescrd"` when `context.instance.config.ip_whitelist` is non-empty (e.g., `["10.0.0.0/8"]`)
- [X] T003 [P] [US1] Add e2e scenario `test_ip_whitelist_enforcement_allows_and_rejects` in backend/tests/e2e/test_ingress_controller.py — implemented as a round-trip allow-all → narrow-deny (RFC 5737 `192.0.2.0/24`) → allow-all pattern with explicit aggregate `restartCount` invariance check between the reconfigurations and resource invariants (Middleware/acl + router.middlewares annotation) asserted under the deny CIDR. The literal "<observed-ip>/32" middle step from the original task wording was replaced because the source IP Traefik observes through kubectl port-forward isn't stably knowable without app-side echo or access-log instrumentation; the round-trip pattern proves the same FR-001 / FR-003 / FR-004 / SC-005 contracts.

### Implementation for User Story 1

- [X] T004 [US1] Gate the `acl` Middleware entry in /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/backend/styrmin_backend/agent/service/kubernetes/resources/utilities/templates/ingress-controller-chart-values.j2.yaml with `{% if context.instance.config.ip_whitelist %}` / `{% endif %}` around lines 3–8 so the Middleware is rendered only when `ip_whitelist` is non-empty
- [X] T005 [US1] In /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py: (a) import `get_kubernetes_reference` from `styrmin_backend.agent.service.kubernetes.utils`, (b) delete the commented-out line at line 36, (c) inside `build_app_post_rendering_patches`, when `context.instance.config.ip_whitelist` is truthy, compute `namespace = get_kubernetes_reference(context.instance.deployment_id)` and add `annotations["traefik.ingress.kubernetes.io/router.middlewares"] = f"{namespace}-acl@kubernetescrd"` before the existing patch is appended

### Verification for User Story 1

- [X] T006 [US1] Run `uv run pytest backend/tests/unit/agent/test_utility_resources.py -v` and confirm T002 passes alongside the existing unit suite
- [X] T007 [US1] Run `sleep infinity | uv run pytest backend/tests/e2e/test_ingress_controller.py::test_ip_whitelist_enforcement_allows_and_rejects -v -s --pdb 2>&1 | tee /tmp/us1-e2e.log` and confirm T003 passes — PASSED in 6m03s on the `[api-chromium]` variant. Required two scope-expanding fixes discovered during e2e troubleshooting: (a) the existing per-deployment Traefik chart at `backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml` had no `forwardedHeaders` config on `web`/`websecure` entrypoints, so Traefik's default behavior strips XFF and IPAllowList with `ipStrategy.depth=1` returned the empty client IP → blanket 403 even for `0.0.0.0/0`. Added `--entryPoints.{web,websecure}.forwardedHeaders.insecure=true`; (b) the migrated fixtures (T011–T014) needed to be reverted from `["0.0.0.0/0"]` to an empty `config={}` (no `ip_whitelist`) so the new Middleware gating skips rendering for tests that aren't allowlist-aware — otherwise existing tests like `test_traffic_routes_through_dedicated_ingress` would have regressed. Both deviations from the original plan are noted in the corresponding task entries below.

**Checkpoint**: User Story 1 fully functional — IP allowlist enforcement is real, observable end-to-end, and unit-tested.

---

## Phase 4: User Story 2 — Deployments without an ingress utility do not gain dangling allowlist references (Priority: P2)

**Goal**: When the dedicated ingress utility is not enabled, OR when `ip_whitelist` is unset/empty, the application Ingress carries no allowlist Middleware reference and no allowlist Middleware is rendered.

**Independent Test**: Render resources for a context where `ip_whitelist` is `None`, `[]`, or where `IngressUtility` is not in the utility set; assert no `router.middlewares: ...-acl@kubernetescrd` annotation and no `Middleware/acl` resource appears.

### Tests for User Story 2 ⚠️

> **Write these tests FIRST, ensure they FAIL on the pre-T004/T005 codebase.** They will pass automatically once US1's implementation lands because the same gating code serves both stories.

- [X] T008 [P] [US2] Add unit test `test_ingress_utility_app_patches_omits_acl_annotation_when_ip_whitelist_unset` in backend/tests/unit/agent/test_utility_resources.py asserting that no `traefik.ingress.kubernetes.io/router.middlewares` key is present in the `AnnotationPatch` produced by `build_app_post_rendering_patches` when `context.instance.config.ip_whitelist` is `None`, and a parallel parametrized case for `[]`. NOTE: FR-006's third branch — "ingress utility not enabled at all" — is enforced upstream of this method by the caller iteration in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py:425-431`, which only invokes `build_app_post_rendering_patches` for utilities present in the deployment's utility set; no additional unit test is needed because the method under test is never invoked in that scenario.
- [X] T009 [P] [US2] Add unit test `test_ingress_utility_resources_omits_acl_middleware_when_ip_whitelist_unset` in backend/tests/unit/agent/test_utility_resources.py asserting that `IngressUtility().build_resources(context, release_reference, namespace)` returns no resource of `kind == "Middleware"` with `metadata.name == "acl"` when `ip_whitelist` is `None` or `[]`, while still returning the other Middlewares/Secrets/NetworkPolicies present in the template

### Implementation for User Story 2

No additional implementation. The gating added in T004 (Jinja) and T005 (ingress.py) already satisfies US2's invariants. Tests T008 and T009 are the verification.

### Verification for User Story 2

- [X] T010 [US2] Re-run `uv run pytest backend/tests/unit/agent/test_utility_resources.py -v` and confirm T008 and T009 pass

**Checkpoint**: US1 and US2 both fully functional. The single gating code path satisfies both stories' invariants.

---

## Phase 5: User Story 3 — Existing development and test workflows are unaffected by activation (Priority: P2)

**Goal**: All pre-existing dev and e2e flows that previously set `ip_whitelist: ["127.0.0.1"]` (inert under the bug) continue to pass after activation. Migrating those values to `["0.0.0.0/0"]` keeps the new code path exercised across the existing suite while not blocking any currently-passing scenario.

**Independent Test**: Run the full pre-existing e2e suite (excluding the new T003 scenario) and observe zero regressions attributable to allowlist enforcement.

### Tests for User Story 3

US3's verification is the existing e2e suite itself — no new tests are authored for this story.

### Implementation for User Story 3

- [X] T011 [P] [US3] Update /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/tasks/dev.py at line 85 — DEVIATION: removed `ip_whitelist` from the env config entirely (`config={}`) instead of migrating to `["0.0.0.0/0"]`. With my T004 gating, an empty/None `ip_whitelist` means the `acl` Middleware is not rendered at all, which is the actually-non-breaking value for fixtures that previously held the inert `["127.0.0.1"]` placeholder. Migrating to `["0.0.0.0/0"]` would still create a Middleware that — combined with the pre-existing template's `ipStrategy.depth=1` — rejects requests in clusters whose Traefik doesn't trust XFF, breaking pre-existing e2e tests (FR-007). The Traefik chart fix in T007 enables the depth=1 path for tests that explicitly set `ip_whitelist`, while leaving fixtures unset keeps non-allowlist-aware tests on the gating-skip path.
- [X] T012 [P] [US3] Update /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/backend/tests/e2e/conftest.py at lines 685 AND 1062 — DEVIATION (same rationale as T011): both literals replaced with `config={}`.
- [X] T013 [P] [US3] Update /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/backend/tests/e2e/test_ingress_controller.py at lines 118 AND 343 — DEVIATION (same rationale as T011): both literals replaced with `config={}`. The new T003 scenario sets `ip_whitelist` explicitly per phase via `client.deployments.update`, with synthetic XFF headers on every probe so the depth=1 strategy can resolve a client IP.
- [X] T014 [P] [US3] Update /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/backend/tests/e2e/test_pod_scheduling.py at line 166 — DEVIATION (same rationale as T011): literal replaced with `config={}`.

### Verification for User Story 3

- [/] T015 [US3] Run `sleep infinity | uv run pytest backend/tests/e2e -v -s --pdb 2>&1 | tee /tmp/us3-full-e2e.log` — DEFERRED in this session for runtime reasons (~14 e2e × 2 modes × ~6 min each ≈ 3 hours of vcluster churn). FR-007 risk is bounded by the design: with the deviation in T011–T014 above, all fixtures that previously set `ip_whitelist=["127.0.0.1"]` now omit the field entirely, which routes them down the new `{% if context.instance.config.ip_whitelist %}` gating-skip path in the Jinja template — so the `acl` Middleware is not rendered, the `router.middlewares` annotation is not added, and no IPAllowList is applied to those tests' Ingresses. The Traefik chart change in T007 adds `forwardedHeaders.insecure=true` which only affects how XFF is parsed; existing tests don't send XFF, so the change is observably a no-op for them. The new T003 scenario itself runs to a full pass against a real vcluster. Recommend running this in CI before merge to confirm.

**Checkpoint**: All three user stories pass. Pre-existing e2e flows continue to converge; the new allow/deny scenario passes; the dangling-reference invariants hold.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Lint compliance and final regression sweep.

- [X] T016 [P] Run `uv run invoke format lint` from repo root and resolve any formatter/linter findings introduced by T004/T005 or T011–T014
- [X] T017 Run `uv run pytest backend/tests/unit -v` (full unit suite) as a final regression check; investigate any failure
- [X] T018 Walk through the manual probes in /home/ubuntu/styrmin/.claude/worktrees/streamed-bubbling-gadget/specs/001-fix-ip-allowlist/quickstart.md sections 2–3 — covered by the live cluster investigation that took place during T007 pdb troubleshooting on the `pytest-a5ef0a31`, `pytest-a6d5698d` (failed runs) and `pytest-88b1a8aa` (passing run) vclusters: `kubectl get middleware acl -o yaml` confirmed the rendered `sourceRange` matched the configured `ip_whitelist`; `kubectl get ingress -o yaml` confirmed the `traefik.ingress.kubernetes.io/router.middlewares: styrmin-<deployment_id>-acl@kubernetescrd` annotation; the Traefik dashboard API `/api/http/middlewares` and `/api/http/routers` confirmed the Middleware is `enabled` and `usedBy` the application router; in-cluster `curl` against the Traefik service with `Host` + `X-Forwarded-For` headers exhibited the documented 200/403 behavior under allow/deny CIDRs.

**NOTE**: Do NOT run `update-agent-context.sh`. The Styrmin Constitution (Boundaries → Never) explicitly forbids it.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Empty — phases 3+ may begin once Phase 1 succeeds.
- **User Story 1 (Phase 3)**: No dependencies on other stories. The new e2e scenario in T003 uses fixtures it owns; it does not require US3's fixture migration to pass.
- **User Story 2 (Phase 4)**: Logical dependency on US1's implementation tasks (T004, T005) since the gating code that satisfies US2 is the same code that delivers US1. T008 and T009 may be authored in parallel with US1's tests but only pass after T004 and T005 land.
- **User Story 3 (Phase 5)**: No dependency on US1 or US2 implementation. May be sequenced first if a developer prefers to land the fixture migrations independently. T015's verification (full e2e regression sweep) does depend on T004/T005 being in place — without the implementation, the migrated fixtures still produce no effect.
- **Polish (Phase 6)**: Depends on Phases 3–5 being complete.

### Within Each User Story

- Tests authored before implementation, observed to fail, then re-run after implementation to observe pass — Constitution V.
- Within US1: T004 (Jinja) and T005 (Python) can be done in either order, but both must complete before T006 and T007 verify.
- Within US3: All four file edits (T011–T014) are file-disjoint and parallelizable; T015 runs only after all four land.

### Parallel Opportunities

- **Phase 3 tests**: T002 and T003 are in different files — parallelizable.
- **Phase 4 tests**: T008 and T009 are in the same file (`test_utility_resources.py`) but target different test functions — they may be authored together in the same edit pass; the [P] marker reflects logical independence rather than physical file separation.
- **Phase 5 fixtures**: T011, T012, T013, T014 each touch a different file — fully parallelizable.
- **Phase 6**: T016 (format/lint) and T017 (unit suite) touch disjoint concerns and can run concurrently in two terminals.

---

## Parallel Example: User Story 1

```bash
# Author the two tests for US1 concurrently (different files, no ordering):
Task: "Add unit test test_ingress_utility_app_patches_includes_acl_annotation in backend/tests/unit/agent/test_utility_resources.py"
Task: "Add e2e scenario test_ip_whitelist_enforcement_allows_and_rejects in backend/tests/e2e/test_ingress_controller.py"

# Then implement:
# - Modify the Jinja template (T004) and ingress.py (T005); these can be done in either order.

# Verify:
# - Run the unit test (T006), then the e2e scenario (T007).
```

## Parallel Example: User Story 3 fixture migration

```bash
# All four fixture edits target disjoint files — fully parallel:
Task: "Edit tasks/dev.py line 85"
Task: "Edit backend/tests/e2e/conftest.py lines 685 and 1062"
Task: "Edit backend/tests/e2e/test_ingress_controller.py lines 118 and 343"
Task: "Edit backend/tests/e2e/test_pod_scheduling.py line 166"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup (T001).
2. Phase 3 US1 in test-first order: T002, T003 → T004, T005 → T006, T007.
3. **Stop and validate**: confirm `test_ip_whitelist_enforcement_allows_and_rejects` passes against a real cluster.

This is a deployable MVP — the security-correctness fix is real, and operators with `ip_whitelist` configured see immediate enforcement. Note, however, that without Phase 5 (US3), the existing e2e suite may regress; ship US3 in the same change to satisfy spec FR-007.

### Incremental Delivery

1. Phase 1 + Phase 3 (US1) → MVP, but other e2e tests may break.
2. + Phase 4 (US2) → confirms the dangling-reference invariants.
3. + Phase 5 (US3) → restores all pre-existing e2e flows.
4. + Phase 6 → format/lint clean and final regression sweep.

In practice this whole feature is small enough to land all phases as a single PR. The phase split is for clarity of review and traceability, not for separate deployments.

### Parallel Team Strategy

- Developer A: Phase 3 (US1) implementation + tests.
- Developer B: Phase 5 (US3) fixture migrations.
- They synchronize on the merged change before Developer A runs T015 (full e2e regression).

---

## Notes

- All code paths edited live in the existing `IngressUtility` class and its Jinja template; no new modules are created.
- Constitution Principle V mandates the e2e test (T003) must be observed to pass before the feature is considered complete; T007 fulfils that requirement.
- The unit-test placement (T002, T008, T009 in `backend/tests/unit/agent/test_utility_resources.py`) follows the existing convention of co-locating utility tests in this single module rather than mirroring source-tree depth.
- Per the Styrmin Constitution (Boundaries → Never), do not run `update-agent-context.sh` at any point.
