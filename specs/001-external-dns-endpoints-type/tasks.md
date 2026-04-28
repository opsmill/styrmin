---

description: "Task list for external-dns endpoints-type opt-in for application Ingress"
---

# Tasks: external-dns endpoints-type opt-in for application Ingress

**Input**: Design documents from `/specs/001-external-dns-endpoints-type/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Test tasks ARE included — the spec requires them (FR-007 unit-test snapshots, FR-008 E2E extension, US2 explicitly tests Pydantic validation).

**Organization**: Tasks are grouped by user story (US1 = P1 IPv6/Cloudflare opt-in; US2 = P2 reject invalid values).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps to a user story (US1, US2)

## Path Conventions

This is a **monorepo backend feature**. All paths are absolute from the repo root `/home/ubuntu/styrmin/.claude/worktrees/precious-booping-lovelace/`. Production code lives under `backend/styrmin_backend/`; tests live under `backend/tests/unit/` and `backend/tests/e2e/`. No frontend changes.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the Python toolchain has every package needed before editing.

- [ ] T001 Run `uv sync --all-groups --all-packages` from the repo root and confirm it exits cleanly so subsequent `uv run` commands resolve all backend packages.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the new optional field to the shared base config model. Both user stories depend on this.

**⚠️ CRITICAL**: No US1 or US2 task can begin until T002 lands.

- [ ] T002 Add the `external_dns_endpoints_type: Literal["NodeExternalIP", "ClusterIP"] | None = None` field to `BaseConfigSection` in `backend/styrmin_backend/context/models/config.py` (after `external_url_port`, before `scheduling`). Use `Field(default=None, description="...")` whose description satisfies FR-006: explain that operators set this to `"NodeExternalIP"` on IPv6 / dual-stack clusters where external-dns must publish AAAA records that resolve to the node's external IP rather than the Service ClusterIP. Extend the class `Attributes:` docstring with a one-line entry for the new field.

**Checkpoint**: Foundation ready — both user stories can now be implemented.

---

## Phase 3: User Story 1 - IPv6/Cloudflare operator opts in to NodeExternalIP records (Priority: P1) 🎯 MVP

**Goal**: Operator who sets `external_dns_endpoints_type` on cluster/environment/deployment config sees `external-dns.alpha.kubernetes.io/endpoints-type: <value>` on every dedicated-Traefik application Ingress emitted by Styrmin, alongside the existing `hostname` and `cloudflare-proxied` annotations. Operator who leaves the field unset sees byte-identical pre-feature output.

**Independent Test**: Set `"external_dns_endpoints_type": "NodeExternalIP"` on the session cluster fixture; reconcile a deployment; `kubectl get ingress -o yaml` shows the new annotation. Unset → annotation absent.

### Implementation for User Story 1

- [ ] T003 [US1] Modify `IngressUtility.build_app_post_rendering_patches` in `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`. After the existing `annotations = {...}` literal (lines 32–37) and before the `if context.instance.config.dedicated_ingress:` branch, conditionally insert: `if context.instance.config.external_dns_endpoints_type is not None: annotations["external-dns.alpha.kubernetes.io/endpoints-type"] = context.instance.config.external_dns_endpoints_type`. Do not introduce a runtime default; do not alter any existing annotation key. Keep within the 120-char line limit.

### Tests for User Story 1

- [ ] T004 [US1] Add four test methods to `class TestIngressUtilityPostRenderingPatches` in `backend/tests/unit/agent/test_utility_resources.py`:
  - `test_includes_endpoints_type_when_node_external_ip` — set `global_context.instance.config.external_dns_endpoints_type = "NodeExternalIP"`, call `build_app_post_rendering_patches`, assert `annotations["external-dns.alpha.kubernetes.io/endpoints-type"] == "NodeExternalIP"`.
  - `test_includes_endpoints_type_when_cluster_ip` — same with `"ClusterIP"`.
  - `test_omits_endpoints_type_when_unset` — leave `external_dns_endpoints_type` at its `None` default (the existing `global_context` fixture already does), call `build_app_post_rendering_patches`, assert `"external-dns.alpha.kubernetes.io/endpoints-type" not in annotations`. Mirror the lookup pattern of the adjacent `test_includes_external_dns_hostname` and `test_includes_cloudflare_proxied`.
  - `test_deployment_overrides_cluster_endpoints_type` — build a `ClusterConfig(external_dns_endpoints_type="NodeExternalIP", ingress_class="traefik", fqdn_suffix="test.styrmin.com", dedicated_ingress=DedicatedIngressConfig())`, an `EnvironmentConfig()` (field unset), and a `DeploymentConfig(external_dns_endpoints_type="ClusterIP")`. Import `_resolve_instance_config` from `styrmin_backend.context.resolvers`; call it to produce a `ResolvedConfig`. Build a `GlobalContext` whose `instance.config` is that resolved value (reuse the rest of the existing `global_context` fixture's contexts). Run `build_app_post_rendering_patches` and assert `annotations["external-dns.alpha.kubernetes.io/endpoints-type"] == "ClusterIP"`. This test covers FR-002 (deepest-layer-wins merge), US1 Acceptance Scenario 3 (deployment override of cluster value), and the "Field set at multiple layers" edge case in one shot.

- [ ] T005 [P] [US1] Update the session-scoped cluster fixture in `backend/tests/e2e/conftest.py` (the `await driver.create_cluster(...)` call around line 665, inside the `styrmin_resources` fixture). Add `"external_dns_endpoints_type": "NodeExternalIP"` to the cluster `config={...}` dict, alongside the existing `fqdn_suffix` / `ingress_class` / `dedicated_ingress` keys. This exercises the Cluster → Environment → Deployment merge end-to-end and is the single E2E injection point per the spec's clarification (do not add a new scenario).

- [ ] T006 [US1] Extend the existing `test_deploy_with_dedicated_ingress` in `backend/tests/e2e/test_ingress_controller.py` with a single assertion. Inside the existing `for ing in ingresses:` loop (currently asserting `kubernetes.io/ingress.class == "traefik"` and `ingressClassName is None`), add `assert annotations.get("external-dns.alpha.kubernetes.io/endpoints-type") == "NodeExternalIP", f"Expected endpoints-type annotation 'NodeExternalIP', got: {annotations}"`. Do **not** create a new scenario.

**Checkpoint**: User Story 1 is complete and independently testable. Run unit tests (`uv run pytest backend/tests/unit/agent/test_utility_resources.py::TestIngressUtilityPostRenderingPatches -v`) and the extended E2E (`sleep infinity | uv run pytest backend/tests/e2e/test_ingress_controller.py::test_deploy_with_dedicated_ingress -v -s --pdb 2>&1 | tee /tmp/pdb.log`).

---

## Phase 4: User Story 2 - Reject invalid values at config load time (Priority: P2)

**Goal**: An operator who sets `external_dns_endpoints_type` to anything other than `"NodeExternalIP"`, `"ClusterIP"`, `null`, or absent gets a Pydantic `ValidationError` at config-parse time naming the field and listing accepted values — before any Kubernetes resource is rendered.

**Independent Test**: Construct `ClusterConfig(external_dns_endpoints_type="PodIP")` and observe the `ValidationError`. Construct `ClusterConfig(external_dns_endpoints_type=None)` and observe success.

**Note on implementation**: US2 needs **no production code beyond T002**. The `Literal[...] | None` declaration on `BaseConfigSection` is what produces the rejection — Pydantic does the work for free. Phase 4 therefore consists of test tasks only.

### Tests for User Story 2

- [ ] T007 [US2] Create `backend/tests/unit/context/test_base_config_section.py` with two test functions exercising the new field's validation contract:
  - `test_validation_rejects_invalid_endpoints_type` — call `ClusterConfig(external_dns_endpoints_type="PodIP")`, assert it raises `pydantic.ValidationError`. Inspect `exc.errors()` (or the string form) to verify the offending field name (`external_dns_endpoints_type`) and both accepted values (`'NodeExternalIP'`, `'ClusterIP'`) appear in the error payload — this proves the Literal-rejection message satisfies FR-005's "names the offending field and lists accepted values" guarantee.
  - `test_validation_accepts_explicit_null` — call `ClusterConfig(external_dns_endpoints_type=None)`, assert it succeeds and the round-tripped instance has `.external_dns_endpoints_type is None`.

  Use `pytest.raises(ValidationError)`, import `ClusterConfig` from `styrmin_backend.context.models.config`, import `ValidationError` from `pydantic`. Keep the file scoped to this field — do not bundle other config-validation tests in here.

**Checkpoint**: User Story 2 is complete and independently testable. Run `uv run pytest backend/tests/unit/context/test_base_config_section.py -v`.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Hygiene and definition-of-done verification.

- [ ] T008 [P] Run `uv run invoke format lint` from the repo root. Ensure both ruff format and ruff lint pass cleanly on every modified file (`backend/styrmin_backend/context/models/config.py`, `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`, `backend/tests/unit/agent/test_utility_resources.py`, `backend/tests/unit/context/test_base_config_section.py`, `backend/tests/e2e/conftest.py`, `backend/tests/e2e/test_ingress_controller.py`). Per AGENTS.md, ruff and ty are authoritative; do not rely on visual inspection.

- [ ] T009 [P] Run `uv run invoke test` and confirm the full unit + integration suite passes. In particular, the pre-existing `test_includes_external_dns_hostname`, `test_includes_cloudflare_proxied`, `test_includes_traefik_entrypoints_annotation`, and `test_returns_target_patches` tests in `TestIngressUtilityPostRenderingPatches` MUST pass without modification — that's how SC-002 (zero existing-deployment behaviour change) is regression-protected.

- [ ] T010 Run the E2E entrypoint covering the dedicated-Traefik path: `sleep infinity | uv run pytest backend/tests/e2e/test_ingress_controller.py::test_deploy_with_dedicated_ingress -v -s --pdb 2>&1 | tee /tmp/pdb.log`. The `sleep infinity |` keeps pdb's stdin open per AGENTS.md. Confirm the test passes (no pdb breakpoint hit). If it fails, the breakpoint is the diagnostic — open a second shell and `kubectl get ingress -A -o yaml` against the vcluster's kubeconfig (`export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)`), inspect the rendered annotations, fix and re-run.

- [ ] T011 Verify no GraphQL or SDK regeneration is needed by running `uv run invoke validate-graphql` (no `.graphql` files were modified, so the validator should report no changes). Per the plan, `schema.graphql` and SDK types are intentionally untouched — this task confirms the invariant rather than performing a regen.

- [ ] T012 Walk the operator quickstart in `specs/001-external-dns-endpoints-type/quickstart.md` end-to-end: confirm the rendered Ingress in Step 3 carries the new annotation, and confirm Step 2's "remove the field" rollback produces a byte-identical pre-feature annotation set.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** → no dependencies, run first.
- **Foundational (Phase 2 / T002)** → depends on Setup. **BLOCKS** US1 and US2.
- **User Story 1 (Phase 3)** → depends on T002. Can run in parallel with US2 (different test files; T003 only edits `ingress.py` which US2 doesn't touch).
- **User Story 2 (Phase 4)** → depends on T002. Can run in parallel with US1.
- **Polish (Phase 5)** → depends on all desired user stories being complete (US1 alone is the MVP cut; US2 should also be in for a release).

### Within User Story 1

- T003 (production change) gates the unit tests in T004 (they assert behaviour T003 implements).
- T005 (E2E fixture) and T003 are in different files with no code dependency — they can be edited in parallel by a single developer or split across two.
- T006 (E2E assertion) depends on **both** T003 (annotation must actually be emitted) and T005 (fixture must set the field). Run T006 after T003 + T005.

### Within User Story 2

- T007 has no further sub-dependencies. Single test file, two test functions.

### Parallel Opportunities

- US1 and US2 can be implemented in parallel after T002 lands.
- Within US1, T005 can be edited in parallel with T003/T004 (different file, no shared state). Marked `[P]`.
- Within Polish, T008 (lint) and T009 (unit suite) touch disjoint outputs and can run concurrently. Both marked `[P]`. T010 (E2E) takes minutes and should not be parallelised with the unit suite to avoid resource contention against the same vcluster.

---

## Parallel Example: User Story 1

```bash
# After T002 lands, a developer can interleave:
# - Edit production code (T003) in ingress.py
# - Edit unit tests (T004) in test_utility_resources.py — depends on T003 conceptually but file-disjoint
# - Edit E2E fixture (T005) in conftest.py — file-disjoint, no dep on T003

# Then:
# - Edit E2E assertion (T006) in test_ingress_controller.py — depends on T003 + T005

# Run unit tests:
uv run pytest backend/tests/unit/agent/test_utility_resources.py::TestIngressUtilityPostRenderingPatches -v

# Run extended E2E (with --pdb per AGENTS.md):
sleep infinity | uv run pytest backend/tests/e2e/test_ingress_controller.py::test_deploy_with_dedicated_ingress -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. T001 (setup).
2. T002 (foundational field).
3. T003 → T004 → T005 → T006 (US1 production + tests + E2E extension).
4. T008 / T009 / T010 / T011 / T012 (polish).
5. Ship MVP — operator can opt into `NodeExternalIP` and the rendered Ingress carries the annotation.

### Incremental Delivery (US1 + US2)

1. Setup + Foundational (T001–T002).
2. US1 (T003–T006). **STOP**, run unit + E2E, validate.
3. US2 (T007). **STOP**, run unit, validate the validation contract.
4. Polish (T008–T012).

### Single-Developer Strategy

This feature is small enough (~6 LOC production, ~30 LOC test) that one developer can do everything sequentially in a single sitting in the order T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011 → T012. The phase boundaries exist for traceability, not for staffing.

---

## Notes

- **No DB migration**, **no GraphQL schema change**, **no SDK regeneration**, **no frontend change** — see `plan.md` constitution check and `data-model.md` § Storage / § Wire Format.
- **No agent-context script run** — the Styrmin constitution forbids `update-agent-context.sh`.
- Pre-existing tests `test_includes_external_dns_hostname` and `test_includes_cloudflare_proxied` MUST pass unmodified after implementation. They are the regression-fence for SC-002.
- The `--pdb` E2E pattern is mandatory per AGENTS.md; do not strip it to "save time" on green runs (it costs nothing on pass).
