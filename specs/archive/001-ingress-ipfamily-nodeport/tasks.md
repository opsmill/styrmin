# Tasks: IP Family & Fixed NodePort Knobs for Dedicated Ingress Service

**Input**: Design documents from `/specs/001-ingress-ipfamily-nodeport/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Required by spec FR-013 / SC-006 and Constitution §V. Test-first ordering applies: each unit/snapshot/E2E test MUST be written and observed to fail before its implementation task lands.

**Organization**: Tasks are grouped by user story. US1 (P1, IPv6/dual-stack pinning), US2 (P1, fixed NodePort), and US3 (P2, backward-compat verification). US1 and US2 both modify `backend/styrmin_backend/context/models/config.py` and `backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml` — they can be developed by different people on different branches but tasks targeting those two files are NOT marked `[P]` across stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps a task to its user story (US1, US2, US3) for traceability
- All paths below are repository-relative

## Path Conventions

Backend-only feature on a web-app layout. Tasks reference these paths:

- Production code: `backend/styrmin_backend/context/models/config.py`, `backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml`
- Unit tests: `backend/tests/unit/services/test_ingress_controller.py`
- E2E tests: `backend/tests/e2e/test_ingress_controller.py`
- Operator docs: `dev/guides/ingress-ipv6-dual-stack-validation.md` (new)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Capture baseline so US3's backward-compat assertion has a known reference.

- [X] T001 Run `uv run pytest backend/tests/unit/services/test_ingress_controller.py backend/tests/e2e/test_ingress_controller.py -v` and confirm a green baseline before any code changes. Record the pre-change pass count to compare against after US1+US2 land.

  Baseline (2026-04-28): 33 unit tests passing. E2E suite collects 12 scenarios (6 base × 2 driver modes); full E2E run deferred to T016/T020 to avoid duplicate vcluster bring-up.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-story prerequisites.

**No foundational tasks for this feature.** US1, US2, and US3 each add independent fields/validators/template branches; there is no shared infrastructure that must land before any story can begin. The only cross-story coupling is the two shared files (`config.py`, `chart_values.j2.yaml`) — handled by serializing tasks that touch those files within each story.

---

## Phase 3: User Story 1 — Pin a dedicated ingress Service to IPv6 on a dual-stack cluster (Priority: P1) 🎯 MVP

**Goal**: Operators can pin the dedicated ingress Service to a specific IP family and policy by setting `ip_families` and/or `ip_family_policy` on `dedicated_ingress.service`. Validation rejects empty / duplicate / unknown family lists and unknown policy values at config load. Chart values render the new keys conditionally under `service:`.

**Independent Test**: With `ip_families: ["IPv6"]` + `ip_family_policy: "SingleStack"` set in an environment config, render the dedicated-ingress chart values and assert the YAML contains `service.ipFamilies: [IPv6]` and `service.ipFamilyPolicy: SingleStack`; with either field absent, the corresponding key is omitted. Empty/duplicate/unknown family lists raise `ValidationError` at config load. End-to-end pass-through (Styrmin renders the requested family fields into the actual Service object) is verified by T012/T016 against the existing single-family vcluster using `ip_families: ["IPv4"]` — proving the rendering layer reaches the cluster. Cluster-side IPv6 *traffic* verification (AAAA records, v6 client requests reach the Service on a dual-stack cluster) follows the manual-validation runbook delivered in T007.

### Tests for User Story 1 (write FIRST, observe FAIL before implementation) ⚠️

- [X] T002 [US1] Add failing unit tests for the `ip_families` field validator in the `TestIngressServiceConfigModel` class of `backend/tests/unit/services/test_ingress_controller.py`. Cover: accepts `["IPv6"]` and `["IPv4", "IPv6"]`; rejects `[]` (empty), `["IPv6", "IPv6"]` (duplicates), and `["foo"]` (unknown — Pydantic Literal mismatch). Confirm each test fails with `AttributeError` / `TypeError` because the field does not yet exist.
- [X] T003 [US1] Add failing unit tests for the `ip_family_policy` field in the same test class: accepts each of `"SingleStack"`, `"PreferDualStack"`, `"RequireDualStack"`; rejects `"DualStack"` and any other string (Literal mismatch). Confirm failure pre-implementation.
- [X] T004 [US1] Add failing unit tests that render `chart_values.j2.yaml` against `IngressServiceConfig` instances and parametrize across at least: (i) `ip_families: ["IPv6"]` + `ip_family_policy: "SingleStack"` → YAML contains `service.ipFamilies == ["IPv6"]` and `service.ipFamilyPolicy == "SingleStack"`; (ii) `ip_families: ["IPv4", "IPv6"]` + `ip_family_policy: "RequireDualStack"` → YAML contains `service.ipFamilies == ["IPv4", "IPv6"]` and `service.ipFamilyPolicy == "RequireDualStack"` (covers spec US1 Acceptance Scenario 2); (iii) both fields unset → neither key appears. Confirm failure pre-implementation.

### Implementation for User Story 1

- [X] T005 [US1] Implement the `ip_families: list[Literal["IPv4", "IPv6"]] | None = None` and `ip_family_policy: Literal["SingleStack", "PreferDualStack", "RequireDualStack"] | None = None` fields on `IngressServiceConfig` in `backend/styrmin_backend/context/models/config.py:8-23`. Add the `_validate_ip_families` field validator (`@field_validator("ip_families", mode="after")`) implementing the non-empty + no-duplicates rule per [data-model.md](./data-model.md). T002–T004 must transition to passing once T005 and T006 are both complete.
- [X] T006 [US1] Render `service.ipFamilies` and `service.ipFamilyPolicy` conditionally in `backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml` inside the existing top-level `service:` block, mirroring the `{% if … %}` pattern already used for `load_balancer_ip` and `external_traffic_policy`. Each key appears only when its corresponding config attribute is non-`None`.
- [X] T007 [P] [US1] Write the manual-validation runbook at `dev/guides/ingress-ipv6-dual-stack-validation.md` per [research.md §R6](./research.md). Sections: (1) cluster pre-flight (`kubectl get nodes -o wide`, `/api/v1/nodes` IPv6 check); (2) known-good environment config snippet; (3) verification steps (`kubectl get service -o yaml` → `spec.ipFamilies` / `spec.ipFamilyPolicy`; `dig AAAA <fqdn>`; v6-capable client request).
- [X] T008 [US1] Update the `IngressServiceConfig` class docstring in `backend/styrmin_backend/context/models/config.py:8-23` with the FR-012 dual-stack guidance: pin to `["IPv6"]` + `SingleStack` for v6-only origins; use `RequireDualStack` only when the cluster has both families configured; `PreferDualStack` for fall-back semantics.

**Checkpoint**: US1 fully testable. `T002`, `T003`, and `T004` pass. The runbook in `dev/guides/` walks an operator through dual-stack verification on a real cluster.

---

## Phase 4: User Story 2 — Pin a fixed NodePort for a Cloudflare origin (Priority: P1)

**Goal**: Operators can set `node_port` on `dedicated_ingress.service` (with `type: "NodePort"`) and have Traefik's `websecure` (HTTPS) entrypoint bind that port. (`web` keeps Kubernetes's auto-allocated NodePort — Kubernetes rejects a Service whose two ports share a `nodePort`, and the Cloudflare/Infrahub recipe terminates TLS at the cluster.) Validation rejects out-of-range values and the `node_port` + non-`NodePort` combination at config load. Chart values render `ports.websecure.nodePort` conditionally; the previously commented-out `ports:` scaffold at lines 49–55 is removed.

**Independent Test**: With `type: "NodePort"` + `node_port: 30443` set, render the chart values and assert `ports.websecure.nodePort == 30443` while `web` is NOT pinned to the same value. With `node_port` unset, the `ports:` block does not appear. Out-of-range values (`0`, `65536`, `-1`) and the `type: "LoadBalancer"` + `node_port: 30443` combination raise `ValidationError` at config load. End-to-end: T012/T016 deploys with the NodePort config (combined with US1's IP family fields) on the existing single-family vcluster and observes the Service reporting `websecure` on `30443` and persisting across a reconcile.

### Tests for User Story 2 (write FIRST, observe FAIL before implementation) ⚠️

- [X] T009 [US2] Add failing unit tests for the `node_port` field range in the `TestIngressServiceConfigModel` class of `backend/tests/unit/services/test_ingress_controller.py`: accepts `1`, `30443`, `65535`; rejects `0`, `65536`, `-1` (Pydantic `ge`/`le` constraint). Confirm failure pre-implementation.
- [X] T010 [US2] Add a failing unit test for the `_validate_node_port_requires_nodeport_type` model validator in the same test class: `type="NodePort"` + `node_port=30443` is accepted; `type="NodePort"` + `node_port=None` is accepted (preserves "let Kubernetes pick"); `type="LoadBalancer"` + `node_port=30443` raises `ValidationError` whose message names both `type` and `node_port`. Confirm failure pre-implementation.
- [X] T011 [US2] Add a failing unit test that renders `chart_values.j2.yaml` against an `IngressServiceConfig` with `type="NodePort"` + `node_port=30443` and asserts the parsed YAML contains `ports.websecure.nodePort == 30443` (and that `web` does NOT carry the same fixed NodePort — Kubernetes rejects two ports on one Service sharing a `nodePort`, so the rendering pins `websecure` only). Add a paired test asserting that with `node_port` unset, the `ports:` block is absent entirely. Confirm failure pre-implementation.
- [X] T012 [US1] [US2] Extend `backend/tests/e2e/test_ingress_controller.py` with a new test function `test_dedicated_ingress_service_overrides` that creates an environment with `dedicated_ingress.service.type = "NodePort"`, `dedicated_ingress.service.node_port = <port>`, `dedicated_ingress.service.ip_families = ["IPv4"]`, and `dedicated_ingress.service.ip_family_policy = "SingleStack"`, deploys via the existing `scenario_driver` / `vcluster` / `styrmin_resources` fixtures, and asserts on the resulting Traefik Service object: (a) `spec.type == "NodePort"`; (b) the `websecure` port reports the chosen `nodePort`, and the `web` port reports a NodePort that is NOT the chosen value (Kubernetes rejects two ports on a single Service sharing a `nodePort`); (c) `spec.ipFamilies == ["IPv4"]`; (d) `spec.ipFamilyPolicy == "SingleStack"`. Using `["IPv4"]` (cluster default but explicit) keeps the test on the existing single-family vcluster while proving end-to-end pass-through of US1's family fields — dual-stack *traffic* validation stays in the manual runbook (T007). The platform enforces a one-cluster limit, so the test reuses the cluster created by `styrmin_resources` and overrides ingress at the **environment** level (env-level `dedicated_ingress` replaces cluster-level — verified by `TestConfigMergePrecedence`). Reuse the existing `kr8s.asyncio.objects.Service` import (no new fixture, no new module). The original assertion (post-delete reconcile re-applies the same NodePort) was dropped after `/speckit.implement` discovered Flux helm-controller's default reconcile mode does not detect drift against the live cluster — that's a platform-level concern outside this feature's scope, recorded in `spec.md` § Clarifications. Confirm failure pre-implementation.

### Implementation for User Story 2

- [X] T013 [US2] Implement the `node_port: int | None = Field(default=None, ge=1, le=65535)` field on `IngressServiceConfig` in `backend/styrmin_backend/context/models/config.py:8-23`. Add the `_validate_node_port_requires_nodeport_type` model validator (`@model_validator(mode="after")`) per [data-model.md](./data-model.md). T009 and T010 transition to passing once T013 lands.
- [X] T014 [US2] Render `ports.websecure.nodePort` conditionally in `backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml` as a new top-level `ports:` block emitted only when `node_port` is set. **Only `websecure` is pinned** — Kubernetes rejects a Service whose two ports share a `nodePort`, so `web` keeps the chart's default (Kubernetes-allocated) NodePort. **Remove the commented-out `ports:` scaffold currently at lines 49–55** — it is replaced by the real rendering. T011 transitions to passing once T014 lands.
- [X] T015 [US2] Update the `IngressServiceConfig` class docstring in `backend/styrmin_backend/context/models/config.py:8-23` to note: `node_port` is only meaningful when `type == "NodePort"`; it pins the Traefik **`websecure` (HTTPS) entrypoint only** because Kubernetes rejects a Service whose two ports share a `nodePort`, and the Cloudflare/Infrahub recipe terminates TLS at the cluster; `web` keeps the chart default; per-entrypoint divergence (`web_node_port`) is a future extension.
- [X] T016 [US1] [US2] Run T012's E2E scenario via `sleep infinity | uv run pytest backend/tests/e2e/test_ingress_controller.py::test_dedicated_ingress_service_overrides -v -s --pdb 2>&1 | tee /tmp/pdb.log` per AGENTS.md and confirm pass. All four assertions (a)–(d) from T012 must succeed.

  Result (2026-04-28): `1 passed in 186.57s` for `test_dedicated_ingress_service_overrides[api-chromium]`. All four assertions (a) `spec.type == "NodePort"`; (b) `websecure` NodePort = chosen, `web` NodePort != chosen; (c) `spec.ipFamilies == ["IPv4"]`; (d) `spec.ipFamilyPolicy == "SingleStack"` succeeded against the live cluster.

**Checkpoint**: US2 fully testable. Unit tests `T009`–`T011` pass; E2E `T012` passes against the existing single-family vcluster.

---

## Phase 5: User Story 3 — Pre-existing deployments redeploy unchanged (Priority: P2)

**Goal**: Configurations that do not set any of the three new fields produce byte-identical chart values to the pre-feature output. Existing snapshot tests continue to pass without modification.

**Independent Test**: Construct an `IngressServiceConfig` with no new fields set; render the chart values; assert the result equals the pre-feature snapshot. Run the existing snapshot tests (especially the ones at `backend/tests/unit/services/test_ingress_controller.py:178-192`) and confirm zero modifications were required to keep them passing.

### Tests for User Story 3

- [X] T017 [US3] Add an explicit "all-three-new-fields-unset" snapshot/equivalence test in the `TestIngressServiceConfigModel` class of `backend/tests/unit/services/test_ingress_controller.py`. Construct an `IngressServiceConfig` with `ip_families=None, ip_family_policy=None, node_port=None` (and the existing fields at their pre-feature defaults), render the chart-values template, and assert: (a) the parsed YAML's `service:` block contains no `ipFamilies` / `ipFamilyPolicy` keys; (b) no top-level `ports:` block is present; (c) the rendered output equals the rendering of the same config built **without ever touching the new fields** (proves the byte-identical guarantee). This test must pass on first run after T005, T006, T013, T014 are complete.

### Verification for User Story 3

- [X] T018 [US3] Run the full unit test suite for the ingress controller via `uv run pytest backend/tests/unit/services/test_ingress_controller.py -v` and confirm every pre-existing test passes **without modification** since T001's baseline. Specifically verify that the existing assertions in `TestIngressServiceConfigModel` and the snapshot tests at `backend/tests/unit/services/test_ingress_controller.py:178-192` (per pre-feature line numbers) are present and unchanged; the only additions to the file should be the new test methods introduced by T002, T003, T004, T009, T010, T011, and T017.

**Checkpoint**: US3 verified. Backward-compat guarantee is asserted explicitly by T017 and confirmed at the suite level by T018.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T019 Run `uv run invoke format lint` against the full repo and address any findings introduced by US1/US2/US3 changes. Constitution §VI requires this gate to pass before commit.
- [X] T020 [P] Re-run `uv run pytest backend/tests/unit/services/test_ingress_controller.py backend/tests/e2e/test_ingress_controller.py -v` end-to-end after all stories land; confirm the unit count grew (US1 + US2 + US3 added tests) and the E2E count grew by exactly one (T012). Confirm no pre-existing test required modification.

  Result (2026-04-28): unit suite went from 33 → 61 passing (28 new tests added across US1/US2/US3); E2E suite went from 12 → 14 collected scenarios (one new test × two driver modes; only the `[api-chromium]` variant was run end-to-end because the platform's one-cluster limit makes `[ui-chromium]` redundant for this rendering pass-through test). No pre-existing test required modification — the only file-level changes to `test_ingress_controller.py` were the new test methods + the `_render_chart_values` helper.
- [X] T021 [P] Cross-check `quickstart.md` examples against the implemented validators: paste the snippets from the "Validation errors (config load)" table into a Python REPL with the new `IngressServiceConfig` and confirm each error message matches what the doc claims. Update either the doc or the code so they agree exactly.
- [X] T022 Final sweep: confirm `schema.graphql` and the SDK generated types are unchanged (`git status` should show no diff in `python_sdk/src/styrmin_sdk/graphql/_generated/` or `schema.graphql`). If anything changed unexpectedly, stop and investigate — the spec and research both assert no GraphQL/SDK regen is required.
- [X] T023 Open a follow-up tracking issue (or spec) for **automated dual-stack IPv6 *traffic* E2E coverage**. Reference this spec (`specs/001-ingress-ipfamily-nodeport/`) and the §V narrowed deviation in `plan.md` Complexity Tracking. The follow-up should: introduce dual-stack vcluster fixtures (or equivalent), add an E2E that deploys with `ip_families: ["IPv6"]` + `ip_family_policy: "SingleStack"` and asserts cluster-side traffic actually flows on v6 (AAAA resolution + v6-capable client request), and replace the manual runbook step with the automated assertion. Do not consider this iteration's E2E gap closed until that follow-up lands.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** — T001 must run before any other task (captures baseline for US3).
- **Foundational (Phase 2)** — empty for this feature; user stories proceed directly after T001.
- **User Stories (Phase 3+)**:
  - US1 (Phase 3) and US2 (Phase 4) can run in parallel **on different branches** but their tasks targeting `config.py` and `chart_values.j2.yaml` MUST be serialized when merged (no `[P]` across these two files across stories).
  - US3 (Phase 5) depends on US1 and US2 implementation tasks completing (T005, T006, T013, T014). Run last.
- **Polish (Phase 6)** — depends on all stories complete.

### Within Each User Story

- Test tasks are written FIRST and observed to fail (Constitution §V test-first).
- Within US1: T002, T003, T004 → T005 → T006 → T008 (docstring after impl is fine; runbook T007 is independent and can run anytime after T001).
- Within US2 (E2E in T012/T016 is bundled cross-story with US1): T009, T010, T011, T012 → T013 → T014 → T015 → T016. T012 and T016 are labeled `[US1] [US2]` because they assert on both stories' fields; they require US1's implementation tasks (T005, T006) to be merged before they can be authored or run.
- Within US3: T017 → T018 (the new test must exist before the suite-wide verification).

### Parallel Opportunities

- T007 (US1 manual runbook in `dev/guides/`) is in a separate file from all production-code and test-file work — `[P]` safe with everything from T002 onward.
- T020 and T021 (Polish) target different files (test-suite execution vs. doc cross-check) — `[P]` safe with each other.
- US1 and US2 can be developed in parallel by different people on different branches; merge ordering must serialize edits to `config.py` and `chart_values.j2.yaml`.

---

## Parallel Example: User Story 1

```bash
# Once T001 (baseline) is captured, US1's runbook can be authored in parallel
# with the unit-test additions:
Task: "T007 — write manual-validation runbook at dev/guides/ingress-ipv6-dual-stack-validation.md"
Task: "T002, T003, T004 — add failing unit tests in backend/tests/unit/services/test_ingress_controller.py"

# After T002–T004 fail and T005, T006 land, T008 (docstring) is independent of the runbook:
Task: "T008 — update IngressServiceConfig docstring with FR-012 dual-stack guidance"
```

---

## Implementation Strategy

### MVP First (US1 + US2 = full Cloudflare/Infrahub recipe)

The spec assigns both US1 and US2 to **P1**: the Cloudflare-fronted Infrahub recipe needs both knobs. The honest MVP is therefore both stories together:

1. T001 — capture baseline.
2. US1 — IPv6 pinning (T002 → T008).
3. US2 — fixed NodePort (T009 → T016).
4. US3 — backward-compat verification (T017, T018).
5. Polish (T019 → T022).

If a partial-MVP cut is needed (e.g., to unblock a deployment quickly), US2 alone is the more impactful slice — the NodePort drift is the more frequently-felt pain, and US2's flow has full automated E2E coverage. US1 alone ships the IPv6 pinning but relies on the manual runbook for cluster-side verification.

### Incremental Delivery

1. T001 → baseline captured.
2. US1 lands → operators can pin IP families; manual runbook bridges to dual-stack verification.
3. US2 lands → operators get stable Cloudflare origin port with automated E2E coverage.
4. US3 verification → backward-compat guarantee asserted in tests.
5. Polish → format/lint + cross-checks.

Each story integrates into the existing dedicated-ingress flow without modifying any other deployment path.

### Parallel Team Strategy

- Person A: US1 on branch `001-…/ipv6` (T002–T008).
- Person B: US2 on branch `001-…/nodeport` (T009–T016).
- Merge ordering: serialize the `config.py` and `chart_values.j2.yaml` edits at merge time (rebase the second branch onto the first; resolve the trivial additive conflicts).
- Person A or B: US3 verification (T017, T018) after both branches merge.
- Either person: Polish (T019–T022).

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- `[Story]` label maps each task to its user story for traceability.
- Each user story is independently testable — US1 by unit/snapshot + manual runbook, US2 by unit/snapshot + automated E2E, US3 by suite-level non-regression.
- Verify tests fail before implementing (Constitution §V test-first).
- Commit after each task or logical group.
- Stop at any checkpoint to validate the story independently.
- The §V partial deviation (no automated dual-stack E2E in this iteration) is recorded in `plan.md` Complexity Tracking with the user's explicit approval logged in `spec.md` § Clarifications.
