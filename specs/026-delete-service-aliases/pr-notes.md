# Pull Request Notes: Deleting a Deployment Deletes Its Service Aliases

Notes for the pull request description of spec 026 ([#503](https://github.com/opsmill/styrmin/issues/503)). Links to files on the branch use the branch name `fac/services-cleanup-zk1ti`.

Suggested title: `fix(operator): delete a deployment's service aliases when it is deleted (#503)`

## Summary: deleting a deployment deletes its service aliases in the other namespaces

When a user deleted a deployment, the service aliases of its services stayed in the namespaces of the other deployments of its environment ([#503](https://github.com/opsmill/styrmin/issues/503)). A service alias is the `ExternalName` Service that Styrmin writes in each peer's namespace, so that the peer can reach a service by its short name. This change deletes those aliases and stops the flows of other deployments from writing them again during the deletion:

- The operator's teardown has a new first step. It deletes the deployment's aliases in all namespaces before it requests the deletion of the deployment's namespace. It finds an alias by the label `styrmin.io/deployment-id`, or, for an alias without that label, by the namespace that `spec.externalName` points into.
- The alias flow that a create, update or upgrade of another deployment runs reads the cluster before and after its writes:
  - it writes no alias of a deployment whose deletion was requested, and writes nothing into that deployment's namespace;
  - it deletes an alias of that deployment that it wrote just before it could read the request;
  - it skips a namespace that does not exist or is being deleted, and the step does not fail;
  - it no longer creates any namespace;
  - it reads the other deployments' services from the server when it runs, because a flow's context lists no deployment requested after it. The alias step that runs last therefore writes the aliases between two deployments requested one after the other.
- Deleting an alias is best-effort, like the rest of the teardown. A failure is logged, the deletion continues to `DELETED`, and the alias can stay.

The change does not delete these aliases:

- aliases left by deletions made before this version;
- an alias whose deletion failed, which the operator logs;
- aliases of a deployment whose namespace is deleted without a deletion request, by a restore or with `kubectl delete namespace` (FR-017);
- aliases of a StyrminDeployment annotated `styrmin.io/skip-teardown`, which a cross-target restore sets on its copy of the source's StyrminDeployment;
- an alias that a flow writes after the delete handler's teardown listed the aliases and before the StyrminDeployment is removed (FR-007).

The changelog fragment [`changelog/503.fixed.md`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/changelog/503.fixed.md) names each case and links the new "Service aliases" section of [`ingress-and-networking.md`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/docs/docs/concepts-and-architecture/ingress-and-networking.md), which shows how to find and delete them. A deployment created or changed while a peer is being restored gets no aliases to that peer until a later change of either deployment; [`backups-and-restores.md`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/docs/docs/concepts-and-architecture/backups-and-restores.md) describes this and how to recover.

Driver templates of other deployments still see a `DELETING` deployment's services until it reaches `DELETED`, as before.

Review fixes (2026-10-17): the flow's second read counts an owner only under the operator teardown's rule, a `spec.deletionRequested` flag or a `deletionTimestamp` while the namespace exists and is not `Terminating` (rule A), so a restore's namespace deletion no longer makes a flow delete the alias it has just written; and the flow deletes every alias it wrote of a deleted owner, whatever namespace holds it (rule B). With rule A, an alias written after the delete handler's teardown listed the aliases, and before the StyrminDeployment was removed, can remain (research R-004).

Review fixes of PR #516 (2026-10-17):

- The alias step reads the environment's services from the server (FR-018, research R-012). It replaces the 60-second wait for a missing namespace of commit `c4fd1534`, which CI run [39030125607](https://github.com/opsmill/styrmin/actions/runs/39030125607) prompted.
- The teardown lists the aliases with two label selectors and deletes each with the `resourceVersion` of the listing.
- The alias labels and rules, and the StyrminDeployment read, move to modules that import no Prefect code. The operator and the flow's second read call the same deletion rule.
- The flow reads at most 10 namespaces at the same time.

The maintainer confirmed FR-017 and accepted the FR-007 exception (spec, Session 2026-10-17). Not decided: the unit-test question below.

## High-risk areas touched

The change touches the operator's teardown and an agent flow that writes into the namespaces of other deployments:

- Operator teardown, in [`backend/styrmin_backend/operator/handlers/styrmin_deployment.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/styrmin_backend/operator/handlers/styrmin_deployment.py): the new `_delete_service_aliases` runs first in `_teardown_owned_resources`, on both deletion paths, and deletes Services in namespaces other than the deleted deployment's own. Its guards:
  - it acts only when the StyrminDeployment's namespace is `styrmin-<spec.deploymentId>`, so the copy of a source's StyrminDeployment that a cross-target restore deletes deletes none of the running source's aliases (research R-001);
  - on the delete handler path without `spec.deletionRequested`, it acts only when the namespace exists and is not `Terminating` (FR-017);
  - the skip-teardown branch stays first, so an annotated StyrminDeployment deletes no alias.
- Alias flow, in [`backend/styrmin_backend/agent/tasks/service_aliases.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/styrmin_backend/agent/tasks/service_aliases.py): `apply_service_aliases` reads the Namespace and the StyrminDeployment of each namespace it writes into or points into, before and after its writes. It no longer has the `namespace_labels` parameter or the loop that created namespaces; the four callers in `orchestration.py` changed with it.
- The alias step now calls the GraphQL API (`environmentServices`) with the flow's action token, in [`agent/tasks/environment_services.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/styrmin_backend/agent/tasks/environment_services.py). When the call fails, the step uses the context's list, as before.
- Kubernetes primitives, in [`backend/styrmin_backend/agent/service/kubernetes/primitives.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/styrmin_backend/agent/service/kubernetes/primitives.py): new `get_namespace`, `apply_service` and `is_namespace_gone_error`. The `Service` branch of `apply_kubernetes_resource` now calls `apply_service`, so every Service that the operator writes through it goes through that function. The behaviour is the same as before: create, then replace on 409.

The GraphQL API, SDK, CLI, frontend, database schema and Helm charts do not change.

## Evidence

[e2e-evidence.md](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/specs/026-delete-service-aliases/e2e-evidence.md) records four local sessions of `backend/tests/e2e/test_service_discovery.py`, the last one after the review fixes, with their commands, times, vclusters and `PASSED` lines, the agent log of each deletion of `intent`, and the walk-through of [quickstart.md](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/specs/026-delete-service-aliases/quickstart.md), including the two `kubectl` checks in all namespaces.

## Checks run

| Check | Time (UTC, 2026-10-16) | Result |
| --- | --- | --- |
| `uv run invoke format lint` | finished 23:47:04 | Passed, no file changed. yamllint printed two warnings for files this change does not touch (`driver/examples/infrahub-mcp/driver.styrmin.yml`, `.specify/workflows/speckit/workflow.yml`) |
| `uv run invoke test` (backend unit, functional and integration tests, without E2E) | 23:47:27 to 23:50:34 | `4980 passed, 3 skipped, 35 warnings` |
| Docs site build in `node:22-slim` (`pnpm build`), for the change to `docs/docs/drivers/generic-app.md` | 23:47:23 to 23:47:39 | `[SUCCESS] Generated static files in "build".` |
| quickstart.md unit tests (5 files) | 23:57:55 to 23:57:57 | `85 passed` |
| E2E `shard_general` module, API variant (task T015) | 23:36:09 to 23:38:38 | `3 passed, 3 deselected` |
| E2E `shard_general` module, UI variant (task T035) | 23:50:54 to 23:53:13 | `1 passed, 2 skipped, 3 deselected` (the skipped tests are `api_only`) |
| E2E `shard_general` module, API variant, paused after the deletion for the `kubectl` checks (task T036) | 23:54:23 to 23:57:42 | `3 passed, 3 deselected` |
| E2E `shard_general` module, API variant, after the review fixes | 2026-10-17, 02:25:24 to 02:27:59 | `3 passed, 3 deselected` |

Each E2E session passed at the first attempt. Only the module `test_service_discovery.py` ran locally, not the whole `shard_general` shard; the next section explains why that is enough for the new test. CI runs the full suite on this pull request.

## Deleting `intent` in the E2E test affects no later test of the `shard_general` session

<!-- T013 (critique E5), checked on 2026-10-16 -->

`test_deleted_deployment_leaves_no_alias` deletes the `intent` deployment of the session's scenario environment. CI runs the shard with `-m "ci and shard_general" -k "api-chromium"` (`.github/workflows/ci.yml`), and pytest runs the modules in file-name order, so two `shard_general` modules run after `test_service_discovery.py`:

- `test_ui_smoke.py` is marked `ui_only`, so pytest skips all its tests in the `api-chromium` session. In the `ui-chromium` session the new test is skipped instead, so `intent` stays.
- `test_worker_death_recovery.py` takes neither `driver_mode` nor `scenario_driver`, so its node ID has no `api-chromium` part and `-k "api-chromium"` deselects it. It also reads only the `styrmin` namespace and Prefect, not the scenario environment.

No other module refers to `intent` (`grep -rn intent backend/tests/e2e` finds it only in `test_service_discovery.py` and in unrelated comments). No module that runs after `test_service_discovery.py` counts the scenario environment's deployments. `executor` keeps running until the session ends, so the deletion does not empty the environment. Running the module alone is therefore enough for the local E2E evidence.

## Question for the maintainer: is a unit test enough for an alias that a failed teardown left?

The design brief left open whether the fix adds a test for this case: a failed teardown left an alias, and another deployment later uses that name for its own Service. The spec (Clarifications) answers yes, with one unit test, and flags the answer for confirmation because the brief did not give it.

The test is `test_cluster_ip_service_replaces_alias_a_failed_teardown_left` in [`backend/tests/unit/agent/test_apply_service.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/tests/unit/agent/test_apply_service.py). When the create of a deployment's `ClusterIP` Service returns 409, `apply_service` replaces the existing object with the `ClusterIP` manifest. It starts no deployment.

The test uses a mocked Kubernetes API, so it cannot show that the API server accepts the change of `spec.type` from `ExternalName` to `ClusterIP`. Research R-007 records that the Kubernetes documentation allows this change, not a cluster run.

Can this case keep the unit test only, or is an E2E test wanted?

## Answered by the maintainer: FR-017, which the brief did not list

> Answered on 2026-10-17: FR-017 is the wanted behaviour. The changelog and the user documentation list the aliases of a deployment whose namespace was deleted directly.

FR-017 was added during the critique of the spec. A restore deletes the target namespace, which deletes the StyrminDeployment in it and runs the delete handler's teardown. Without FR-017 that teardown would delete the restored deployment's aliases in the other namespaces. The restore flows write no alias, so those aliases would stay missing until a create, update or upgrade flow of that environment runs, and the other deployments could not reach the restored deployment by short name until then (research R-011).

FR-017: when a StyrminDeployment without `spec.deletionRequested: true` is deleted because its namespace is being deleted, the teardown deletes no alias. When the teardown cannot read the namespace, it deletes no alias and logs why.

What follows from the rule:

- The teardown deletes aliases when `spec.deletionRequested` is true (platform deletion, environment deletion, discarding a clone), or when the StyrminDeployment is deleted while its namespace exists and is not being deleted (`kubectl delete styrmindeployment`).
- Deleting a deployment's namespace directly, without a deletion request, leaves its aliases.
- A failed read of the namespace leaves the aliases rather than deleting those of a running deployment. The next flow that writes that name overwrites a left alias.

Unit tests in [`backend/tests/unit/test_deployment_deletion_operator.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/tests/unit/test_deployment_deletion_operator.py) cover the rule, among them `test_delete_service_aliases_keeps_aliases_when_the_namespace_goes_without_a_request` and `test_delete_service_aliases_keeps_aliases_when_the_namespace_cannot_be_read`. No E2E test runs a restore with aliases.

## Answered by the maintainer: the FR-007 exception

> Answered on 2026-10-17: the trade-off is accepted, and FR-007 now names the case. A cleanup of the aliases that stay is a separate issue.

When the StyrminDeployment is already removed at the flow's second read, the read cannot tell a deletion from a restore, so it keeps the alias. An alias written after the delete handler's teardown listed the aliases, and before the StyrminDeployment was removed, can then remain, and nothing deletes it later (research R-004).

## Follow-up issue [#527](https://github.com/opsmill/styrmin/issues/527): a deployment's own flow can create its namespace again after its deletion was requested

Research R-010 records a case that this change does not fix, because the brief covers only the flows of other deployments. A create, update or upgrade flow of a deployment that runs after the deletion of that same deployment was requested calls `apply_kubernetes_namespace` on its own namespace in `_write_styrmin_deployment` ([`backend/styrmin_backend/agent/tasks/orchestration.py`](https://github.com/opsmill/styrmin/blob/fac/services-cleanup-zk1ti/backend/styrmin_backend/agent/tasks/orchestration.py)), so it can create that namespace again. It is not known how often this happens; no test of this change reproduces it. Filed as [#527](https://github.com/opsmill/styrmin/issues/527).

## Follow-up issue [#526](https://github.com/opsmill/styrmin/issues/526): delete the aliases that stay

The maintainer accepted the FR-007 exception and asked for a separate issue. It would cover a cleanup of aliases whose owner is no longer a deployment of the environment, which would also delete aliases left by failed teardowns and by deletions made before this version (FR-011 and decision 6 of the brief exclude this from #503).

