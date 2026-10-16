# Implementation report: ingress class set only after the chart renders

| Field | Value |
|-------|-------|
| Feature | 023 Ingress class set only after the chart renders (#471) |
| Spec directory | `specs/024-ingress-class-post-render/` |
| Base commit | `d0080947bebd2eba0779954ec6b83205c8a60bea` |
| Head commit (before this report) | `426eadf7` |
| Wall-clock time | About 1 h 15 min (2026-10-15T09:11:42Z to 10:27Z) |
| Result | DONE: 27 of 27 tasks done, local-pass evidence for every new or modified test |

## 1. Chunk-by-chunk ledger

1. **Phase 1: Setup** (1 task: T001)
   - Outcome: 1 ✅, 0 ⚠️, 0 ❌
   - Commit: `4c55df67`
   - Notes: the baseline was 55 passed and 0 skipped. `helm` v4.1.0 and `kubectl` v1.35.0 are on `PATH`.
2. **Phase 2: Foundational** (6 tasks: T002 to T007)
   - Outcome: 6 ✅, 0 ⚠️, 0 ❌
   - Commit: `731d82bd`
   - Notes:
     - No other test or code depended on the removed step that hid `ingress_class` from the template data.
     - The two new dedicated-mode tests failed on the old code and pass on the new code.
     - The agent unit suite gives 463 passed.
     - The first `pnpm install` ran in the outer emdash workspace and stopped in its postinstall; it left no tracked change. `frontend/node_modules` was then installed with `pnpm --ignore-workspace`.
3. **Phase 3: User Story 1, drivers, documentation and integration test** (6 tasks: T008 to T013)
   - Outcome: 6 ✅, 0 ⚠️, 0 ❌
   - Commits: `71754935`, `5c02e058`, `8ad5053f`
   - Notes:
     - The dedicated case of `test_migrated_simple_app_template_gets_the_class_of_its_mode` passes even without the removal patch, because `simple-app` renders no class when `className` is empty. T016 covers the removal patch.
     - `backend/tests/integration/fixtures/legacy_drivers/simple-app/values.j2.yml` keeps the class line on purpose, because its README forbids edits.
4. **Phase 3: User Story 1, local E2E runs** (2 tasks: T014, T015)
   - Outcome: 2 ✅, 0 ⚠️, 0 ❌
   - Commit: `6a9d2217`
   - Notes: both tests passed on the first attempt. During T015 the `simple-app` Ingress had no `spec.ingressClassName` and had the annotation `kubernetes.io/ingress.class: traefik`.
5. **Phase 4: User Story 2** (2 tasks: T016, T017)
   - Outcome: 2 ✅, 0 ⚠️, 0 ❌
   - Commit: `154df839`
   - Notes: with the removal patch left out of `ingress.py`, all three dedicated cases fail, including the empty chart class, because the `subchart-ui` Ingress keeps `nginx`.
6. **Phase 5: User Story 3** (2 tasks: T018, T019)
   - Outcome: 2 ✅, 0 ⚠️, 0 ❌
   - Commit: `e0ed7a2c`
   - Notes:
     - With the old step that hid `ingress_class` restored, the dedicated case fails with `assert '' == 'nginx'`.
     - The E2E fixture drivers `late-container` and `failing-actions` are unchanged.
     - The local `develop` ref is stale, and `origin/develop` is not an ancestor of `HEAD`.
7. **Phase 6: Polish and cross-cutting concerns** (8 tasks: T020 to T027)
   - Outcome: 8 ✅, 0 ⚠️, 0 ❌
   - Commits: `91f12f8e`, `2ad3682a`, `91713762`, `9a607117`, `437c0a4a`
   - Notes:
     - The task text said no class is resolved "only when the cluster config sets `ingress_class: null`". The code differs, and the documentation says what the code does:
       - An explicit null is possible only at `createCluster`, because `updateCluster` replaces null with `traefik`.
       - An empty string also counts as no class, at any level, when it is the deepest value set.
     - `dedicated_ingress.implementation` accepts any string and defaults to `traefik`. A different value gives an annotation that the dedicated controller does not serve. This was already the case before this change, and it is not changed.
     - The full backend suite gives 4475 passed and 3 skipped. The 3 skips are fixed skip markers unrelated to this change.
8. **Review fixes** (after Phase 6)
   - Commits: `1e6efea3` (documentation), `5ebee846` (tests), `426eadf7` (E2E evidence)
   - Notes: the fixes changed a code comment in `ingress.py` and a docstring in `application.py`. T027 requires new E2E runs after any change under `backend/styrmin_backend/`, so both E2E tests ran again at `5ebee846` and passed.

## 2. Tasks not completed

None. Every task in `tasks.md` is `[X]`.

## 3. Local-pass evidence

All runs used Python 3.14.3, `helm` v4.1.0+g4553a0a and `kubectl` v1.35.0 (Kustomize v5.7.1) on the same host.

### Unit tests

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---------|------|-------------|----------------------|---------------------|--------------------|
| `backend/tests/unit/agent/test_utility_resources.py::TestIngressClassNameRemovalPatch::test_renders_ingress_class_name_null` | unit | `uv run pytest "backend/tests/unit/agent/test_utility_resources.py::TestIngressClassNameRemovalPatch" "backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching" backend/tests/unit/agent/test_render_value_template_ingress_class.py -v -p no:cacheprovider` | 2026-10-15T09:16:40Z | n/a | `...::TestIngressClassNameRemovalPatch::test_renders_ingress_class_name_null PASSED` |
| `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_dedicated_ingress_removes_ingress_class_name` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `...::TestDedicatedIngressPatching::test_dedicated_ingress_removes_ingress_class_name PASSED` |
| `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_dedicated_ingress_sets_annotation` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `...::TestDedicatedIngressPatching::test_dedicated_ingress_sets_annotation PASSED` |
| `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_fallback_to_cluster_ingress_class` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `...::TestDedicatedIngressPatching::test_fallback_to_cluster_ingress_class PASSED` |
| `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_no_ingress_class_patch_when_neither_set` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `...::TestDedicatedIngressPatching::test_no_ingress_class_patch_when_neither_set PASSED` |
| `backend/tests/unit/agent/test_render_value_template_ingress_class.py::test_template_reads_ingress_class_of_every_section[dedicated-ingress]` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `test_render_value_template_ingress_class.py::test_template_reads_ingress_class_of_every_section[dedicated-ingress] PASSED` |
| `backend/tests/unit/agent/test_render_value_template_ingress_class.py::test_template_reads_ingress_class_of_every_section[shared-ingress]` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `test_render_value_template_ingress_class.py::test_template_reads_ingress_class_of_every_section[shared-ingress] PASSED` |
| `backend/tests/unit/agent/test_render_value_template_ingress_class.py::test_unset_ingress_class_renders_empty` | unit | same as above | 2026-10-15T09:16:40Z | n/a | `test_render_value_template_ingress_class.py::test_unset_ingress_class_renders_empty PASSED` |
| `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_dedicated_ingress_removes_class_when_no_class_resolved` | unit | `uv run pytest backend/tests/unit/agent backend/tests/integration/test_ingress_class_post_render.py -v -rs` | 2026-10-15T10:16:49Z | n/a | `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_dedicated_ingress_removes_class_when_no_class_resolved PASSED [ 87%]` |
| `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_shared_ingress_renders_class_then_annotation_patches` | unit | same as above | 2026-10-15T10:16:49Z | n/a | `backend/tests/unit/agent/test_utility_resources.py::TestDedicatedIngressPatching::test_shared_ingress_renders_class_then_annotation_patches PASSED [ 88%]` |

The 09:16:40Z run ended with `8 passed in 0.06s`. The 10:16:49Z run ended with `476 passed, 29 warnings in 6.56s`, with 0 skipped.

### Integration tests

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---------|------|-------------|----------------------|---------------------|--------------------|
| `backend/tests/integration/test_ingress_class_post_render.py::test_migrated_simple_app_template_gets_the_class_of_its_mode[dedicated]` | integration | `uv run pytest backend/tests/integration/test_ingress_class_post_render.py -v -rs` | 2026-10-15T09:22:21Z | helm and kubectl as above | `...::test_migrated_simple_app_template_gets_the_class_of_its_mode[dedicated] PASSED [ 50%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_migrated_simple_app_template_gets_the_class_of_its_mode[shared]` | integration | same | 2026-10-15T09:22:21Z | same | `...::test_migrated_simple_app_template_gets_the_class_of_its_mode[shared] PASSED [100%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_chart_class_is_replaced_or_removed[dedicated-chart-empty]` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_chart_class_is_replaced_or_removed[dedicated-chart-empty] PASSED [ 33%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_chart_class_is_replaced_or_removed[dedicated-chart-traefik]` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_chart_class_is_replaced_or_removed[dedicated-chart-traefik] PASSED [ 44%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_chart_class_is_replaced_or_removed[dedicated-chart-nginx]` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_chart_class_is_replaced_or_removed[dedicated-chart-nginx] PASSED [ 55%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_chart_class_is_replaced_or_removed[shared-chart-empty]` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_chart_class_is_replaced_or_removed[shared-chart-empty] PASSED [ 66%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_chart_class_is_replaced_or_removed[shared-chart-traefik]` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_chart_class_is_replaced_or_removed[shared-chart-traefik] PASSED [ 77%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_chart_class_is_replaced_or_removed[shared-chart-nginx]` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_chart_class_is_replaced_or_removed[shared-chart-nginx] PASSED [ 88%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_no_class_resolved_keeps_the_chart_class` | integration | same | 2026-10-15T09:34:35Z | same | `...::test_no_class_resolved_keeps_the_chart_class PASSED [100%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_template_that_still_sets_the_class_gives_the_same_ingress[dedicated]` | integration | same | 2026-10-15T09:37:15Z | same | `backend/tests/integration/test_ingress_class_post_render.py::test_template_that_still_sets_the_class_gives_the_same_ingress[dedicated] PASSED [ 90%]` |
| `backend/tests/integration/test_ingress_class_post_render.py::test_template_that_still_sets_the_class_gives_the_same_ingress[shared]` | integration | same | 2026-10-15T09:37:15Z | same | `backend/tests/integration/test_ingress_class_post_render.py::test_template_that_still_sets_the_class_gives_the_same_ingress[shared] PASSED [100%]` |

The whole module passed again twice:

- At 2026-10-15T09:42:19Z, during T026: `11 passed in 1.30s`, 0 skipped.
- At 2026-10-15T10:16:49Z, after a one-line comment fix in the module, in the 476-test run listed above.

### E2E tests (existing tests, run locally)

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---------|------|-------------|----------------------|---------------------|--------------------|
| `backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress[api-chromium]` | e2e | `export STYRMIN_IMAGE_VER=e2e-471-5ebee846 && docker compose build server`, then `sleep infinity \| uv run pytest "backend/tests/e2e/test_cluster_update.py::test_cluster_update_redeploys_and_moves_dedicated_ingress" -k api-chromium -v -s --pdb` | 2026-10-15T10:22:14Z | HEAD `5ebee846`; vCluster `pytest-8a6d40e0-e21f-40f8-820c-fba965fd1338`; kubeconfig `/tmp/pytest-of-root/pytest-1596/vcluster0/kubeconfig` | `PASSED10:22:14 info Removing vCluster container vcluster.cp.pytest-8a6d40e0-e21f-40f8-820c-fba965fd1338...` and `1 passed, 1 deselected, 1 warning in 231.94s (0:03:51)` |
| `backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress[api-chromium]` | e2e | same image, then `sleep infinity \| uv run pytest "backend/tests/e2e/test_ingress_controller.py::test_traffic_routes_through_dedicated_ingress" -k api-chromium -v -s --pdb` | 2026-10-15T10:24:52Z | HEAD `5ebee846`; vCluster `pytest-fce84793-3f02-4064-bb34-eac6bb537481`; kubeconfig `/tmp/pytest-of-root/pytest-1597/vcluster0/kubeconfig` | `PASSED10:24:52 info Removing vCluster container vcluster.cp.pytest-fce84793-3f02-4064-bb34-eac6bb537481...` and `1 passed, 1 deselected, 1 warning in 137.56s (0:02:17)` |

Both E2E tests also passed earlier, at HEAD `8ad5053f` with image `e2e-471-8ad5053f`: at 2026-10-15T09:28:02Z (216.53 s) and 09:31:09Z (142.00 s). [e2e-evidence.md](e2e-evidence.md) has both sets of runs. No new E2E test was added; the idea review of #471 approved this, as recorded in the spec's Testing Approach. No E2E row is deferred.

## 4. Review findings

The review covered `d0080947..437c0a4a` with five reviewers, run one after the other: code, tests, comments, types and simplify. The errors reviewer did not run, because the change adds and alters no error handling. No finding was rated critical or high.

| Severity | File | Summary | Status |
|----------|------|---------|--------|
| Medium | `docs/docs/concepts-and-architecture/ingress-and-networking.md` | Existing text said Ingresses use the cluster's `ingress_class`; the new text said the resolved value | Fixed, `1e6efea3` |
| Medium | `backend/tests/unit/agent/test_utility_resources.py` | No test pinned the shared-mode patch list, so a reordered or added shared-mode patch passed every test | Fixed, `5ebee846` |
| Low | `dev/adr/0071-ingress-class-set-by-post-render.md`, `ingress-and-networking.md`, `ingress.py:49` | Wrong reason why the dedicated controller ignores `spec.ingressClassName`: it runs with `disableIngressClassLookup: true` and reads no IngressClass | Fixed, `1e6efea3` |
| Low | `changelog/471.changed.md` | Described shared-mode behavior, which was already the case, as new | Fixed, `1e6efea3` |
| Low | `CONTEXT.md`, `dev/knowledge/backend/data-models.md` | Left out the case where no class is resolved and the chart's class stays | Fixed, `1e6efea3` |
| Low | `ingress-and-networking.md`, ADR-071 | "When one of them sets an empty string" was too broad; only the deepest value set counts | Fixed, `1e6efea3` |
| Low | `dev/knowledge/backend/data-models.md` | Said the agent removes the field; the Flux helm-controller applies the patch that the agent writes | Fixed, `1e6efea3` |
| Low | `docs/docs/drivers/context.md`, `docs/docs/drivers/creating-a-driver.md` | The lead "No Ingress class." read as "the Ingress has no class" | Fixed, `1e6efea3` |
| Low | `application.py` docstring, `data-models.md`, `CONTEXT.md`, ADR-071 | "Driver templates do not set the class" was stated as a fact | Fixed, `1e6efea3` |
| Low | `backend/tests/integration/test_ingress_class_post_render.py` | A comment said both Ingresses carry the chart's class, which is false for the empty chart class | Fixed, `5ebee846` |
| Low | `backend/tests/unit/agent/test_utility_resources.py` | No dedicated-mode test had no resolved class | Fixed, `5ebee846` |
| Low | `specs/024-ingress-class-post-render/spec.md` (Testing Approach) | The `late-container` and `failing-actions` E2E tests cannot detect a missing removal patch, because the main E2E cluster resolves `traefik`; only the integration test detects it | Deferred |
| Low | `backend/tests/integration/test_ingress_class_post_render.py` | No test checks that `semaphore` and `slurpit` keep no class line, or that the example drivers keep their `spec.version` | Deferred |
| Low | `backend/styrmin_backend/.../blocks/patches.py:749` | `_operation="remove"` names the JSON6902 operation that research D-001 rejected; the `Patch` base class requires the field and nothing reads it | Deferred |
| Low | `backend/styrmin_backend/.../blocks/patches.py:745-747` | `api_version`, `kind` and `name` are constructor arguments that do not change which resources the patch applies to | Deferred |
| Medium (advisory) | `backend/tests/integration/test_ingress_class_post_render.py:158-199` | `_helm_template`, `_kustomize` and `_render_values` copy the helpers in `test_container_override_migration_parity.py`; they could move to `backend/tests/helpers/` | Deferred |
| Low (advisory) | test files | Seven small test cleanups, such as assertions that can never fail, a repeated annotation lookup and an unused `values_template` on `ChartInfo` | Deferred |

## 5. Autonomous decisions

- Phase 3 ran as two chunks: drivers, documentation and the integration test (T008 to T013), then the E2E runs (T014, T015). The E2E runs take long and change no code.
- Phase 1 (one task) ran as its own chunk instead of being merged with Phase 2.
- The skill requires inline fixes only for findings rated high or above. I also fixed two medium findings and eight low findings:
  - Ten of them were documentation or comment statements that contradict the code, which Constitution §VII forbids.
  - One was the shared-mode test gap. A regression there would change every shared-mode HelmRelease.
  - All of them were small.
- The review fixes changed only a comment and a docstring under `backend/styrmin_backend/`. Both E2E tests still ran again, because T027 requires it after any change in that directory.
- The errors reviewer did not run, because the change has no error handling.
- The seven remaining findings are deferred. They are low severity or advisory, or out of scope; for example, a separate base class for strategic merge patches would touch every patch class.

## 6. Suggested next steps

1. Rebase the branch onto `origin/develop`. It is not an ancestor of `HEAD`, and the local `develop` ref is stale.
2. Open a pull request. List the high-risk area (agent post-render patches applied to every application HelmRelease) and the local E2E evidence.
3. Decide whether to address the deferred findings in this pull request or in a follow-up:
   - Correct the spec's Testing Approach about which E2E tests cover FR-005 in dedicated mode.
   - Move the shared helm and kustomize test helpers into `backend/tests/helpers/`.
   - Give strategic merge patches a base class without `_operation` and `_path`.
4. Decide whether `dedicated_ingress.implementation` should accept only `traefik`, since any other value gives an annotation that the dedicated controller does not serve. This was already the case before this change.
5. Run `speckit-opsmill-extract` on this spec directory when the pull request is merged.
