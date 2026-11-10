# Quickstart results

**Quickstart**: [quickstart.md](quickstart.md) | **E2E evidence**: [e2e-evidence.md](e2e-evidence.md)

Each row is one step of the quickstart, run once from the repository root on branch `sas-591-prerelease-spec`. Logs are in the scratchpad log directory (not committed).

| Step | What it expects | Command run | Observed result |
| --- | --- | --- | --- |
| 1. Unit tests | The four test files pass: boundary table, parity of picker, pin check and driver-load check, refusal text lists every range and has no word "prerelease", `latest` unchanged | `uv run pytest backend/tests/unit/services/test_version_range.py backend/tests/unit/services/test_driver_version_resolution.py backend/tests/unit/services/test_unsupported_version_message.py backend/tests/unit/services/driver/test_default_version.py -q` | `70 passed in 0.24s`. The quickstart command with `-v` was not used; `-q` was used. The individual assertions were not re-read for this step. |
| 2. Existing suite | Lint exits 0. No test that passed before fails | `uv run invoke format lint` (after `cd frontend && pnpm install --frozen-lockfile`), then `uv run invoke test` | Lint: exit 0. The ruff checks reported `All checks passed!`; `282/282 .graphql files passed validation`; the step "Validating generated types are up to date" ended without an error message. Suite: `1 failed, 5902 passed, 8 skipped, 41 warnings in 314.15s (0:05:14)`. The one failure is `tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused` (`assert 7.80293000000529 < 2`), the timing test that the baseline of task T002 also recorded as failing, and that PR #594 reports as failing on `develop`. No comparison run on `develop` was made in this chunk. |
| 3. End-to-end test | The node passes in `[api-chromium]` and `[ui-chromium]` | Not re-run, by instruction. Evidence from [e2e-evidence.md](e2e-evidence.md) | `1 passed ... in 313.40s` (api) and `1 passed ... in 307.14s` (ui), both quoted from the logs. The links between the logged runs and the committed node are listed under "Not verified" in that file. The steps inside the node (deployment of `0.2.0-beta.1`, upgrade to `0.2.0`, refusal of `1.0.0b1`) were not read from the logs: a passing run shows no per-step lines. |
| 4. Real `infrahub` driver at `1.12.0b0` | Optional. `styrminctl deployments create infrahub 1.12.0b0 <environment> --cluster <cluster>` exits 0 | Not run | Not verified. No cluster with the standard drivers was available in this chunk. |
| 5. Documentation and glossary | `pnpm build` passes. The page has the section "Prereleases in `supported_versions`" with the rule, the ordering and the range `>=1.12.0b0,<1.13`. `CONTEXT.md` has the rewritten entry. `changelog/591.changed.md` states the rule | `cd docs && pnpm install --frozen-lockfile && pnpm build` | Build exit 0: `[SUCCESS] Generated static files in "build".` The heading is at `docs/docs/drivers/creating-a-driver.md:229` (`#### Prereleases in \`supported_versions\``). The built page `docs/build/docs/drivers/creating-a-driver/index.html` contains `id="prereleases-in-supported_versions"`, and `docs/docs/drivers/loading-drivers.md:673` links to it. The text of the section (lines 229 to 272) names the range `>=1.12.0b0,<1.13` at lines 256 to 257. `CONTEXT.md:137` has the entry "Prerelease (application version)". `changelog/591.changed.md` states the rule. |
| 6. How the CLI and the UI show the message | Record what each shows for `2.0.0b1`. A rendering defect is a separate issue | No running stack. CLI: a throwaway script in the scratchpad, `cli_refusal_check.py`, run with `uv run python`. UI: the log `e2e-prerelease-ui.log` and the code in `frontend/src/pages/deployments/DeployFormPage.tsx` | See the two paragraphs below. The new message with the list of ranges was not displayed by the CLI or the UI against a real server. |

## Step 6 in detail

CLI. `styrminctl deployments create` runs inside `styrmin_error_handler` (`cli/src/styrminctl/output.py`, line 75). It catches `StyrminError` and `ValueError` (the SDK's `StyrminAPIError` is a subclass of `StyrminError`), prints `Error: <message>` through `print_error`, and exits with code 1. The throwaway script mocked the SDK so that `deployments.create` raised `StyrminAPIError` with the message of message 1 in [contracts/refusal-messages.md](contracts/refusal-messages.md) for `2.0.0b1`. The output was:

```text
Error: Version 2.0.0b1 is not supported by the application driver infrahub
(supported ranges: >=1.5,<2.0).
EXIT CODE: 1
```

The line break comes from the Rich console, which wraps at 80 columns when the output is not a terminal. The text is complete. This shows how the CLI prints an error that carries this message. It does not show that a real server sends this message to the CLI, or how a terminal of another width wraps it.

UI. The Deploy form catches a failed mutation, stores `err.message` and renders it in an alert titled "Deployment failed" (`DeployFormPage.tsx`, lines 134 to 135 and 275 to 280). In the first failing run (`e2e-prerelease-ui.log`, lines 563 and 564) the form showed:

```text
Deployment failed
Version 0.2.0-beta.1 is not supported by driver version 22db5022-d01a-4da2-b621-557f53525c70 (supports >=0.1,<1.0).
```

That text is the old message of a pinned version, without the list of ranges, for another version string. It proves that the form displays the full text of the server's error. It does not prove how the new, longer message looks in the form. The Playwright MCP server was not used.

No rendering defect was seen in either check.
