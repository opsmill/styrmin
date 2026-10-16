# Implementation report: 024 helm-controller runs with Helm v4 defaults (#435)

- Status: DONE
- Spec directory: `/root/emdash/worktrees/styrmin-55123dec/fac-helm-v4-end3k/specs/024-helm-v4-defaults`
- Branch: `fac/helm-v4-end3k`
- Base commit: `5a2cb5db`
- Head commit before this report: `76e981c4`
- Wall-clock time: 2026-10-16T08:24:54Z to 2026-10-16T12:05Z, about 3 h 40 min
- Tasks: 34 of 34 ticked `[X]` in `tasks.md`

## 1. Chunk ledger

| # | Chunk (tasks.md phase) | Tasks | ✅ / ⚠️ / ❌ | Commits |
|---|------------------------|-------|-------------|---------|
| 1 | Phase 1: Setup | 1 (T001) | 1 / 0 / 0 | `2a7881c3` |
| 2 | Phase 2: Foundational | 9 (T002–T010) | 9 / 0 / 0 | `8a5d3b61`, `f752856a` |
| 3 | Phase 3: User Story 1 | 3 (T011–T013) | 3 / 0 / 0 | `fe06e502` |
| 4 | Phase 4: User Story 2 | 9 (T014–T022) | 9 / 0 / 0 | `d6193096`, `edea76e4` |
| 5 | Phase 5: User Story 3 | 1 (T023) | 1 / 0 / 0 | `45310b26` |
| 6 | Phase 6: User Story 4 | 7 (T024–T030) | 7 / 0 / 0 | `81c37c51` |
| 7 | Phase 7: Polish and Verification | 4 (T031–T034) | 4 / 0 / 0 | `8affc418` |
| – | Phase 6 review fixes | – | – | `5bb88fcf`, `76e981c4` |

What each chunk flagged:

1. **Setup.** The baseline was green: 40 unit tests and 13 integration tests passed. Local tools are older than the ones helm-controller bundles: `helm` v4.1.0 (helm-controller has v4.2.4) and kustomize v5.7.1 in `kubectl` (helm-controller has v5.8.1). `frontend/node_modules` was missing, so the subagent installed it in a Node 22 container for the generated-types lint step.
2. **Foundational.**
   - The old JSON patch fails on a resource without labels with `add operation does not apply: doc is missing path`; the new strategic merge passes on a `Deployment`, a `ConfigMap` without labels and a hook `Job` without labels.
   - No existing test pinned the old patch form; the full unit suite passed (3762 passed).
   - The repository does not run doctests, because the existing `LabelPatch` docstring fails doctest collection. The new class's doctest was run directly.
3. **User Story 1.**
   - No operator change was needed.
   - helm-controller v1.6.5 with Helm v4 defaults still reports the rollback of a post-renderers-only change as `Ready=True` (`UpgradeSucceeded`) about 11 s after the rollback. The operator still reports `RolledBack`.
   - New installs use server-side apply (`apply_method: ssa`, `managedFields` operation `Apply`).
   - The failed step now carries FluxCD's kstatus text `timeout waiting for: [Deployment/<ns>/<name> status: 'InProgress']`.
4. **User Story 2.**
   - The E2E git-server image needed `RUN git init --bare /git/hook-job.git`, which the tasks did not name. The first API run stopped in setup without it.
   - The hook `ConfigMap` gets Styrmin's labels but no `styrmin/component` label, because no component identifier matches it.
   - Each upgrade's hook `Job` carries that upgrade's scheduling settings.
   - The UI session needed one rerun for the known flake `test_edit_cluster_config_from_detail_page[ui-chromium]`.
5. **User Story 3.**
   - All nine expected results of quickstart §4 were met: no new release revision after the agent chart upgrade, the same pod start times, and the next change kept client-side apply (`apply_method: csa`, `managedFields` operation `Update`).
   - The check used the E2E fixtures and a temporary test that held the deployment between steps. "The chart from develop" was this branch's chart with the two gate lines put back, which is the only difference under `helm/` against `origin/develop`.
   - Gap: the server and agent image was the same before and after the upgrade. A real upgrade also changes the label patch in each HelmRelease's `spec.postRenderers`. Whether the operator re-renders HelmReleases, and so upgrades releases, right after an agent upgrade was not checked.
6. **User Story 4.**
   - The ADR is `dev/adr/0072-helm-v4-defaults-releases-keep-apply-method.md`, because 0071 is taken on the open branch `origin/fac/ingress-class-post-render-tb7qv`.
   - The driver guide follows the code where it is more specific than the task text. The overrides and the component-container guard reach a hook only when the component has an override, and the scheduling patches match a component's first identifier label on the hook's own `metadata.labels`.
   - The docs site builds without broken links.
7. **Polish.**
   - `uv run invoke test`: 4498 passed. Integration suite: 37 passed. E2E collection: 195 tests collected. The docs site builds.
   - The task's `grep -v "specs/"` filters lines by content, not path, so it hid one intended line; `git grep` with a path exclusion found it.
   - The subagent added an entry to the hand-written `docs/docs/changelog.md`.
   - The PR notes are in `pr-notes.md`. The repository has no pull request template.

## 2. Tasks not completed

None. Every task in `tasks.md` is `[X]`.

## 3. Local-pass evidence

### Tests added or modified

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---------|------|-------------|----------------------|---------------------|--------------------|
| `backend/tests/unit/agent/test_blocks.py::test_metadata_labels_merge_patch_*` (11 ids, including `value_stays_a_string[123/true/null/1.0//yes]` and `newline_value_stays_one_value`) | unit | `uv run pytest backend/tests/unit/agent/test_blocks.py -v -k metadata_labels` | 2026-10-16T08:33:22Z | n/a | `11 passed, 27 deselected in 0.07s` |
| Doctest of `MetadataLabelsMergePatch` | unit (doctest) | `uv run python` with `doctest.DocTestFinder().find(MetadataLabelsMergePatch)` and `DocTestRunner` | 2026-10-16T08:30:12Z | n/a | `TestResults(failed=0, attempted=2)` |
| `backend/tests/integration/test_label_patch_kustomize.py::test_labels_reach_resources_with_and_without_labels` | integration | `uv run pytest backend/tests/integration/test_label_patch_kustomize.py -v` | 2026-10-16T08:33:50Z | `kubectl` v1.35.0, kustomize v5.7.1 | `backend/tests/integration/test_label_patch_kustomize.py::test_labels_reach_resources_with_and_without_labels PASSED [100%]` |
| `backend/tests/unit/test_helm_agent_crd_upgrade.py::test_helm_controller_runs_with_helm_v4_defaults` (added in chunk 2, extended in review fix `5bb88fcf`) | unit | `uv run pytest backend/tests/unit/test_helm_agent_crd_upgrade.py -v` | 2026-10-16T12:03:57Z (first pass 08:34:30Z) | n/a | `backend/tests/unit/test_helm_agent_crd_upgrade.py::test_helm_controller_runs_with_helm_v4_defaults PASSED [100%]` |
| `backend/tests/unit/test_helm_agent_crd_upgrade.py::test_fixture_controllers_run_the_chart_images[helm-controller]` and `[source-controller]` (modified: helper moved to module level) | unit | `uv run pytest backend/tests/unit/test_helm_agent_crd_upgrade.py -v` | 2026-10-16T08:34:30Z | n/a | `PASSED [ 83%]` and `PASSED [ 91%]` |
| `backend/tests/unit/agent/test_custom_resources.py::test_minimal_helm_release_leaves_the_helm_v4_defaults_to_flux` | unit | `uv run pytest backend/tests/unit/agent/test_custom_resources.py -v` | 2026-10-16T08:34:45Z | n/a | `backend/tests/unit/agent/test_custom_resources.py::test_minimal_helm_release_leaves_the_helm_v4_defaults_to_flux PASSED [100%]` |
| `backend/tests/unit/test_simple_app_hook_job.py::test_no_hook_by_default` | unit | `uv run pytest backend/tests/unit/test_simple_app_hook_job.py -v` | 2026-10-16T09:33:49Z | `helm` v4.1.0 | `backend/tests/unit/test_simple_app_hook_job.py::test_no_hook_by_default PASSED [ 50%]` |
| `backend/tests/unit/test_simple_app_hook_job.py::test_enabled_renders_the_hook_job_and_the_unlabelled_hook_config_map` | unit | `uv run pytest backend/tests/unit/test_simple_app_hook_job.py -v` | 2026-10-16T09:33:49Z | `helm` v4.1.0 | `backend/tests/unit/test_simple_app_hook_job.py::test_enabled_renders_the_hook_job_and_the_unlabelled_hook_config_map PASSED [100%]` |
| `backend/tests/e2e/test_pod_scheduling.py::test_scheduling_end_to_end[api-chromium]` (modified: hook-job driver, hook Job and hook ConfigMap assertions) | e2e | `uv run pytest backend/tests/e2e -m "ci and shard_compute" -k api-chromium -v -s --pdb <&3` | 2026-10-16T09:32:55Z (session 09:22:23Z–09:32:55Z) | vcluster `pytest-5016eb89-01ec-494a-b643-3c50f21712ee`, kubeconfig `/tmp/pytest-of-root/pytest-1721/vcluster0/kubeconfig`, `STYRMIN_IMAGE_VER=helmv4-f752856a` | `test_pod_scheduling.py::test_scheduling_end_to_end[api-chromium] PASSED` |
| `backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium]` (its module's `scheduling_deployment` fixture changed) | e2e | same session as above | 2026-10-16T09:32:55Z | same as above | `test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql[api-chromium] PASSED` |

### Regression E2E sessions run against the change (no test in them was changed)

| Session | Run command | Time window (UTC) | Environment context | Summary line |
|---------|-------------|-------------------|---------------------|--------------|
| `shard_task_steps`, API variant (T011) | `uv run pytest backend/tests/e2e -m "ci and shard_task_steps" -k api-chromium -v -s --pdb <&3` | 2026-10-16T08:41:05Z–08:50:28Z | vcluster `pytest-aebe3cf0-7b84-4fcb-9e12-4383c63b5847`, kubeconfig `/tmp/pytest-of-root/pytest-1718/vcluster0/kubeconfig`, `STYRMIN_IMAGE_VER=helmv4-f752856a` | `5 passed, 190 deselected, 1 warning in 560.55s (0:09:20)` |
| `shard_configuration`, API variant (T012, excluded from CI) | `uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k api-chromium -v -s --pdb <&3` | 2026-10-16T08:53:03Z–09:07:28Z | vcluster `pytest-de8167c0-b674-48d0-b691-0ba2facbd5e7`, kubeconfig `/tmp/pytest-of-root/pytest-1719/vcluster0/kubeconfig`, same image tag | `8 passed, 12 skipped, 175 deselected, 1 warning in 862.89s (0:14:22)` |
| `shard_compute`, API variant (T021) | see the table above | 2026-10-16T09:22:23Z–09:32:55Z | see the table above | `7 passed, 1 skipped, 187 deselected, 1 warning in 630.22s` |
| `shard_compute`, UI variant (T022), after one rerun of a known flake | `uv run pytest backend/tests/e2e -m "ci and shard_compute" -k ui-chromium -v -s --pdb <&3` | 2026-10-16T09:36:09Z–09:40:43Z | vcluster `pytest-c86e8031-09f0-4ccd-ad09-2f7c363ed3b0`, kubeconfig `/tmp/pytest-of-root/pytest-1725/vcluster0/kubeconfig`, same image tag | `4 passed, 4 skipped, 187 deselected, 1 warning in 270.97s` |
| Agent-upgrade check (T023, temporary holder test, not committed) | E2E fixtures with a temporary test file; see `agent-upgrade-check.md` | 2026-10-16T11:07:00Z–11:13:08Z | vcluster `pytest-de7d989e-5ab1-45bc-bdf1-d9faa14877ac`, kubeconfig `/tmp/pytest-of-root/pytest-1726/vcluster0/kubeconfig` | `1 passed, 1 warning in 366.07s` |

The node ids and verbatim `PASSED` lines of each session are in [e2e-evidence.md](e2e-evidence.md), runs 1 to 4. The agent-upgrade check is in [agent-upgrade-check.md](agent-upgrade-check.md).

Full suites after all chunks (T031): `uv run invoke test` printed `4498 passed, 3 skipped, 31 warnings in 150.38s (0:02:30)`, and `uv run pytest backend/tests/integration -q` printed `37 passed in 28.39s`. Both ran between 11:28Z and 11:32Z, before the review fixes. After the review, only `test_helm_agent_crd_upgrade.py` was run again (12 passed).

## 4. Review findings

The review ran `speckit-review-run` over `5a2cb5db..HEAD` with five aspects in sequence: code, tests, comments, types and simplify. The errors aspect was skipped because the change adds no error handling.

| Severity | Aspect | File | Summary | Outcome |
|----------|--------|------|---------|---------|
| High | comments | `dev/knowledge/agent/operator.md:141` (and a first review fix in `operator-and-crds.md`, `docs/docs/changelog.md`) | The text said FluxCD's wait for Helm hooks never ends early. Helm waits for each hook by itself, and fluxcd/pkg ssa stops a wait when only `Failed` and `Current` statuses are left, so a failed hook `Job` ends its wait. | Fixed, `76e981c4` |
| Medium | code | `dev/adr/0072-…md:141` | The ADR named a backup annotation-patch limitation that the code does not have: `TemplateAnnotationPatch` is a strategic merge, and a JSON `add` on missing annotations succeeds in kustomize. | Fixed, `76e981c4` |
| Medium | tests | `backend/tests/unit/test_helm_agent_crd_upgrade.py:113` | The gate test dropped templated lines, so a gate re-added through a templated argument would pass. | Fixed, `5bb88fcf`; a mutation check with a templated `--feature-gates` line fails the test |
| Medium | comments | `changelog/435.changed.md:1` | It said any downgrade turns the gate on again; only a downgrade to a release that runs helm-controller with the gate does. | Fixed, `76e981c4` |
| Medium | comments | `changelog/435.changed.md:1`, `pr-notes.md` | They left out that server-side apply returns only fields that the chart sets. | Fixed, `76e981c4` |
| Low | comments | `operator-and-crds.md:109`, `docs/docs/changelog.md:53`, `pr-notes.md:16`, ADR `:34` | They said an upgrade uses the apply method of the "previous install or upgrade"; it uses the newest revision's method, and a rollback uses its target revision's method (R-004). | Fixed, `76e981c4` |
| Low | comments | ADR `:153` | It said the hook `ConfigMap` receives all patches; it receives Styrmin's labels only. | Fixed, `76e981c4` |
| Low | comments | `dev/knowledge/backend/e2e-testing.md:398` | A new test driver that reuses an example chart also needs `chart_name` in its conftest entry. | Fixed, `76e981c4` |
| Low | comments | ADR `:75-77`, `CONTEXT.md:154` | The list of patches that reach hooks leaves out the stopped-component `replicas: 0` patch, the backup annotation patch and the Ingress patches. | Deferred |
| Low | comments | `docs/docs/drivers/creating-a-driver.md:102-118`, `docs/docs/changelog.md` | They write "hook" alone, which `CONTEXT.md` lists under _Avoid_. | Deferred |
| Low | code | `backend/tests/integration/test_label_patch_kustomize.py:85` | The test has no case for a custom resource, a CRD, `labels: null` or a `kind: List`. The reviewer checked all four by hand and each one gets the labels. | Deferred |
| Low | tests | `backend/tests/unit/agent/test_custom_resources.py:42` | C-002 is checked on `build_minimal_helm_release()` only, not on `ApplicationHelmReleaseBuilder.build()`. | Deferred |
| Low | tests | `backend/tests/e2e/test_pod_scheduling.py:483-527` | The expected labels come from the server Deployment, which gets them from the same patch, so a label dropped from every resource still passes. | Deferred |
| Low | tests | `backend/tests/e2e/test_pod_scheduling.py:117-136` | A failed hook `Job` fails the upgrade first, so the test times out in the scheduling wait with a message about the pod template, not the hook. | Deferred |
| Low | tests, simplify | `backend/tests/unit/test_simple_app_hook_job.py:57-82` | The test pins template details that C-005 does not require (command, image, requests). | Deferred |
| Low | types | `patches.py:290-291` | The inherited `_path` and `_operation` fields do nothing in a strategic-merge patch. Sibling strategic-merge patches have the same pattern, and no code reads them. | Deferred |
| Low | types | `patches.py:293-296` | Label keys and the prefix are not validated; no current caller passes an invalid one. | Deferred |
| Low | types | `patches.py:288` | `labels` is typed `dict[str, str]`, but the caller passes `dict[str, Any]`; `str(value)` makes it work. | Deferred |
| Simplify (high value) | simplify | `backend/tests/integration/test_label_patch_kustomize.py:120-152` | The `_kustomize`, `_render` and `_context` helpers copy those of `test_component_container_kustomize.py`; moving the test into that file removes about 70 lines. | Deferred |
| Simplify (medium) | simplify | `backend/tests/unit/test_simple_app_hook_job.py:23-33` | `_render` copies the one in `test_helm_agent_crd_upgrade.py`. | Deferred |
| Simplify (low) | simplify | `test_helm_agent_crd_upgrade.py:119-121`, `test_pod_scheduling.py:503,525` | The parsed-argument checks duplicate the raw-text checks; the label subset checks could use `expected.items() <= labels.items()`. | Deferred |

## 5. Autonomous decisions to review

- **Chunks.** One chunk per `tasks.md` phase, seven in all. Phase 1 (one task) was kept on its own, as the chunking rule says.
- **ADR number.** 0072 instead of 0071, because 0071 is taken on `origin/fac/ingress-class-post-render-tb7qv`. Check again at merge time. `plan.md` and `tasks.md` still say 0071.
- **Work outside the task list:**
  - the git-server `Dockerfile` line for the `hook-job` repository (chunk 4);
  - the entry in the hand-written `docs/docs/changelog.md` (chunk 7).
- **Method of the agent-upgrade check (T023).**
  - "The chart from develop" was this branch's chart with the two gate lines restored.
  - The check used one forced reconcile instead of waiting two HelmRelease intervals, because the interval is 1 h.
  - The image was the same before and after, so the effect of the changed label patch on existing HelmReleases after a real agent upgrade is not known.
- **Known flake.** The UI session of `shard_compute` was rerun once for `test_edit_cluster_config_from_detail_page[ui-chromium]`. It passed on the rerun.
- **Review triage.**
  - Besides the high finding, the medium findings and four low documentation findings were also fixed, because they were factual errors in user-facing pages and cost one edit each.
  - Test and type refactors were deferred.
  - The errors aspect was skipped as not applicable.
- **Prep documents left unchanged.** `research.md` R-008 and `plan.md` still describe the backup annotation-patch limitation that the code does not have, and `plan.md` names ADR 0071. This command does not modify prep documents.
- **Version gap in local tools.** The kustomize integration test ran with kustomize v5.7.1; helm-controller uses v5.8.1.

## 6. Suggested next steps

1. Open the pull request, starting from [pr-notes.md](pr-notes.md). It asks the maintainer to confirm that `Stalled` and the readiness timeout keep unit-test coverage only, and it states that the API cell of `shard_configuration` ran locally because CI excludes it.
2. Decide whether the agent-upgrade gap needs a check with a real image upgrade: does the operator re-render `Ready` HelmReleases after an agent upgrade, and so upgrade releases because the label patch changed?
3. Run `speckit-reconcile-run` to bring `plan.md` and `research.md` in line: ADR 0072, and no backup annotation-patch limitation in R-008.
4. Consider the deferred findings, first the duplicated kustomize test helpers and the C-002 check on `ApplicationHelmReleaseBuilder.build()`.
