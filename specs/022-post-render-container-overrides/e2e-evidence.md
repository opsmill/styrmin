# E2E Evidence: 022 Post-Render Container Overrides

Task T017. Local run of the container override E2E (`shard_configuration`, API variant) after the T016 changes.

## Command

```bash
export STYRMIN_IMAGE_VER=e2e-457-t017a
docker compose build server
sleep infinity | uv run pytest backend/tests/e2e/test_deployment_container_overrides.py \
  -k api-chromium -v -s --pdb
```

## Environment

- `STYRMIN_IMAGE_VER`: `e2e-457-t017a` (image `registry.opsmill.io/opsmill/styrmin:e2e-457-t017a`)
- vCluster: `pytest-89f5c7ce-9308-4598-af5e-1bc2c2662c88` (Docker driver, created and deleted by the session fixture)
- Kubeconfig: `/tmp/pytest-of-root/pytest-1471/vcluster0/kubeconfig`
- Start: 2026-10-14T11:24:32+00:00
- End: 2026-10-14T11:33:14+00:00

## Result

```text
backend/tests/e2e/test_deployment_container_overrides.py::test_us1_override_args_on_server[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us2_command_independent_of_args[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us3_clear_override_falls_back_to_chart_default[api-chromium] PASSED
backend/tests/e2e/test_deployment_container_overrides.py::test_us4_invalid_overrides_rejected[api-chromium] PASSED
============ 4 passed, 4 deselected, 1 warning in 509.55s (0:08:29) ============
```

The `test_us1` line is joined from the node ID line and the `PASSED` line, because `-s` prints fixture output between them. The 4 deselected tests are the `[ui-chromium]` variants, which `-k api-chromium` leaves out. No test was skipped.

## Clear after an override (research D-012)

`test_us3` waited until the `simple-app` container's `command` and `args` equalled the values captured before any override, and this happened after the clear. The operator's change detection needed no fix.
