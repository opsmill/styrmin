# E2E Evidence: Load an Application Driver from a Driver Directory of a Git Repository

This file records the local E2E runs for spec 028 ([#517](https://github.com/opsmill/styrmin/issues/517)), with the details that Constitution §V asks for: the pytest node IDs, the exact command, the start and end times, the vcluster and its kubeconfig path, and the `PASSED` lines as pytest printed them. Each run has its own section; add later runs at the end of the file.

- Branch: `fac/check-driver-from-git-repo-works-0d15v`
- Every run gives pytest a standard input that stays open, so `--pdb` can stop at a failure, and stops only its own `sleep` afterwards (the pattern in each command).
- Colour codes are removed from the quoted pytest lines. With `-s`, other output can sit between a node ID and its `PASSED`; where it does, the node ID is given with the line.

## Early single-test run for T026 and T027 (API variant)

This run checks the fixture change of T024 and T026 and the assertions of T027 before the full shard runs. The full `shard_general` runs are T052 (API variant) and T053 (UI variant).

- Commit tested: `6595abcb` ("test(drivers): load the session E2E driver from a driver directory (#517)").
- Command, from the repository root:

  ```bash
  export STYRMIN_IMAGE_VER=e2e028-1792262388
  docker compose build server
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e/test_driver_version_reselection.py -m "ci and shard_general" -k api-chromium -v -s --pdb <&3 > e2e-attempt1.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-17T18:40:00Z. End: 2026-10-17T18:43:40Z.
- vcluster: `pytest-fffb29b8-ba8c-4d5e-a83d-4346251da1e9`.
- Kubeconfig: `/tmp/pytest-of-root/pytest-1948/vcluster0/kubeconfig`.
- Collected: `collected 4 items / 2 deselected / 2 selected`.
- In this session, `styrmin_resources` loaded `simple-app` from the driver directory `drivers/simple-app` of `git://git-server.default.svc.cluster.local/driver-collection.git`, and `deployed_simple_app` deployed that driver version and ran its setup actions. The test then checked that the driver version stores `sourcePath == "drivers/simple-app"` and that its Prefect action deployments, tagged `fingerprint/<commit>` and `directory/drivers/simple-app`, have the pull steps `git_clone` then `set_working_directory` into `.../drivers/simple-app`.
- `test_drivers_list_caps_long_histories` is `ui_only`, so the API variant skips it.

Result lines:

```text
backend/tests/e2e/test_driver_version_reselection.py::test_driver_version_reselection[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_driver_version_reselection.py::test_drivers_list_caps_long_histories[api-chromium] SKIPPED
====== 1 passed, 1 skipped, 2 deselected, 1 warning in 218.29s (0:03:38) =======
```

## T052: full `shard_general` run (API variant)

This run checks that every `[api-chromium]` test of `shard_general` passes when the session fixture `styrmin_resources` loads `simple-app` from the driver directory `drivers/simple-app` of the `driver-collection` repository on the E2E git server. The shard passed on the first attempt, so no node needed a rerun.

- Commit tested: `197d368e` ("chore(drivers): record lint and unit suite verification of spec 028 (#517)").
- Command, from the repository root. The log is written to the session's scratch directory instead of `/tmp/e2e-028-api.log`:

  ```bash
  export STYRMIN_IMAGE_VER=e2e028-1792264606
  docker compose build server
  exec 3< <(sleep infinity); spid=$!
  uv run pytest backend/tests/e2e -m "ci and shard_general" -k api-chromium -v -s --pdb <&3 > e2e-028-api-attempt1.log 2>&1
  exec 3<&-; kill "$spid"
  ```

- Start: 2026-10-17T19:17:06+00:00. End: 2026-10-17T19:25:20+00:00.
- vcluster: `pytest-ed6d5d60-2d48-483a-8518-0d75e9f14e3e`.
- Kubeconfig: `/tmp/pytest-of-root/pytest-1960/vcluster0/kubeconfig`.
- Collected: `collected 201 items / 174 deselected / 27 selected`.
- The session fixture loads `simple-app` with `driver_directory="drivers/simple-app"` from `git://git-server.default.svc.cluster.local/driver-collection.git` (`backend/tests/e2e/conftest.py`). Every test that deploys the session driver ran against that driver version. `test_driver_version_reselection` checked that the driver version stores `sourcePath == "drivers/simple-app"` and that its Prefect action deployments clone the commit and set their working directory to `drivers/simple-app`.
- The 10 skipped nodes are marked `ui_only`, so the API variant skips them: the `test_ui_smoke.py` module, `test_delete_deployment_ui`, `test_environment_views_hide_ingress_controller` and `test_drivers_list_caps_long_histories`. The `[ui-chromium]` run is T053.
- In the log, the vcluster teardown message (`19:25:13 info Removing vCluster container ...`) follows the last `SKIPPED` on the same line. It is left out of the quote below.

Result lines:

```text
backend/tests/e2e/test_admin_group_membership.py::test_admin_group_membership_lifecycle[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_admin_user_crud.py::test_admin_user_crud_lifecycle[api-chromium] PASSED
backend/tests/e2e/test_auth_lifecycle.py::test_auth_lifecycle[api-chromium] PASSED
backend/tests/e2e/test_delete_deployment_api.py::test_delete_deployment_api[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_delete_deployment_ui.py::test_delete_deployment_ui[api-chromium] SKIPPED
backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium] PASSED
backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_deploy_app.py::test_deployment_records_created_by[api-chromium] PASSED
backend/tests/e2e/test_deploy_app.py::test_deployed_service_external_url_includes_port[api-chromium] PASSED
backend/tests/e2e/test_deploy_app.py::test_environment_views_hide_ingress_controller[api-chromium] SKIPPED
backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_has_entries[api-chromium] PASSED
backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_after_upgrade[api-chromium] PASSED
backend/tests/e2e/test_deployment_timeline.py::test_deployment_timeline_ordering[api-chromium] PASSED
backend/tests/e2e/test_deployment_typed_input.py::test_update_deployment_typed_input_propagates_component_env_var_and_scheduling[api-chromium] PASSED
backend/tests/e2e/test_driver_version_reselection.py::test_driver_version_reselection[api-chromium] PASSED
backend/tests/e2e/test_driver_version_reselection.py::test_drivers_list_caps_long_histories[api-chromium] SKIPPED
backend/tests/e2e/test_pod_component_attribution.py::test_pod_component_attribution[api-chromium] PASSED
backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report[api-chromium]   (node ID line; PASSED follows the -s output)
PASSED
backend/tests/e2e/test_service_discovery.py::test_service_discovery_between_apps[api-chromium] PASSED
backend/tests/e2e/test_service_discovery.py::test_service_rename_creates_new_kubernetes_service[api-chromium] PASSED
backend/tests/e2e/test_ui_smoke.py::test_deployment_header_shows_driver_name[api-chromium] SKIPPED
backend/tests/e2e/test_ui_smoke.py::test_deploy_form_shows_driver_label_after_selection[api-chromium] SKIPPED
backend/tests/e2e/test_ui_smoke.py::test_pods_tab_copy_logs_command[api-chromium] SKIPPED
backend/tests/e2e/test_ui_smoke.py::test_driver_detail_inspects_versions_via_tabs[api-chromium] SKIPPED
backend/tests/e2e/test_ui_smoke.py::test_driver_logo_description_and_links_render[api-chromium] SKIPPED
backend/tests/e2e/test_ui_smoke.py::test_browser_tab_title_names_page_and_product[api-chromium] SKIPPED
backend/tests/e2e/test_ui_smoke.py::test_cluster_detail_shows_full_configuration[api-chromium] SKIPPED
==== 17 passed, 10 skipped, 174 deselected, 1 warning in 491.21s (0:08:11) =====
```
