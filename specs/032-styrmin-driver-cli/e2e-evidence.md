# E2E and validation evidence: 032-styrmin-driver-cli

Each entry gives the command, the time of the run, the cluster, and the result lines copied from the output, as constitution section V requires.

## Pull request 1: the move to the SDK (T026)

The move adds no E2E test. The existing E2E tests that load and deploy a driver ran on the moved code.

- Command: `sleep infinity | uv run pytest backend/tests/e2e/test_deploy_app.py -k "api-chromium" -v -s --pdb -p no:cacheprovider 2>&1 | tee e2e-pr1.log`
- Time: the run ended at 2026-10-28T14:28:20+01:00 and took 230.92 s.
- Cluster: the session vCluster `pytest-ba093e3c-d426-4ff7-bdeb-553d84df8de6` (container `vcluster.cp.pytest-ba093e3c-d426-4ff7-bdeb-553d84df8de6`), created and removed by the session fixture.
- Image: `registry.opsmill.io/opsmill/styrmin:latest`, built by the session from the working tree with the moved code.
- Result:

  ```text
  backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_upgrade_simple_app[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_deployment_records_created_by[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_deployed_service_external_url_includes_port[api-chromium] PASSED
  backend/tests/e2e/test_deploy_app.py::test_environment_views_hide_ingress_controller[api-chromium] SKIPPED
  ====== 4 passed, 1 skipped, 5 deselected, 6 warnings in 230.92s (0:03:50) ======
  ```

  The skipped test is marked `ui_only` (`backend/tests/e2e/test_deploy_app.py:499-503`), so the API variant skips it. The `[ui-chromium]` variants were not run.

Other checks of pull request 1, on the same working tree:

| Command | Result |
|---------|--------|
| `uv run pytest tests --ignore=tests/e2e -q -n auto` (in `backend/`) | 5773 passed, 8 skipped, 1 failed. The failure, `tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused` (7.8 s against a 2 s limit), fails the same way on a clean checkout of `HEAD` on this machine. |
| `uv run pytest -q python_sdk/tests` | 347 passed |
| `uv run pytest -q cli/tests` | 416 passed |
| `uv run invoke lint` | ruff, ty, rumdl, yamllint and the GraphQL check pass. The last step, `generate-validate`, did not run: `graphql-codegen` is missing because `frontend/node_modules` is not installed in this worktree. |
| `uv lock --check` | passes; `uv.lock` adds no package |

## Pull request 2: the command (T044)

- Node: `backend/tests/e2e/test_deploy_app.py::test_styrmin_driver_matches_helm_release[api-chromium]`
- Command: `sleep infinity | uv run pytest "backend/tests/e2e/test_deploy_app.py::test_styrmin_driver_matches_helm_release[api-chromium]" -v -s --pdb -p no:cacheprovider 2>&1 | tee e2e-us2.log`
- Time: the run ended at 2026-10-28T14:41:03+01:00 and took 152.07 s.
- Cluster: the session vCluster `pytest-02d2b201-ad62-4dbd-a1ee-2f029bca0b82` (container `vcluster.cp.pytest-02d2b201-ad62-4dbd-a1ee-2f029bca0b82`), created and removed by the session fixture.
- Image: `registry.opsmill.io/opsmill/styrmin:latest`, built by the session from the working tree with `styrmin-driver`.
- Result:

  ```text
  backend/tests/e2e/test_deploy_app.py::test_styrmin_driver_matches_helm_release[api-chromium] PASSED
  ================== 1 passed, 4 warnings in 152.07s (0:02:32) ===================
  ```

- What it shows:
  - SC-004: `styrmin-driver render driver/examples/simple-app --context <spec.context of the StyrminDeployment>` gave the `spec.values` of the deployment's HelmRelease.
  - FR-006: every key path of `spec.context` is in the output of `styrmin-driver context`, except the paths that come from the session's configuration.
  - FR-014: `docker run --rm <image> styrmin-driver check /styrmin/drivers/simple-app` exited with 0.
- Session configuration: the session cluster sets `fqdn_suffix`, `external_url_scheme`, `external_url_port`, `ingress_class`, `dedicated_ingress`, `runtime_class`, `standard_storage`, `fast_storage` and `external_dns_endpoints_type` (`backend/tests/e2e/conftest.py:1095-1116`); the environment sets none. So the real context holds `cluster.config.*` and `instance.config.*` keys that the example context does not have, and the FR-006 check leaves out the paths under `cluster.config`, `environment.config`, `deployment.config`, `instance.config`, the capabilities, `deployed_services`, the services of other deployments, and the per-component keys that configuration adds (research R-013, "Not known").

## Quickstart run (T056)

Run on 2026-10-28 from the clone, with `uv run`.

| Scenario | Result |
|----------|--------|
| 1. Eight example drivers | Seven exit with 0. `slurpit` exits with 1: `values.j2.yml:84` and `:89` read `services.slurpit`, which the driver does not declare. See "Open decision" below. |
| 2. Every error in one run | A copy of `simple-app` with `{{ parameters.admn_email }}` on line 12 and the upgrade action pointing to `upgrade_missing`: two errors (`driver.styrmin.yml:62` and `values.j2.yml:12`), exit code 1; exit code 0 after both fixes. |
| 3. Render with a context file | `context` on `generic-app` prints the context and one placeholder warning. Both renders exit with 0; `diff` of the two outputs shows only the image tag (`'0'` against `1.2.3`). A file with `parameterz` exits with 2 and names `parameterz`. |
| 4. Compare values | `diff` against the saved render: no output, exit code 0. With the context file: a unified diff of the image tag, exit code 1. |
| 5. Exit code 2 | A directory that does not exist, `--bogus`, and a base file that does not exist: exit code 2 each. |
| 6. From the image | Covered by the E2E node above (`docker run ... styrmin-driver check /styrmin/drivers/simple-app`, exit code 0). |
| 7. Time to a first render | `check` and `render` of `simple-app` together: 0.69 s (`/usr/bin/time -p`, `real`). |

## Open decision: the `slurpit` example driver

`driver/examples/slurpit/values.j2.yml` reads `services.slurpit.primary_fqdn` on lines 84 (`PORTAL_BASE_URL`) and 89 (the ingress host), and `driver/examples/slurpit/driver.styrmin.yml` declares no `spec.services`. On a deployment, both values render empty unless another deployment of the environment declares a service named `slurpit`. `styrmin-driver check` reports it, so SC-001 does not hold for `slurpit` until the driver changes. `python_sdk/tests/driver_format/test_check_examples.py` marks this case as an expected failure (`xfail`, `strict=True`). Changing the driver changes what it deploys, so the decision is the user's.

## Final checks (T055, T057)

Run on 2026-10-28 on the working tree with both pull requests' changes.

| Command | Result |
|---------|--------|
| `cd docs && pnpm install --frozen-lockfile && pnpm build` | `[SUCCESS] Generated static files in "build".` No CI job builds the docs; this build ran locally only. |
| `uv run invoke lint` (with `frontend/node_modules` installed) | exit code 0: ruff, ty, rumdl, yamllint (two warnings in files this change does not touch), GraphQL validation (282 files), generated types up to date |
| `uv run pytest tests --ignore=tests/e2e -q -n auto` (in `backend/`) | 5806 passed, 8 skipped, 1 failed: the same `test_send_report_returns_false_when_the_connection_is_refused`, which fails on a clean `HEAD` too |
| `uv run pytest -q python_sdk/tests` | 457 passed, 1 xfailed (`slurpit`, see "Open decision") |
| `uv run pytest -q cli/tests` | 416 passed |
| `uv lock --check` | passes |

## Fixes of the 8 critical review findings (2026-10-28)

The review of 2026-10-28 (five agents: code, tests, errors, types, comments) found 8 critical issues. The fixes and their tests:

| Finding | Fix | Tests |
|---------|-----|-------|
| 1. `context` failed on template errors | The context is built whenever `driver.styrmin.yml` is valid; `context` ignores the checks of `TEMPLATE_CHECKS` (`diagnostics.py`, `cli.py`) | `test_cli_exit_codes.py::test_context_ignores_every_template_error` (4 cases) |
| 2. Bad context or base files crashed with exit 1 | Files read as bytes and decoded as UTF-8; wrong shapes and validator errors become `ContextFileError` (`cli.py`, `example_context.py`) | `test_context_file.py` (not UTF-8, `app.helm` null or a string, invalid env var name), `test_diff.py::test_a_base_file_that_is_not_utf8_exits_with_2` |
| 3. Unreadable driver files and template runtime errors crashed | Driver files that cannot be read or are not UTF-8 are errors with their line; any render failure is an error with its template line; `main` exits with 2 on an unexpected exception | `test_check_errors.py` (template not UTF-8, unreadable, render failure), `test_rendering_check_mode.py::test_any_render_failure_is_a_result_with_its_line`, `test_cli_exit_codes.py::test_an_unexpected_exception_exits_with_2_as_an_internal_error` |
| 4. Undefined names in operations were missed | Operators bound again on `_CheckingUndefined`; the agent's wording (`'dict object'`) for fields without a value | `test_rendering_check_mode.py::test_uses_in_operations_calls_subscripts_and_comparisons_are_all_reported`, `::test_an_operation_on_a_field_without_a_value_fails_as_on_the_agent`, `::test_undefined_uses_found_before_a_render_failure_are_kept` |
| 5. `loop.previtem` was reported as undefined | Jinja's own undefined values render as on the agent | `test_rendering_check_mode.py::test_jinja_own_undefined_values_render_as_on_the_agent` |
| 6. The example version depended on the hash seed | Clauses read in written order (`example_context.py`) | `test_example_context.py::test_the_application_version_follows_the_written_order_in_every_process` (8 hash seeds) |
| 7. The syntax-error test did not check the line | Exact line and message asserted | `test_check_errors.py::test_template_syntax_error_names_the_file_and_the_line` (2 cases) |
| 8. The docs promised one-line messages and exit 2 | Reference page, contract, glossary and step 9 describe the behaviour: messages that take several lines, the full exit-code 2 list, the version order, `context` and the template | documentation lint, docs build |

Checks after the fixes, on the same working tree:

| Command | Result |
|---------|--------|
| `uv run invoke lint` | exit code 0 |
| `uv run pytest tests --ignore=tests/e2e -q -n auto` (in `backend/`) | 5806 passed, 8 skipped, 1 failed: the same `test_send_report_returns_false_when_the_connection_is_refused`, which fails on a clean `HEAD` too |
| `uv run pytest -q python_sdk/tests` | 480 passed, 1 xfailed (`slurpit`) |
| `uv run pytest -q cli/tests` | 416 passed |
| `uv lock --check` | passes |
| `sleep infinity \| uv run pytest "backend/tests/e2e/test_deploy_app.py::test_styrmin_driver_matches_helm_release[api-chromium]" -v -s --pdb -p no:cacheprovider` | `1 passed, 4 warnings in 213.00s`, ended 2026-10-28T15:38:46+01:00, session vCluster `pytest-f02eaa92-2ec4-44c5-8099-1488723b8a77`, image rebuilt from the working tree |
