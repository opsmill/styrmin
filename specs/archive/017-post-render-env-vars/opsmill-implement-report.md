# opsmill-implement report: 017-post-render-env-vars

**Status: DONE.** All 65 tasks finished. Every new or modified test has local-pass evidence.

| Field | Value |
|---|---|
| Feature | Platform-owned env var injection via post-render (#385) |
| Spec dir | `specs/017-post-render-env-vars/` |
| Base commit | `c294559` (`d7d8825` before the rebase onto `develop`) |
| Head commit (before this report) | `ca4b2c2` |
| Commits | 19 (18 from the 14 chunks, 1 review fix) |
| Diff | 101 files changed, +5499 / −942 |
| Wall clock | 2026-10-02T16:47:17Z → 2026-10-02T19:48:38Z (about 3h01m) |

## 1. Chunk ledger

Chunks ran one at a time, each in a fresh subagent.

| # | Chunk | Tasks | ✅ / ⚠️ / ❌ | Commits | Flagged upward |
|---|---|---|---|---|---|
| 1 | Phase 1 Setup | 1 (T001) | 1/0/0 | `7926556` | There are 28 components, not 30. Every D-010 container name was confirmed with `helm template`. Found two existing bugs: slurpit passed `env` to its chart as a list when the chart expects a map, and the semaphore chart has no `extraEnv` key. |
| 2 | Phase 2 Foundational | 4 (T002–T005) | 4/0/0 | `41a1214` | No extra wiring was needed: `container` flows from the driver through to `ComponentContext`. Stored component configs now carry `"container": null` when none is declared. |
| 3a | US1 backend core | 9 (T006–T009, T014–T018) | 9/0/0 | `0d403f6`, `9b95b8e` | Added a `PostRenderPatchRenderingError` base class. The builder skips orphaned env vars. Per-key metadata ops need the label and annotation maps to exist, and the builder always sets both. An offline `kubectl kustomize` merge check passed. |
| 3b | US1 E2E + simple-app | 7 (T010–T013, T019–T021) | 7/0/0 | `02045a7`, `21c8580`, `7e0324c` | **Out-of-task fix in a high-risk area (`02045a7`):** research D-003 was incomplete. The agent merge-patched the StyrminDeployment CR, so cleared env vars stayed in `spec.context`. The agent's CR applies now replace each top-level spec key they write, and leave `spec.deletionRequested` alone. Also: the api and ui E2E variants must run as separate sessions. |
| 4 | US2 | 4 (T022–T025) | 4/0/0 | `e33c618` | The precedence cases passed first time; the builder needed no change. `test_us2` and `test_us3` stay `api_only` because the UI test driver only takes scheduling updates. |
| 5a | US3 driver migrations | 8 (T027, T028, T034–T039) | 8/0/0 | `dcaf712` | Six drivers migrated, all render-verified. slurpit env is back to map shape. infrahub's prefect-server gets its chart env defaults back. Added an extra `changelog/+example-driver-env-wiring.fixed.md` fragment. |
| 5b | US3 filter retirement | 3 (T026, T032, T033) | 3/0/0 | `097651e` | The `RETIRED_TEMPLATE_FILTER` code and metadata collapse into a status string at the operator boundary; the message and the guide URL survive. contracts/errors.md accepts this. |
| 5c | US3 driver-version GraphQL + UI | 5 (T029, T030, T040–T042) | 5/0/0 | `5c091cd` | `invoke lint` reverts unstaged `_generated/` changes. Frontend `node_modules` reinstalled under Node 22. |
| 5d | US3 SC-003 E2E | 2 (T031, T043) | 2/0/0 | `b801d62` | Reuses the existing `deployed_infrahub_enterprise_app` boot, so no extra cluster boot. No credentials needed. |
| 6a | US4 backend | 6 (T044, T045, T047–T050) | 6/0/0 | `a87c1da` | Error metadata keys are snake_case, matching contracts/errors.md. The `styrminctl apply` ordering gap is described in §5. |
| 6b | US4 frontend | 2 (T046, T051) | 2/0/0 | `f8bf738` | Read-only rows get a new test id; the E2E selectors are unchanged. |
| 7 | US5 | 3 (T052–T054) | 3/0/0 | `d354e38` | No new query. Rows from before this feature have no `container` key, so they read `isApplicable: false`. |
| 8a | Docs | 8 (T055–T062) | 8/0/0 | `225287e`, `ab2f917` | ADR-057 written. `contracts/graphql-deltas.md` fixed to snake_case. Some docs went beyond the task list (changelog page, styrminctl reference, DRIVERS.md). |
| 8b | Final gates | 3 (T063–T065) | 3/0/0 | `6fbc5d7` | All gates green. Two CLI tests fail on base and HEAD alike because they run as root. Quickstart corrected. The stale simple-app comments were fixed before the E2E run. |
| — | Review fix | — | — | `ca4b2c2` | Removed stale merge-patch reasoning from the `component_command`/`component_args` docstrings. |

## 2. Tasks not completed

None. All 65 tasks are `[X]`.

## 3. Local-pass evidence

The environment for every backend run used an isolated `PREFECT_HOME=$(mktemp -d)`; the shared `~/.prefect` database is on an unknown revision. E2E sessions ran on per-session vClusters on local docker. Full transcripts are in [`e2e-evidence.md`](e2e-evidence.md).

| Test id | Type | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
|---|---|---|---|---|---|
| `backend/tests/unit/services/driver/test_component_container.py` (whole file) | unit | `uv run pytest backend/tests/unit/services/driver/test_component_container.py backend/tests/unit/context/test_component_context_container.py -v` | 2026-10-02T17:08:01Z | n/a | `16 passed in 0.06s` (both files) |
| `backend/tests/unit/context/test_component_context_container.py::test_stored_context_without_container_key_still_validates` (+ siblings) | unit | same as above | 2026-10-02T17:08:01Z | n/a | `...::test_stored_context_without_container_key_still_validates PASSED [100%]` |
| `backend/tests/unit/agent/test_container_env_patch.py` (18 tests) | unit | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/agent/test_container_env_patch.py backend/tests/unit/services/env_vars/test_patch_builder.py backend/tests/unit/agent/test_application_builder_env_vars.py backend/tests/unit/agent/test_upsert_custom_resource_replace_spec.py -v` | 2026-10-02T17:19:13Z | n/a | `...::TestContainerEnvPatchShape::test_renders_strategic_merge_document PASSED` |
| `backend/tests/unit/services/env_vars/test_patch_builder.py` (12 tests in chunk 3a) | unit | same as above | 2026-10-02T17:19:13Z | n/a | `...::TestEmittedPatches::test_component_with_container_and_env_vars_gets_two_patches PASSED` |
| `backend/tests/unit/agent/test_application_builder_env_vars.py` (4 tests) | unit | same as above | 2026-10-02T17:19:13Z | n/a | `...::TestEnvPatchOrdering::test_env_patches_come_after_every_scheduling_patch PASSED` |
| `backend/tests/unit/agent/test_upsert_custom_resource_replace_spec.py` (10 tests) | unit | same as above | 2026-10-02T17:19:13Z | n/a | `...::test_conflict_sends_single_json_patch PASSED` — summary `44 passed, 4 warnings in 3.76s` |
| `backend/tests/unit/agent/test_upsert_styrmin_deployment_crd_replace_keys.py` | unit | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/agent/test_upsert_styrmin_deployment_crd_replace_keys.py backend/tests/unit/agent/test_upsert_custom_resource_replace_spec.py` | ~2026-10-02T17:30Z (exact time not reported) | n/a | `13 passed in 0.41s`. It also passed in the full-suite runs at 18:19:18Z and 19:4xZ (`invoke test` gave `2053 passed, 2 skipped`). |
| US1 unit selection rerun (T021) | unit | `uv run pytest backend/tests/unit -k "container_env_patch or patch_builder or application_builder_env_vars or replace_spec" -v` | 2026-10-02T17:30:24Z | n/a | `64 passed, 1564 deselected, 4 warnings in 4.59s` |
| `backend/tests/e2e/drivers/test_conformance.py` | unit (e2e harness) | `uv run pytest backend/tests/e2e/drivers/test_conformance.py` | 2026-10-02T17:30:08Z | n/a | `7 passed, 1 warning in 21.54s` |
| `backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[api-chromium]` | e2e | `sleep infinity \| STYRMIN_IMAGE_VER=local-fac017-final uv run pytest backend/tests/e2e/test_deployment_env_vars.py -k "api-chromium" -v -s --pdb` | 2026-10-02T19:27:57Z | vcluster `pytest-057dbcc2-d07f-4c10-9320-137206420609`, `/tmp/pytest-of-root/pytest-324/vcluster0/kubeconfig` | `...::test_component_env_var_merges_into_chart_env[api-chromium] PASSED` (first passed 17:54:27Z on pytest-299) |
| `backend/tests/e2e/test_deployment_env_vars.py::test_component_env_var_merges_into_chart_env[ui-chromium]` | e2e | same, with `-k "ui-chromium"` | 2026-10-02T19:31:07Z | vcluster `pytest-f54a3ede-aef0-44e2-a1ad-e827534fe481`, `/tmp/pytest-of-root/pytest-328/vcluster0/kubeconfig` | `...::test_component_env_var_merges_into_chart_env[ui-chromium] PASSED` (first passed 17:55:31Z on pytest-300) |
| `backend/tests/e2e/test_deployment_env_vars.py::test_us1_deployment_level_env_var[api-chromium]` | e2e | full-module api session (above) | 2026-10-02T19:27:57Z | pytest-324 (above) | `...::test_us1_deployment_level_env_var[api-chromium] PASSED` |
| `backend/tests/e2e/test_deployment_env_vars.py::test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium]` | e2e | full-module api session (above) | 2026-10-02T19:27:57Z | pytest-324 (above) | `...::test_us2_environment_level_env_var_propagates_to_all_deployments[api-chromium] PASSED` (first passed 18:04:38Z on pytest-301) |
| `backend/tests/e2e/test_deployment_env_vars.py::test_us3_per_component_env_var_overrides_deployment_level[api-chromium]` | e2e | full-module api session (above) | 2026-10-02T19:27:57Z | pytest-324 (above) | `...::test_us3_per_component_env_var_overrides_deployment_level[api-chromium] PASSED` — module summary `5 passed, 1 skipped, 6 deselected` |
| `backend/tests/unit/services/env_vars/test_patch_builder.py::TestResolvedScopes::test_deepest_scope_wins_per_component` | unit | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/services/env_vars/test_patch_builder.py -v` | 2026-10-02T18:01:43Z | n/a | `...::TestResolvedScopes::test_deepest_scope_wins_per_component PASSED` |
| `backend/tests/unit/services/env_vars/test_patch_builder.py::TestResolvedScopes::test_deployment_scope_skips_component_without_container` | unit | same as above | 2026-10-02T18:01:43Z | n/a | `...::test_deployment_scope_skips_component_without_container PASSED` — `14 passed in 0.04s` |
| `backend/tests/unit/services/driver/test_example_drivers_container.py` (15 tests) | unit | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/services/driver/test_example_drivers_container.py backend/tests/unit/agent/test_infrahub_values_prefect_env.py -v -p no:cacheprovider` | 2026-10-02T18:14:47Z | n/a | `...::test_expected_mapping_covers_existing_drivers PASSED` |
| `backend/tests/unit/agent/test_infrahub_values_prefect_env.py` (6 tests) | unit | same as above | 2026-10-02T18:14:47Z | n/a | `...::test_prefect_server_env_is_not_overridden[infrahub] PASSED` — `21 passed in 0.10s` |
| `backend/tests/unit/agent/test_render_value_template_env_vars.py` (10 tests, rewritten) | unit | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/unit/agent/test_render_value_template_env_vars.py -v -p no:cacheprovider` | 2026-10-02T18:21:09Z | n/a | `...::TestRetiredComponentEnvVarsFilter::test_operator_records_message_without_applying_helm_release PASSED` — `10 passed, 8 warnings in 4.58s` |
| `backend/tests/functional/graphql/test_application_driver_version_propagation.py::test_component_container_propagates_from_driver_load_to_graphql` | functional (propagation) | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/functional/graphql/test_application_driver_version_propagation.py -v` | 2026-10-02T18:30:12Z | in-memory SQLite | `...::test_component_container_propagates_from_driver_load_to_graphql PASSED [ 75%]` |
| `backend/tests/functional/graphql/test_application_driver_version_propagation.py::test_component_container_is_null_for_rows_without_the_key` | functional (propagation) | same as above | 2026-10-02T18:30:12Z | in-memory SQLite | `...::test_component_container_is_null_for_rows_without_the_key PASSED [100%]` |
| `frontend/src/__tests__/drivers/ComponentsTab.test.tsx` › shows each component's declared container | frontend | `cd frontend && PATH=/root/.local/node22/bin:$PATH pnpm exec vitest run src/__tests__/drivers/ComponentsTab.test.tsx --reporter=verbose` | 2026-10-02T18:30:15Z | Node 22.16.0, jsdom | `✓ ComponentsTab > shows each component's declared container` |
| `frontend/src/__tests__/drivers/ComponentsTab.test.tsx` › none-declared state | frontend | same as above | 2026-10-02T18:30:15Z | Node 22.16.0, jsdom | `✓ ComponentsTab > shows an explicit none-declared state for a component without a container` |
| `backend/tests/e2e/test_infrahub_services.py::test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium]` | e2e | `sleep infinity \| STYRMIN_IMAGE_VER=local-fac017-final uv run pytest backend/tests/e2e/test_infrahub_services.py -k "api-chromium" -v -s --pdb` | 2026-10-02T19:34:24Z | vcluster `pytest-d7711c10-4c5b-4fc5-a7b2-be2476c54389`, `/tmp/pytest-of-root/pytest-330/vcluster0/kubeconfig` | `...::test_infrahub_task_manager_service_exposes_prefect_ui[api-chromium] PASSED` (first passed 18:37:59Z on pytest-314) |
| `backend/tests/functional/graphql/test_update_deployment_input_errors.py` (21 new + 9 existing) | functional | `PREFECT_HOME=$(mktemp -d) uv run pytest backend/tests/functional/graphql/test_update_deployment_input_errors.py "backend/tests/functional/graphql/test_env_vars_propagation.py::test_component_container_propagation_follows_pinned_driver_version" "backend/tests/functional/graphql/test_update_deployment_input_propagation.py::test_update_deployment_input_components_env_vars" -v` | 2026-10-02T18:51:51Z | local Postgres test fixtures | `...::test_component_container_lost_on_switch_rejects_add_or_change[add_key] PASSED` |
| `backend/tests/functional/graphql/test_env_vars_propagation.py::test_component_container_propagation_follows_pinned_driver_version` | functional (propagation) | same as above | 2026-10-02T18:51:51Z | local Postgres test fixtures | `...::test_component_container_propagation_follows_pinned_driver_version PASSED` |
| `backend/tests/functional/graphql/test_update_deployment_input_propagation.py::test_update_deployment_input_components_env_vars` (modified fixture) | functional (propagation) | same as above | 2026-10-02T18:51:51Z | local Postgres test fixtures | `...::test_update_deployment_input_components_env_vars PASSED` — `32 passed in 2.75s` |
| `ComponentOverridesSection.test.tsx` › (FR-006) offers no env var editor and explains why | frontend | `cd frontend && pnpm exec vitest run src/components/deployment/configuration/sections/edit/ComponentOverridesSection.test.tsx --reporter=verbose` | 2026-10-02T18:57:07Z | Node v22.16.0 | `✓ …ComponentOverridesSection: components without a component container (FR-006) > offers no env var editor and explains why` |
| `ComponentOverridesSection.test.tsx` › (FR-006) explains the restriction before an override block exists | frontend | same as above | 2026-10-02T18:57:07Z | Node v22.16.0 | `✓ … (FR-006) > explains the restriction before an override block exists` |
| `ComponentOverridesSection.test.tsx` › (FR-006) shows stored env vars read-only, with a working remove control | frontend | same as above | 2026-10-02T18:57:07Z | Node v22.16.0 | `✓ … (FR-006) > shows stored env vars read-only, with a working remove control` |
| `ComponentOverridesSection.test.tsx` › components with a component container › keeps the editable env var editor | frontend | same as above | 2026-10-02T18:57:07Z | Node v22.16.0 | `✓ …components with a component container > keeps the editable env var editor` — `Tests  9 passed (9)` |
| `backend/tests/functional/graphql/test_env_vars_propagation.py::test_component_env_vars_is_applicable_follows_pinned_driver_version` | functional (propagation) | `PREFECT_HOME=$(mktemp -d) uv run pytest "<id>" -v -p no:cacheprovider` | 2026-10-02T19:02:32Z | n/a | `...::test_component_env_vars_is_applicable_follows_pinned_driver_version PASSED [ 50%]` |
| `backend/tests/unit/services/env_vars/test_patch_builder.py::TestResolvedScopes::test_stored_values_on_component_that_lost_its_container_emit_none` | unit | same as above | 2026-10-02T19:02:32Z | n/a | `...::test_stored_values_on_component_that_lost_its_container_emit_none PASSED [100%]` — `2 passed in 0.28s` |
| `backend/tests/e2e/test_deployment_container_overrides.py` us1/us2/us3/us4/us6 `[api-chromium]` (regression only; file not modified) | e2e | `sleep infinity \| STYRMIN_IMAGE_VER=local-fac017-final uv run pytest backend/tests/e2e/test_deployment_container_overrides.py -k "api-chromium" -v -s --pdb` | 2026-10-02T19:45:52Z | vcluster `pytest-08e2c2ba-f0ff-4014-b733-abded28275cf`, `/tmp/pytest-of-root/pytest-331/vcluster0/kubeconfig` | `5 passed, 5 deselected, 1 warning in 192.62s` (the first run flaked; see §4) |

Suite-wide gates (T063, about 19:2xZ):

- `invoke test`: `2053 passed, 2 skipped, 18 warnings in 61.48s`
- `pnpm test`: `Tests  519 passed (519)`
- `validate-graphql`: `200/200 .graphql files passed validation.`
- docs: `[SUCCESS] Generated static files in "build".`
- `format lint`: `All checks passed!`

After the review fix, `backend/tests/unit/agent` gave `248 passed, 17 warnings in 4.92s` at 2026-10-02T19:48:25Z.

## 4. Review findings

The review was done by hand in the main context, without the `speckit-review-run` skill; §5 explains why. I read every changed backend, frontend and driver template file, concentrating on the high-risk apply path: HelmRelease spec replace, StyrminDeployment CR spec-key replace, and the operator pipeline. No high-severity findings.

| Severity | File | Summary | Status |
|---|---|---|---|
| Medium | `python_sdk` / `styrminctl apply` (config write then version switch) | `apply` writes config before it switches driver version, so the write guard checks against the old version. A manifest that both moves to a migrated driver and adds component env vars is rejected. A manifest that moves to a version where a component loses its container can store inert values; these are flagged `isApplicable: false` and never injected. | Deferred. Documented in ADR-057 and the migration guide ("upgrade first"). Fix by reordering `apply` or adding a combined mutation. |
| Low | `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py` | The `component_command`/`component_args` docstrings still said the empty-list marker is required because of merge-patch. That stopped being true once the HelmRelease spec is replaced. | **Fixed** in `ca4b2c2`. |
| Low | `backend/styrmin_backend/operator/pipeline.py` (`execute_phase_helmrelease`) | The `RETIRED_TEMPLATE_FILTER` code and metadata collapse into the deployment status string `Failed to create HelmRelease: …`; the message and guide URL survive. | Deferred. contracts/errors.md accepts this, and a unit test pins it. |
| Low | `backend/styrmin_backend/agent/service/kubernetes/primitives.py` (per-key spec replace) | Top-level spec keys whose new value is `None` are pruned rather than removed, so an old value would persist. `instanceId` is the only nullable key, and it never goes back to null in practice. | Deferred. |
| Low | `backend/tests/e2e/test_deployment_container_overrides.py::test_us4_invalid_overrides_rejected` | One timeout: two back-to-back update flows wrote the CR 24 ms apart and the older write landed last. This last-writer-wins race exists with merge-patch too, so it isn't caused by this change. The re-run passed. | Deferred. Possible CI flake; worth an issue. |
| Low | `backend/tests/e2e/drivers/ui_driver.py` | The UI test driver only accepts scheduling updates, so `test_us1`–`test_us3` stay `api_only` even though the frontend now has deployment-scope env var editors. | Deferred. Follow-up coverage. |
| Info | `spec.md`, `plan.md`, `tasks.md`, research D-002 | The docs say 30 components; there are 28. D-002 gives the wrong path for `get_component_env` (it is in `agent/service/kubernetes/primitives.py`). | Deferred. Spec doc drift; candidate for `speckit-reconcile-run`. |

## 5. Autonomous decisions

- **No review skill.** Phase 6 says to invoke `speckit-review-run`. A saved user preference forbids review skills and review subagents, so I did the review by hand in the main context. Subagents were still used for implementation, which the preference does not cover.
- **Chunking.** 14 chunks. US1 was split into backend core and E2E/simple-app. US3 was split four ways, with the **driver migrations run before the filter retirement**, the reverse of tasks.md order, so that no intermediate commit had unmigrated in-repo drivers failing to render. US4 was split into backend and frontend. Polish was split into docs and gates.
- **Accepted the out-of-task high-risk fix `02045a7`.** The agent's StyrminDeployment CR applies now replace each top-level spec key, leaving `spec.deletionRequested` alone. Without it, FR-011 (clearing restores chart defaults) failed end to end. It is recorded in research D-003 (addendum), in ADR-057, and covered by unit tests and the US1 E2E. **Please review it as high-risk operator/agent code.**
- **Accepted extra work beyond the task list:** the slurpit list-to-map env fix plus its changelog fragment, the restored infrahub prefect-server chart env defaults, and extra docs pages (changelog narrative, styrminctl reference, DRIVERS.md).
- **Metadata casing.** I kept snake_case `COMPONENT_CONTAINER_NOT_DECLARED` metadata, matching contracts/errors.md and the sibling error, and corrected `contracts/graphql-deltas.md`. tasks.md T044 still says camelCase.
- **Pre-existing failures not fixed.** Two CLI telemetry tests fail when run as root, on both d7d8825 and HEAD (`2 failed, 262 passed` both times).
- **E2E variants.** Every E2E ran `[api-chromium]` and `[ui-chromium]` as separate sessions (one cluster per install). Tests marked `api_only` ran only the api variant. No E2E was deferred.

## 6. Suggested next steps

1. Review `02045a7` (CR spec-key replace) and `9b95b8e` (HelmRelease spec replace) closely, since both are in the high-risk apply path.
2. Open the PR, with US1 and US3 landing together as planned (the PR template asks for high-risk callouts on operator/agent changes).
3. File follow-ups: the `styrminctl apply` ordering gap, the `test_deployment_container_overrides` CR write race, UI-driver support for deployment-scope env vars, and `get_component_env` name-based container selection (ADR-057).
4. Optionally run `speckit-reconcile-run` to fix the spec drift (component count, D-002 path, T044 casing).

## 7. Addendum: per-key HelmRelease apply (post-report)

Follow-up decision after review (option A). The HelmRelease apply in `9b95b8e` replaced the whole
`spec` (`add /spec`), which also undid spec keys Styrmin never writes, such as `spec.suspend`
from `flux suspend hr`. It now uses the same per-key mode as the StyrminDeployment CR apply from
`02045a7`: one `add /spec/<key>` per top-level spec key Styrmin writes. The wholesale mode and
the `replace_spec_on_update` flag are removed. Rule for both resources: Styrmin owns each
top-level spec key it writes; everything else merges (ADR-057 §6, research D-003 revision).

Pure merge-patch was ruled out because a merge-patch deletes a map key only through an explicit
`null`, so stale user env keys in map-shaped values slots (infrahub, neo4j, slurpit) could never
be cleared. Merge-patch with computed deletions, server-side apply, and dropping FR-011 are
recorded as alternatives in ADR-057.

Evidence for this change is in `e2e-evidence.md` (per-key section). The env-vars module passed
on api (5 passed) and ui (1 passed). container-overrides passed us1, us2, us3 and us6.

container-overrides `test_us4_invalid_overrides_rejected` failed again. The live cluster
confirmed the cause: two concurrent `apply_state` flows for one deployment, with the earlier
mutation's CR write landing last. This is independent of the apply mode, so it is a
pre-existing race for its own issue.

## 8. Rebase onto develop

Before the PR, the branch was rebased onto `develop` (`f89664f`, 50 commits ahead). The SHAs in
this report are the rebased ones. Conflict resolutions:

- `develop` already had ADR-0055 and ADR-0056, so this feature's ADR is now
  `dev/adr/0057-post-render-component-overrides.md` (ADR-057). Every reference to it is
  updated; references to `develop`'s ADR-055 (environment backups) are untouched.
- `develop` moved the driver conformance suite to
  `backend/tests/unit/test_e2e_driver_conformance.py`. The
  `test_set_component_env_vars_is_declared_keyword_only` check moved with it (`17 passed`).
- `dev/README.md` (ADR index) and `docs/docs/changelog.md`: both sides kept, with this
  feature's changelog entry first.

After the rebase:

- `schema.graphql` and the generated SDK/frontend types regenerate with no diff, and
  `validate-graphql` reports `230/230`.
- `format lint` passes, and backend non-E2E tests give `2547 passed, 2 skipped`.
- Frontend: `tsc -b` is clean, `641 passed`, and lint has 0 errors.
- The docs build reports `[SUCCESS]`.
- E2E was not re-run after the rebase.
