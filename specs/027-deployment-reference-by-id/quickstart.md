# Quickstart: Validate Deployment References Stored by Id

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Prerequisites

- `uv sync`, and `cd frontend && pnpm --ignore-workspace install` once (needed by `uv run invoke generate`).
- In this emdash worktree, `export npm_config_ignore_workspace=true` before `uv run invoke generate` and `uv run invoke lint`.
- E2E: `docker` and `vcluster` on `PATH`. Build the server image first with `docker compose build server`.

## 1. Generated surface is current

```bash
uv run styrmin export graphql-schema schema.graphql
uv run invoke generate
git diff --stat schema.graphql python_sdk/src/styrmin_sdk/graphql/_generated frontend/src/generated
```

Expected: only description text changes for `DeploymentReferenceInput` ([contracts/graphql-and-errors.md](contracts/graphql-and-errors.md)).

## 2. Unit and functional tests

```bash
uv run pytest backend/tests/unit/services/scheduling/test_references.py \
  backend/tests/unit/services/test_deployment_reference_binding.py \
  backend/tests/unit/services/test_scheduling_validator.py \
  backend/tests/unit/services/backup/test_environment_clone_service.py -q
uv run pytest backend/tests/functional/graphql/test_deploy_input_propagation.py \
  backend/tests/functional/graphql/test_update_deployment_input_propagation.py \
  backend/tests/functional/graphql/test_update_deployment_version_input_propagation.py \
  backend/tests/functional/graphql/test_environment_update_propagation.py \
  backend/tests/functional/graphql/test_deployment_noop_propagation.py \
  backend/tests/functional/graphql/test_environment_clone.py -q
```

Expected: all pass. These cover FR-001 to FR-009 without a cluster. The clone functional tests run the real flow with both snapshot orders and with mutual terms (FR-008).

## 3. Manual check through GraphQL (optional, dev stack)

With `uv run invoke dev` running and an environment `E` with deployments `a` and `b`:

1. `updateDeployment` on `b` with `scheduling.podAffinity.preferred[0].term.deploymentRef.deploymentName: "a"`. Read `b`'s `config`: the term gives `deployment_id` with `a`'s id and no `deployment_name` (FR-001, FR-003).
2. `updateDeployment` on `a` with `deploymentName: "a2"`. It succeeds. `b`'s `resolvedScheduling` still gives `styrmin/deployment_id=<a's id>` (US1).
3. `updateDeployment` on `b` with the config exactly as read. The returned `Task` is null (FR-009).
4. `updateEnvironment` on `E` with a term that names `missing`. The error has code `VALIDATION_ERROR` and the term's path, and `E`'s config is unchanged (FR-002).
5. Delete `a2`, then update `b`. The error gives the term's path, `deployment_name: "a2"` and `deleted: true` (FR-004).

## 4. E2E

Run each node in its own pytest session, in its shard, with `--pdb` kept alive:

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_pod_scheduling.py::test_pod_anti_affinity_cross_deployment_via_graphql" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-scheduling.log

sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-clone-api.log

sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" \
  -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-clone-ui.log
```

Expected:

- Scheduling: A's stored term gives B's id; B's rename leaves A's pod uids unchanged (SC-002); A's write-back returns a null `Task`; after A's update the rendered pod template selects `styrmin/deployment_id=<B's id>` (SC-001).
- Clone: the request that selects only the peer is refused with `UnclonedDeploymentReferenceError` and creates no record (FR-005); the clone of both ends `COMPLETED`; the peer's counterpart term gives the primary's counterpart id, and no term in the new environment gives a source id (SC-003).

Record for each node the node id, command, ISO 8601 time of the passing run, the vcluster id and kubeconfig path, and the verbatim `PASSED` line (Constitution §V).

## 5. Lint and format

```bash
uv run invoke format lint
```
