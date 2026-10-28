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

## E2E test of the move: load errors reach the client (2026-10-28)

The move adds no user-visible behaviour, but its risk is that a moved error stops reaching API clients: the GraphQL error extension (`backend/styrmin_backend/api/errors.py`) sends the message and code only for a `ServiceError`, and masks any other error as "An internal error occurred". This test loads two driver directories that a load refuses, from a `broken-drivers` repository of the session git server, and checks the code, the message and the metadata that the client receives, and that `styrmin-driver check` reports the same message.

- Node: `backend/tests/e2e/test_deploy_app.py::test_driver_load_errors_reach_the_client_with_the_message_of_styrmin_driver`, two cases (`missing-action`: `VALIDATION_ERROR`; `retired-filter`: `RETIRED_TEMPLATE_FILTER` with `filter: component_command`), `api_only`, shard `shard_general`.
- Fixtures: `backend/tests/e2e/fixtures/drivers/broken/{missing-action,retired-filter}/`, the `broken-drivers` repository added to the `git_server` fixture (`backend/tests/e2e/conftest.py`) and to the git server image (`backend/tests/e2e/fixtures/git-server/Dockerfile`). No deployment starts.
- Command: `sleep infinity | uv run pytest backend/tests/e2e/test_deploy_app.py -k "driver_load_errors and api-chromium" -v -s --pdb -p no:cacheprovider`
- First run: an error in the `git_server` fixture, `GitProtocolError: access denied or repository not exported: /broken-drivers.git`, because the git server image creates each bare repository it serves. The Dockerfile now creates `broken-drivers.git`.
- Second run: ended 2026-10-28T15:51:50+01:00, session vCluster `pytest-d1881941-656c-4605-8cbc-0c97686ca480`.

  ```text
  backend/tests/e2e/test_deploy_app.py::test_driver_load_errors_reach_the_client_with_the_message_of_styrmin_driver[api-chromium-missing-action-VALIDATION_ERROR-Missing entrypoint for action upgrade: upgrade_missing-metadata0] PASSED
  backend/tests/e2e/test_deploy_app.py::test_driver_load_errors_reach_the_client_with_the_message_of_styrmin_driver[api-chromium-retired-filter-RETIRED_TEMPLATE_FILTER-values.j2.yml line 2 calls the 'component_command' template filter, which was removed-metadata1] PASSED
  =========== 2 passed, 14 deselected, 4 warnings in 128.77s (0:02:08) ===========
  ```

## Dependency scan (2026-10-28)

- Command: `trivy fs --scanners vuln --format json --output <file> .`, in two clean worktrees: the branch at `7e12cd36` and `develop` at `8f450f69`. Clean worktrees, because the working checkout holds `.venv` and `node_modules` that the base checkout does not.
- Trivy 0.74.0; vulnerability database version 2, updated 2026-10-28 13:01:10 UTC.
- Targets in both: `uv.lock`, `backend/uv.lock`, `docs/pnpm-lock.yaml`, `frontend/pnpm-lock.yaml`.
- Findings: 194 on the branch, 194 on `develop`, 0 new (compared by `VulnerabilityID`, `PkgName` and `InstalledVersion`). The added dependencies `jinja2` 3.1.6 and `packaging` 25.0 were already in `uv.lock`.

## Code review of the branch (2026-10-28)

The repository's `code-review` skill ran in an agent that did not write the change, at high thoroughness, on the commits `f449e4ca` and `7e12cd36` on top of `develop` (`8f450f69`) and on the uncommitted E2E test of the move. It found 1 CRITICAL, 12 IMPORTANT and 29 MINOR findings.

| Finding | Resolution |
|---------|------------|
| CRITICAL: an FQDN suffix in a context file did not reach the service FQDNs (`host: None`) | Fixed: `apply_context_file` resolves the `config` of `cluster`, `environment` and `deployment` into `instance.config`, as the server does, and builds the service entries again from the merged context unless the file sets `services`. Tests: `test_context_file.py::test_an_fqdn_suffix_in_the_context_file_reaches_the_service_fqdns` (2 cases), `::test_services_set_by_the_context_file_are_kept`. |
| A missing action function at the wrong line when another action is invalid | Fixed: the YAML index of each action is kept. Test: `test_check_errors.py::test_a_missing_action_function_names_its_own_line_when_another_action_is_invalid`. |
| A load message changed in the move (it named the SDK module) | Fixed: the message names `DriverSpec()` without a module; ADR-089 records the change. Tests: two SC-003 cases and `test_a_driver_spec_file_that_is_not_a_mapping_gives_a_message_without_a_module_path`. |
| The new E2E test compared only the start of each message | Fixed: the whole message of `styrmin-driver`, migration guide included, must be in the server's message. |
| The template render is not sandboxed | Kept, documented: the agent renders the same way; the reference page says to run the command on trusted drivers or in an isolated job. A sandbox would reject templates that the agent accepts. |
| The placeholder warnings stayed when the context file set the value | Fixed. Test: `test_context_file.py::test_warnings_about_values_that_the_context_file_sets_are_left_out`. |
| An error in `driver.styrmin.yml` hid the template errors without a note | Fixed: a warning says that `values.j2.yml` was not rendered. Test: `test_check_errors.py::test_a_template_that_is_not_rendered_because_of_spec_errors_says_so`. |
| The YAML error of the rendered values gives a line of the rendered text | Kept: the message is the agent's message (FR-001). Showing the rendered text is a follow-up. |
| One pull request or two; conflicts with open PR #575 on `context/models/contexts.py` | Kept: a decision for the user. |
| `docs/docs/beta-status.md` listed #23 as "Coming next" | Fixed: moved to "Using application drivers". |
| `--version` prints the SDK version; the first image with the command is not named | Fixed in the docs: the reference page says that `--version` prints the SDK version and that images of 0.1.55 and earlier do not have the command. |
| Developer pages named the old backend paths | Fixed: `dev/knowledge/backend/data-models.md`, `hooks-and-actions.md` and `deployment-env-vars.md` name the SDK paths and say that the old paths re-export. |
| No follow-up issues exist | Kept: creating issues is the user's decision. |

The 29 MINOR findings are left as they are.

Checks after the fixes:

| Command | Result |
|---------|--------|
| `uv run invoke lint` | exit code 0 |
| `uv run pytest tests --ignore=tests/e2e -q -n auto` (in `backend/`) | 5809 passed, 8 skipped, 1 failed: the same telemetry timing test, which fails on a clean `HEAD` too |
| `uv run pytest -q python_sdk/tests` | 486 passed, 1 xfailed (`slurpit`) |
| `uv run pytest -q cli/tests` | 416 passed |
| `sleep infinity \| uv run pytest backend/tests/e2e/test_deploy_app.py -k "styrmin_driver and api-chromium" -v -s --pdb -p no:cacheprovider` | `3 passed, 13 deselected, 4 warnings in 251.70s`, ended 2026-10-28T16:26:55+01:00, session vCluster `pytest-580b9c82-3ef4-4991-a354-8dd69bac0618`: `test_styrmin_driver_matches_helm_release` and the two cases of `test_driver_load_errors_reach_the_client_with_the_message_of_styrmin_driver` |
