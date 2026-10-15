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
