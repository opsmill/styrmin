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
| 2. Several errors in one run | A copy of `simple-app` with `{{ parameters.admn_email }}` on line 12 and the upgrade action pointing to `upgrade_missing`: two errors (`driver.styrmin.yml:62` and `values.j2.yml:12`), exit code 1; exit code 0 after both fixes. |
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

## Code reviews of the commit that states the limits of `check`

The `code-review` skill ran in an agent that did not write the change, at high effort, on each version of the commit that states the limits of `check`, and on each commit after it. The versions `38eed3d4`, `4cb12cff` and `fd682a75` were replaced before any push; `fbb24f78` and `9236b94b` replace `fd682a75`.

| Diff reviewed | Findings | Changes made in |
|---------------|----------|-----------------|
| `ffb001c3..38eed3d4` | 3 CRITICAL, 3 IMPORTANT, 8 MINOR | `4cb12cff` |
| `ffb001c3..4cb12cff` | 5 CRITICAL, 12 IMPORTANT, 12 MINOR | `fd682a75` |
| `ffb001c3..fd682a75` | 3 CRITICAL, 8 IMPORTANT, 11 MINOR | `fbb24f78`, `9236b94b` |
| `ffb001c3..9236b94b` | 2 CRITICAL, 3 IMPORTANT, 19 MINOR | `3e8c8283` |
| `9236b94b..3e8c8283` | 3 CRITICAL, 5 IMPORTANT, 11 MINOR | `3b406375` |
| `3e8c8283..3b406375` | 3 CRITICAL, 3 IMPORTANT, 12 MINOR | the commit that adds this row |

Each review read the text that the review before it led to, and found statements in it that were false. The findings of the review of `9236b94b`, and what changed in `3e8c8283`:

| Finding | Resolution |
|---------|------------|
| CRITICAL: step 9 of the driver guide said that the server renders an undefined variable as an empty string, apart from a few filters. `{{ x + 1 }}`, `{{ x \| int }}` and other uses make the server's render fail. | Fixed: the reference page and the guide say that the server renders it as an empty string when the template writes it out, and that some other uses make the render fail with a message that gives no line. |
| CRITICAL: `abs`, `round` and `range()` on an undefined variable stopped the check render with a `TypeError` that named the internal class `CheckingUndefined`, not the variable, so the variables after it were not checked. | Fixed: the check render makes each filter and test record an undefined variable passed to it, apart from `default()` and the `defined` and `undefined` tests, and then goes on with an empty value. `range()`, a list index, and a list or dict that the template writes out record it too. A field of the context model without a value fails with the agent's message. Tests: `test_rendering_check_mode.py::test_an_undefined_variable_passed_to_a_filter_a_test_or_a_function_is_reported_and_the_render_goes_on` (15 cases in `3e8c8283`), `::test_a_retired_filter_given_an_undefined_variable_still_fails_with_its_error`, `::test_filters_on_fields_without_a_value_render_or_fail_as_on_the_agent`. 13 of them fail without the change. |
| IMPORTANT: the narrowing of the brief's FR-009, from every error to more errors than a load, is not confirmed. | Kept: a decision for the author of the brief and the reviewer. |
| IMPORTANT: FR-009, R-015 and the docstring of `run_checks` said that every check runs, but some checks run only when another passes. | Fixed: they say that each check that can run does, and what each check needs. |
| IMPORTANT: a test such as `is none` or `is string` on an undefined variable was false, with no error. | Fixed by the change of the second CRITICAL finding. |

MINOR findings of that review fixed: FR-009 gives examples of what `check` reports; the changelog says "can report more errors"; the dates of the clarifications; the R-015 heading; the reference page no longer describes the server's output of `items`, `tojson`, `pprint` and the filters that return a generator; `indent` on an undefined variable no longer adds a second error; a list index no longer records a second use; `map` and `select` on an undefined variable are reported; the page says that a variable stored with `{% set %}` or passed to a macro is reported at the line that uses it, and that a macro the template never calls is not checked; the wrap of step 9.

MINOR findings of that review left as they are:

- The reference page does not say that `check` reports every invalid field of `driver.styrmin.yml`, because the review of `38eed3d4` found cases where it does not, such as an invalid environment variable name.
- No success criterion measures how many more errors `check` reports than a load.
- `tojson` records the undefined variables of a dict in the order of its keys, not of the template. They share the line.
- A passing `check` does not say that some branches were not rendered.
- The message for a missing `actions.py` does not give the next step that the reference page gives.
- A YAML syntax error in `driver.styrmin.yml` skips the checks of `actions.py` with no warning.

The findings of the review of `3e8c8283`, and what changed in `3b406375`. 12 of the new tests fail with the `rendering.py` of `3e8c8283`.

| Finding | Resolution |
|---------|------------|
| CRITICAL: the reference page, FR-007 and a docstring said that each use of an undefined variable is an error. A method call such as `'abc'.startswith(x)` stopped the render with a `TypeError` that named an internal class, and `{'k': 1}.get(x)`, `x in s`, `[x] \| length` and `{% if [x] %}` gave no error. | Fixed: a function or a method call records an undefined variable passed to it, and the render goes on after the call fails. The page, FR-007, R-003 and the docstrings say which uses are reported, and give examples of uses that are not: `parameters.x in parameters`, `{% if [parameters.x] %}` and `[parameters.x] \| length`. A slice with an undefined bound is reported and stops the render. Tests: `test_rendering_check_mode.py::test_an_undefined_variable_passed_to_a_filter_a_test_or_a_function_is_reported_and_the_render_goes_on` (5 new cases), `::test_a_slice_with_an_undefined_variable_is_reported_and_fails_as_on_the_agent`. |
| CRITICAL: step 9 of the guide gave two outcomes on the server, but some uses give another value with no error, such as `0` for `\| length` or false for `is none`. | Fixed: step 9 and the reference page say that the server renders it as an empty string or another value with no message, or fails with a message that gives no line. The page gives examples of each. |
| CRITICAL: the changelog, the spec (its context, a clarification and FR-016) and the plan said that the server renders an undefined variable as an empty string, with no exception. | Fixed: they say it of a variable that the template writes out, or say that the agent's render does not change. |
| IMPORTANT: after an undefined variable, a filter gave an empty value and a test gave false, so an `if` could take another branch than the agent's, and the agent's branch was not checked. This was new in `3e8c8283`. | Fixed: each filter, test and call gives its own result, and an empty value only when it fails. An undefined list index or dict key gives an undefined value, as on the agent. Test: `::test_after_an_undefined_variable_the_render_takes_the_branch_of_the_agent` (7 cases). |
| IMPORTANT: no test compared the two renders for filters that Jinja passes the context or the environment to. | Fixed: `::test_filters_that_take_the_context_or_the_environment_give_the_values_of_the_agent` (15 cases). 14 of them fail when the filter wrapper does not keep `jinja_pass_arg` (`functools.wraps` removed). |
| IMPORTANT: the reference page no longer said that some uses give a value with no error on the server. | Fixed by the change of the second CRITICAL finding. |
| IMPORTANT: the page did not say that a use of a field without a value fails as on the server where the server's render fails, such as `\| abs`. | Fixed: the page says so, with `instance.config.fqdn_suffix + 1` as the example. |
| IMPORTANT: the narrowing of FR-009 is not confirmed. | Kept: a decision for the author of the brief and the reviewer. |

MINOR findings of that review fixed: the wording of this section about which findings are fixed; `{{ s[x] }}` on a dict no longer records a second use named `<dict>.`; a comment says that no message shows the name of the empty value after a filter or a call.

MINOR findings of that review left as they are:

- A use inside a macro, or of a variable stored with `{% set %}`, is reported at the line that uses it, which does not hold the variable's name. The reference page says so.
- The undefined classes of the check render are named `SilentUndefined`, so `repr()` of the class does not show which one it is.
- `check` gives the same message for a use that makes the server's render fail and for one that gives a value with no error.
- The message `undefined variable 'parameters.admn_email'` gives no next step.
- The check render is slower than before on a template with many filter calls: 0.014 s against 0.005 s for about 80,000 calls, as measured by the reviewer before this change. Not measured after it.
- No success criterion measures the feature.
- This file records each review round.
- The commit `3e8c8283` has the type `fix(sdk)`, and about half of its diff is documentation.

The review of `3b406375` found that the check render still took other branches than the agent's render, and that the call wrapper of `3b406375` hid errors. The cause of these findings, and of most findings of the reviews before, is one design choice: after a use that makes the agent's render fail, the check render went on with a value of its own. The author of the brief chose on 2026-10-29 that the check render renders as the agent's ([spec, clarifications of 2026-10-29](spec.md#session-2026-10-29-reviews-of-the-documentation-of-check)), and confirmed the narrowing of FR-009 on the same day. The findings of the review of `3b406375`, and what changed in the commit that adds the last row of the table above. 26 of the 88 tests of `test_rendering_check_mode.py` fail with the `rendering.py` of `3b406375`.

| Finding | Resolution |
|---------|------------|
| CRITICAL: the check render took another branch than the agent's render for a name read on an undefined variable (`{% if parameters.x.y is string %}`, `is defined`, `\| pprint`), and for an undefined variable compared with a field without a value. The `pprint` case was new in `3b406375`. The commit message, a docstring, R-003 and this file said that the branch is the agent's. | Fixed: the undefined values of the check render are the agent's `SilentUndefined`, which also record their uses. A name read on one gives the agent's empty string. Tests: `test_rendering_check_mode.py::test_after_an_undefined_variable_the_render_takes_the_branch_of_the_agent` (6 new cases). |
| CRITICAL: the plan, the reference page, FR-009, step 9 and two docstrings still said that `check` reports each undefined variable that the render reaches, and the commit message of `3b406375` said they no longer did. | Fixed: they say that `check` reports the undefined variables that its render finds. |
| CRITICAL: an error inside a call that also receives an undefined variable was hidden, such as a removed filter or `"{}{}".format(x)`. New in `3b406375`. | Fixed: the wrappers record, then call the filter, test or function, and do not catch its errors. Tests: `::test_an_error_in_a_call_that_receives_an_undefined_variable_is_not_hidden`, and the `format` case of `::test_a_use_that_the_agent_fails_on_is_reported_and_fails_as_on_the_agent`. |
| IMPORTANT: a slice with an undefined bound stopped the render with a message that is not the agent's. New in `3b406375`. | Fixed: it fails with the agent's message. The use is not recorded, and the reference page says so. Test: `::test_a_slice_with_an_undefined_bound_is_not_reported_and_fails_as_on_the_agent`. |
| IMPORTANT: a key that is a field without a value, or one of Jinja's own undefined values, was reported with a made-up name, such as `components.`. | Fixed: it is not recorded. Test: `::test_a_key_or_a_name_read_on_a_field_without_a_value_is_not_reported` (4 cases). |
| IMPORTANT: `{{ parameters.image.split(":")[0] }}` gave a second error named `<str>.0`. | Fixed: the render fails as on the agent, with `'str' object is not callable`, and reports `parameters.image` once. |

MINOR findings of that review fixed: `__int__`, `__float__` and `<` on an undefined variable fail as on the agent; a name that starts with `_` read on an undefined variable gives the agent's empty string; the reference page names `parameters.get('x')` among the uses that are not reported; line 16 of the spec gives the three results on the server; the decision of R-003 no longer says that the render records each use instead of failing; the narrowing of FR-009 is confirmed.

MINOR findings of that review left as they are:

- The case `{% if X == '' %}` of the branch test also passes with the module of `3e8c8283`. It stays as a guard.
- A missing name of a defined value is reported as `<int>.value`, and the reference page does not explain this form.
- The last sentence of `changelog/23.added.md` describes the server.
- The speed of the check render was not measured after this change. The reviewer measured 0.0349 s on `3b406375` against 0.0088 s for the agent, for 40,000 filter calls and 20,000 method calls.
- A parameter named `values`, `items`, `keys` or `get` is hidden by the method of the mapping, as on the agent.
- The limits of `check` are described on the reference page, and the spec and the research repeat parts of them.

Checks after the fixes, on the working tree of the commit that adds the last row of the table of reviews:

| Command | Result |
|---------|--------|
| `uv run invoke lint` | exit code 0 |
| `uv run pytest tests --ignore=tests/e2e -q -n auto` (in `backend/`) | 5809 passed, 8 skipped, 1 failed: the telemetry timing test of the first table, which failed there on a clean checkout too. Not run again on a clean checkout. |
| `uv run pytest -q python_sdk/tests` | 556 passed, 1 xfailed (`slurpit`) |
| `uv run pytest -q cli/tests` | 416 passed |
| `cd docs && pnpm build` | `[SUCCESS] Generated static files in "build".` |
| `sleep infinity \| uv run pytest backend/tests/e2e/test_deploy_app.py -k "styrmin_driver and api-chromium" -v -s --pdb -p no:cacheprovider` | `3 passed, 13 deselected, 4 warnings in 158.92s`, ended 2026-10-29T13:34:57+01:00, session vCluster `pytest-1b0864de-c5e9-4e0c-b8a6-03d555dbb807`, image built from the working tree: `test_styrmin_driver_matches_helm_release` and the two cases of `test_driver_load_errors_reach_the_client_with_the_message_of_styrmin_driver` |
