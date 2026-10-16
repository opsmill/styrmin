# Pull Request Notes: helm-controller Runs with Helm v4 Defaults

Notes for the pull request description of spec 024 ([#435](https://github.com/opsmill/styrmin/issues/435)). The repository has no `.github/PULL_REQUEST_TEMPLATE.md`, so the sections below follow the points that tasks.md T034 lists. Links to files on the branch use the branch name `fac/helm-v4-end3k`.

Suggested title: `feat(agent): run helm-controller with Helm v4 defaults (#435)`

## Summary: helm-controller runs without the UseHelm3Defaults gate

The agent chart ran FluxCD's helm-controller v1.6.5 with `--feature-gates=UseHelm3Defaults=true` ([#434](https://github.com/opsmill/styrmin/pull/434)), so every deployment was installed and upgraded with Helm v3's client-side apply and health checks. It is not known whether or when FluxCD removes the gate. This change runs helm-controller without the gate, so FluxCD's Helm v4 defaults apply to every HelmRelease, and changes Styrmin's label patch so that a chart resource without labels, such as a Helm hook, no longer fails the render. The operator's rules and the task results that users view do not change.

Not decided: whether `Stalled` and the operator's readiness timeout keep unit-test coverage only (see [Question for the maintainer](#question-for-the-maintainer-e2e-coverage-of-stalled-and-the-readiness-timeout)).

## What changes for operators

- A deployment created after the agent upgrade is installed with server-side apply. helm-controller is the field manager and forces field ownership conflicts, so at each upgrade a field that the chart sets returns to the chart's value, also when `kubectl` or a driver action changed it. The upgrade does not fail.
- A deployment created before the agent upgrade keeps client-side apply on its later upgrades and rollbacks, because each upgrade and rollback uses the apply method of the release's previous install or upgrade.
- Installs and upgrades wait for the chart's resources with kstatus. When pods cannot pull their image, FluxCD still waits the full HelmRelease timeout, and the failed step still names the pods' reason, such as `ImagePullBackOff`.
- To go back to Helm v3's behaviour, downgrade the agent chart to a release that runs helm-controller with the gate. Deployments created while the gate was off keep server-side apply on their later upgrades and rollbacks.

## What changes for driver authors

- Helm hooks of a driver's chart, the resources annotated `helm.sh/hook`, receive Styrmin's post-render patches:
  - Styrmin's labels reach every hook, also a hook without `metadata.labels`.
  - The deployment's scheduling settings reach hook `Job`, `CronJob`, `Deployment`, `StatefulSet`, `DaemonSet` and `ReplicaSet` resources whose own `metadata.labels` carry a component's first identifier label, or every hook of these kinds when the driver declares no components.
  - Env var, image and container overrides, and the component-container guard, reach a hook only when it is a `Deployment` or `StatefulSet` that matches a component.
- A chart `Deployment` with `progressDeadlineSeconds` below 270 seconds makes FluxCD fail a change and roll the release back before Styrmin reads why the pods are not ready, so the failed step shows FluxCD's `ProgressDeadlineExceeded` failure instead of the pods' reason.
- On a deployment installed with server-side apply, a field of a chart resource that a driver action changes directly returns to the chart's value at the next upgrade.

The pages that state this: [Operator and CRDs](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/docs/docs/concepts-and-architecture/operator-and-crds.md), [Creating a driver](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/docs/docs/drivers/creating-a-driver.md) (Step 1, "The component container", Step 7), and the docs-site [changelog](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/docs/docs/changelog.md). The decisions are in [ADR-072](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/dev/adr/0072-helm-v4-defaults-releases-keep-apply-method.md). The towncrier fragment is [`changelog/435.changed.md`](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/changelog/435.changed.md).

## High-risk areas touched

- Agent chart: `helm/agent/templates/helm-controller/deployment.yaml` no longer passes the gate. The integration fixture copy `backend/tests/integration/fixtures/templates/helm-controller/deployment.yaml` changes the same way.
- helm-controller flags: the change of defaults applies to every HelmRelease that the operator writes, including internal deployments such as the environment's ingress controller.
- Post-render patches: the patch that adds Styrmin's labels to every resource (`build_target_for_label_patches` in `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`) is now the strategic-merge `MetadataLabelsMergePatch` (`.../resources/blocks/patches.py`) instead of a JSON patch. It changes `spec.postRenderers` of every HelmRelease that the operator writes from this release, and a post-renderers change makes helm-controller upgrade the release (see [Not checked](#not-checked-whether-an-agent-image-upgrade-upgrades-existing-releases)).

The GraphQL API, SDK, CLI, frontend, database schema and error types do not change (spec FR-012).

## Evidence

- [e2e-evidence.md](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/specs/024-helm-v4-defaults/e2e-evidence.md): four local E2E sessions with their commands, times, vclusters and `PASSED` lines; FluxCD's state during a rollback; the check that the operator's rules need no change; the walk-through of quickstart.md §1 to §5.
- [agent-upgrade-check.md](https://github.com/opsmill/styrmin/blob/fac/helm-v4-end3k/specs/024-helm-v4-defaults/agent-upgrade-check.md): the manual check of an agent chart upgrade from the chart with the gate to this branch's chart on a disposable vcluster.

## Checks run

| Check | Time (UTC, 2026-10-16) | Result |
| --- | --- | --- |
| `uv run invoke format lint` | 11:33:21 | Passed |
| `uv run invoke test` (backend unit and integration tests, without E2E) | 11:28:36 to 11:31:31 | `4498 passed, 3 skipped, 31 warnings` |
| `uv run pytest backend/tests/integration -q` | 11:31:49 to 11:32:20 | `37 passed` |
| `uv run pytest backend/tests/e2e --collect-only -q` | 11:30:29 | `195 tests collected`; `enforce_shard_markers` found one shard marker on every `ci` test |
| Docs site build in `node:22-slim` (`pnpm build`) | 11:30:46 to 11:31:02 | `[SUCCESS] Generated static files in "build".`, no broken link |
| E2E `shard_task_steps`, API variant (run 1) | 08:41 to 08:50 | `5 passed` |
| E2E `shard_configuration`, API variant (run 2) | 08:53 to 09:07 | `8 passed, 12 skipped` (the skipped tests are `ui_only`) |
| E2E `shard_compute`, API variant (run 3) | 09:22 to 09:32 | `7 passed, 1 skipped` (`ui_only`) |
| E2E `shard_compute`, UI variant (run 4) | 09:36 to 09:40 | `4 passed, 4 skipped` (`api_only`) |
| Agent chart upgrade check | 11:07 to 11:13 | All expected results met |
| `grep` for `UseHelm3Defaults` outside the specs | 11:29 | Only text that describes the old behaviour on purpose, FluxCD's own CRD field descriptions and the unit test that asserts the gate is gone |

Run 4 is the second UI session: the first failed `test_edit_cluster_config_from_detail_page[ui-chromium]`, a known flake of that test on this host that does not use the changed driver or any Helm hook, and the rerun passed unchanged.

The full E2E suite, both variants as marked, runs in CI on this pull request. The backup and clone shards (`shard_backup`, `shard_env_backup`) were not run locally; their CI run shows whether restored Helm v4 release Secrets still work.

## The api cell of shard_configuration was run locally

CI excludes the `api` cell of `shard_configuration`, so its `api_only` tests, among them the component-container guard test `test_misnamed_container_never_added`, run only locally. Run 2 in e2e-evidence.md is that cell: all 8 API tests passed with the agent chart without the gate, and the guard failed the deployment with `COMPONENT_CONTAINER_NOT_FOUND` as before.

## Not checked: whether an agent image upgrade upgrades existing releases

The agent upgrade check used the same server and agent image (`helmv4-f752856a`) before and after the chart upgrade, so it covers the chart change only. In that check, helm-controller found both existing releases in sync, created no new release revision, and restarted no pod. The next change to the deployment created release v2, which kept client-side apply.

A real upgrade from an earlier release also replaces the agent image. That image changes the label patch, and so `spec.postRenderers`, in each HelmRelease that the operator writes, and a post-renderers change makes helm-controller upgrade the release. The message of commit `8a5d3b61`, which changes the label patch, states that the HelmRelease of an existing deployment changes only when the operator renders it again: for a new rollout, or when it resumes a deployment that is not `Ready`. This was not checked. So it is not known whether an agent restart on the new image upgrades the releases of existing deployments right away, which would restart their pods. Such an upgrade would keep client-side apply.

## Question for the maintainer: E2E coverage of Stalled and the readiness timeout

AGENTS.md asks for confirmation before E2E coverage is left out. Can `Stalled` and the operator's readiness timeout keep unit-test coverage only (`backend/tests/unit/test_styrmin_deployment_timer.py`, `backend/tests/unit/steps/test_operator_history_failures.py`, with recorded FluxCD states)?

The reasons, from the spec Clarifications and critique P3:

- This change does not change any operator rule.
- Reaching `Stalled` in E2E needs FluxCD to use all its retries, and reaching the readiness timeout needs the 270-second timeout to pass, in a session that other tests share.
- In the local runs, `Stalled=True` did not occur. The readiness timeout did occur in run 1 (`Deployment did not reach Ready within 210s`, with the E2E fixture's 210-second timeout) before FluxCD's rollback, but no E2E test asserts it.
