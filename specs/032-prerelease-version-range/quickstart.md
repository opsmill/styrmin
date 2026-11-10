# Quickstart: validate the prerelease rule

**Spec**: [spec.md](../spec.md) | **Contract**: [contracts/refusal-messages.md](contracts/refusal-messages.md) | **Data model**: [data-model.md](data-model.md)

Run each check from the repository root. Every check names the requirement it proves.

## 1. Unit tests (FR-001, FR-002, FR-004, FR-005, FR-006, FR-007)

```bash
uv run pytest backend/tests/unit/services/test_version_range.py \
  backend/tests/unit/services/test_driver_version_resolution.py \
  backend/tests/unit/services/test_unsupported_version_message.py \
  backend/tests/unit/services/driver/test_default_version.py -v
```

Expected:

- The boundary table in the data model gives the listed verdict for each row.
- The picker, the pin check and the driver-load check give the same verdict as the shared check for each row.
- A refused request names the version, lists every range and does not contain the word "prerelease".
- `latest` behaves as the characterization test recorded before the change.

## 2. Existing suite (FR-007, SC-004)

```bash
uv run invoke format lint
uv run invoke test
```

Expected: lint exits 0 and no test that passed before fails. One test failed on untouched `develop` before this work according to PR #594's description (`test_send_report_returns_false_when_the_connection_is_refused`). Compare against `develop` before treating a failure as caused by this change.

## 3. End-to-end test (SC-001, FR-003)

Prerequisites: `docker` and `vcluster` on `PATH` (see `AGENTS.md`, "Debugging E2E Tests"). The fixtures create their own cluster, so `uv run invoke dev` is not needed.

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_deploy_app.py -k prerelease -v -s --pdb 2>&1 | tee /tmp/prerelease-e2e.log
```

Expected:

- The deployment of `0.2.0-beta.1` with the session `simple-app` driver (range `>=0.1,<1.0`, unchanged) is created and reaches running.
- The stored application version is `0.2.0-beta.1`.
- The upgrade to `0.2.0` is accepted.
- The request for `1.0.0b1` is refused with the ranges listed, and the deployment list is unchanged.
- Both the `[api-chromium]` and the `[ui-chromium]` variants pass, or the node is marked `api_only` with the reason found in research D6.

Record for the Constitution V evidence: the node id, the exact command, the ISO 8601 time of the passing run, the cluster id (kubeconfig path under `/tmp/pytest-of-*/pytest-*/`) and the verbatim `PASSED` line.

## 4. Manual check of the real scenario (SC-001, optional, not required for the done state)

Not verified by this feature's tests: a deployment of the real `infrahub` driver at `1.12.0b0`. If a cluster with the standard drivers is at hand:

```bash
styrminctl deployments create infrahub 1.12.0b0 <environment> --cluster <cluster>
```

Expected: the command exits 0. Before the change it exited 1 with `Version 1.12.0b0 is not supported by the application driver infrahub`.

## 5. Documentation and glossary (FR-008)

```bash
cd docs && pnpm build
```

Expected: the build passes. The page `docs/docs/drivers/creating-a-driver.md` has the section "Prereleases in `supported_versions`" with the rule, the ordering of a prerelease below its release and the range `>=1.12.0b0,<1.13`. `CONTEXT.md` has the rewritten "Prerelease" entry. `changelog/591.changed.md` states the new rule.

## 6. How the CLI and the UI show the message (research D7)

Request `2.0.0b1` once with `styrminctl` and once in the Deploy form. Record what each shows. A rendering problem is a separate issue.
