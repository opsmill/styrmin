# E2E Evidence: 023 Per-Component Replica Counts

Task T031. Local runs of `test_scale_server_and_singleton_guard` (research D-012), one variant per pytest session, at commit `e3c3013c`. Each session ran the whole `test_deployment_image_override.py` module, so the image override tests ran after the replica test on the shared `image_override_deployment`.

## Image build

```bash
export STYRMIN_IMAGE_VER=replicas-c06-e3c3013c
docker compose build server
```

Image: `registry.opsmill.io/opsmill/styrmin:replicas-c06-e3c3013c`.

## API variant

```bash
export STYRMIN_IMAGE_VER=replicas-c06-e3c3013c
sleep infinity | uv run pytest backend/tests/e2e/test_deployment_image_override.py \
  -m "ci and shard_configuration" -k "api-chromium" -v -s --pdb
```

- vCluster: `pytest-a7e4c56f-f0b0-418a-ad21-bdcd842cd686` (Docker driver, created and deleted by the session fixture)
- Kubeconfig: `/tmp/pytest-of-root/pytest-1593/vcluster0/kubeconfig`
- Session start: 2026-10-15T10:16:04+00:00
- Replica test passed: by 2026-10-15T10:18:45+00:00 (the time the `PASSED` line was read)
- Session end: 2026-10-15T10:23:31+00:00

With `-s`, the session fixture's image build output is printed between the node ID and `PASSED`; the lines below join them.

```text
backend/tests/e2e/test_deployment_image_override.py::test_scale_server_and_singleton_guard[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_then_clear[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_with_version_change_reaches_upgrade_job[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_token_follows_upgrade_and_action_job[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_misnamed_container_never_added[api-chromium] PASSED
============ 5 passed, 5 deselected, 1 warning in 445.51s (0:07:25) ============
```

While the session ran, the events of the deployment namespace showed the scale-up and the scale-down that the test read after each update task:

```text
Scaled up replica set styrmin-simple-app-8fc9c4cbd from 1 to 2
Scaled down replica set styrmin-simple-app-8fc9c4cbd from 2 to 1
```

## UI variant

```bash
export STYRMIN_IMAGE_VER=replicas-c06-e3c3013c
sleep infinity | uv run pytest backend/tests/e2e/test_deployment_image_override.py \
  -m "ci and shard_configuration" -k "ui-chromium" -v -s --pdb
```

- vCluster: `pytest-2a160f17-0f2a-4893-a283-4b1092d7cfc3`
- Kubeconfig: `/tmp/pytest-of-root/pytest-1598/vcluster0/kubeconfig`
- Session start: 2026-10-15T10:23:54+00:00
- Replica test passed: by 2026-10-15T10:26:47+00:00
- Session end: 2026-10-15T10:30:38+00:00

```text
backend/tests/e2e/test_deployment_image_override.py::test_scale_server_and_singleton_guard[ui-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_then_clear[ui-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_with_version_change_reaches_upgrade_job[ui-chromium] SKIPPED
backend/tests/e2e/test_deployment_image_override.py::test_token_follows_upgrade_and_action_job[ui-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_misnamed_container_never_added[ui-chromium] SKIPPED
====== 3 passed, 2 skipped, 5 deselected, 1 warning in 403.76s (0:06:43) =======
```

The two skipped tests are marked `api_only`.

## Whole `shard_configuration` shard

Quickstart §4 asks for the rest of the shard in each variant, because `simple-app` version 4 adds a replica patch of 1 on the `database` StatefulSet of every `simple-app` deployment.

### UI variant

```bash
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k "ui-chromium" -v -s --pdb
```

- vCluster: `pytest-b6b478cf-aee0-47e0-8157-8a6c5993506d`
- Kubeconfig: `/tmp/pytest-of-root/pytest-1599/vcluster0/kubeconfig`
- Session: 2026-10-15T10:30:58+00:00 to 2026-10-15T10:42:17+00:00
- `test_scale_server_and_singleton_guard[ui-chromium] PASSED` in this session too; the skipped tests are `api_only`

```text
===== 13 passed, 8 skipped, 172 deselected, 1 warning in 678.72s (0:11:18) =====
```

### API variant

```bash
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k "api-chromium" -v -s --pdb
```

- vCluster: `pytest-92b2e956-3421-42d7-bced-304e7baeeaed`
- Kubeconfig: `/tmp/pytest-of-root/pytest-1600/vcluster0/kubeconfig`
- Session: 2026-10-15T10:42:37+00:00 to 2026-10-15T10:53:06+00:00
- `test_scale_server_and_singleton_guard[api-chromium] PASSED` in this session too; the 12 skipped tests are the `ui_only` drawer tests under `backend/tests/e2e/configuration/`

```text
===== 9 passed, 12 skipped, 172 deselected, 1 warning in 627.75s (0:10:27) =====
```

## Verification runs at commit `973f9a47` (T065, X1, X2)

Commit `973f9a47` adds two UI assertions to existing tests:

- X1: in the UI variant of `test_scale_server_and_singleton_guard`, while `server` has an override of 2, the Component Overrides card of the Settings tab shows `server` `2 (override)` and `database` `1 (driver default, singleton)`. These are the only two components `simple-app` declares, and the test asserts the whole mapping.
- X2: in `test_driver_detail_inspects_versions_via_tabs`, the Components tab of the `simple-app` driver shows Replicas `not set` and Singleton `no` for `server`, and Replicas `not set` and Singleton `yes` for `database`.

The same server image was used for all three sessions, which ran one after another:

```bash
export STYRMIN_IMAGE_VER=replicas-c12-973f9a47
docker compose build server
```

With `-s`, the vCluster output is printed between the node ID and `PASSED`; the lines below join them. Pytest keeps only the three most recent base directories, and other sessions on the host created newer ones, so the directories of these sessions no longer exist. A kubeconfig path is recorded only where the file was observed during the session.

### X2: driver detail Components tab (`shard_general`, UI variant)

```bash
sleep infinity | uv run pytest "backend/tests/e2e/test_ui_smoke.py::test_driver_detail_inspects_versions_via_tabs" \
  -m "ci and shard_general" -k ui-chromium -v -s --pdb
```

- vCluster: `pytest-56f1ca93-fb99-41be-857e-f472d6ed2b09` (created and deleted by the session fixture)
- Kubeconfig: `/tmp/pytest-of-root/pytest-1639/vcluster0/kubeconfig` (the only `vcluster0/kubeconfig` written during the session, at 11:59:29)
- Session: 2026-10-15T11:58:06+00:00 to 2026-10-15T11:59:47+00:00; the test passed by 2026-10-15T11:59:43+00:00

```text
backend/tests/e2e/test_ui_smoke.py::test_driver_detail_inspects_versions_via_tabs[ui-chromium] PASSED
============ 1 passed, 1 deselected, 1 warning in 99.81s (0:01:39) =============
```

### T065: whole `shard_configuration`, API variant

```bash
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k api-chromium -v -s --pdb
```

- vCluster: `pytest-42e00438-962b-4575-ae76-3634975c344c`
- Kubeconfig: `/tmp/pytest-of-root/pytest-1646/vcluster0/kubeconfig` (written at 12:01:56, when the session created its vCluster)
- Session: 2026-10-15T12:01:36+00:00 to 2026-10-15T12:16:04+00:00
- The 12 skipped tests are the `ui_only` drawer tests under `backend/tests/e2e/configuration/`

```text
backend/tests/e2e/test_deployment_container_overrides.py::test_us1_override_args_on_server[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us2_command_independent_of_args[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us3_set_and_clear_command_and_args[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us4_invalid_overrides_rejected[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_scale_server_and_singleton_guard[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_then_clear[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_with_version_change_reaches_upgrade_job[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_token_follows_upgrade_and_action_job[api-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_misnamed_container_never_added[api-chromium] PASSED
===== 9 passed, 12 skipped, 172 deselected, 1 warning in 866.43s (0:14:26) =====
```

### T065 and X1: whole `shard_configuration`, UI variant

```bash
sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_configuration" -k ui-chromium -v -s --pdb
```

- vCluster: `pytest-8cccd72c-f7b5-4192-ba2c-00979ed67c3f`
- Kubeconfig: not recorded. The log does not print the base directory, and pytest removed it before it was read.
- Session: 2026-10-15T12:16:43+00:00 to 2026-10-15T12:28:17+00:00; `test_scale_server_and_singleton_guard[ui-chromium]`, which holds the X1 assertion, passed by 2026-10-15T12:25:08+00:00
- Skipped: 5 `api_only` tests, plus 3 drawer tests that carry `skip` or `skipif` markers (`test_drawer_driver_params_edit`, `test_drawer_networking_edit`, `test_drawer_storage_runtime_edit`)

```text
backend/tests/e2e/configuration/test_configuration_tab_read.py::test_configuration_tab_renders_inheritance_and_overrides[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_component_overrides_edit.py::test_drawer_component_overrides_edit[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_disruptive_change.py::test_drawer_disruptive_toleration_effect_change[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_env_vars_edit.py::test_drawer_env_vars_edit[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_multi_section_edit.py::test_drawer_multi_section_edit[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_multi_section_edit.py::test_drawer_concurrent_edit_surfaces_conflict_panel[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_scheduling_edit.py::test_drawer_scheduling_edit[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_scheduling_edit.py::test_drawer_scheduling_edit_keyboard_only[ui-chromium] PASSED
backend/tests/e2e/configuration/test_drawer_service_overrides_edit.py::test_drawer_service_overrides_edit[ui-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us3_set_and_clear_command_and_args[ui-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_scale_server_and_singleton_guard[ui-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_override_then_clear[ui-chromium] PASSED
backend/tests/e2e/test_deployment_image_override.py::test_token_follows_upgrade_and_action_job[ui-chromium] PASSED
===== 13 passed, 8 skipped, 172 deselected, 1 warning in 691.23s (0:11:31) =====
```
