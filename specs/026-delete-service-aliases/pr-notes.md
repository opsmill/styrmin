# Pull Request Notes: Deleting a Deployment Deletes Its Service Aliases

Draft notes for the pull request description of spec 026 ([#503](https://github.com/opsmill/styrmin/issues/503)). Task T037 completes them.

## Deleting `intent` in the E2E test affects no later test of the `shard_general` session

<!-- T013 (critique E5), checked on 2026-10-16 -->

`test_deleted_deployment_leaves_no_alias` deletes the `intent` deployment of the session's scenario environment. CI runs the shard with `-m "ci and shard_general" -k "api-chromium"` (`.github/workflows/ci.yml`), and pytest runs the modules in file-name order, so two `shard_general` modules run after `test_service_discovery.py`:

- `test_ui_smoke.py` is marked `ui_only`, so pytest skips all its tests in the `api-chromium` session. In the `ui-chromium` session the new test is skipped instead, so `intent` stays.
- `test_worker_death_recovery.py` takes neither `driver_mode` nor `scenario_driver`, so its node ID has no `api-chromium` part and `-k "api-chromium"` deselects it. It also reads only the `styrmin` namespace and Prefect, not the scenario environment.

No other module refers to `intent` (`grep -rn intent backend/tests/e2e` finds it only in `test_service_discovery.py` and in unrelated comments). No module that runs after `test_service_discovery.py` counts the scenario environment's deployments. `executor` keeps running until the session ends, so the deletion does not empty the environment. Running the module alone is therefore enough for the local E2E evidence.
