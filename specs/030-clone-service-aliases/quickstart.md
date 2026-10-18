# Quickstart: Validating That a Clone Writes Its Own Service Aliases

## Prerequisites

- `uv sync` done; `vcluster` and `docker` on `PATH` for the E2E tests.
- Build the server image before an E2E session: `docker compose build server`.

## Unit and functional tests

```bash
uv run pytest backend/tests/unit/agent/test_backup_builders.py \
  backend/tests/unit/agent/test_service_aliases.py \
  backend/tests/unit/workflows/test_restore_steps.py \
  backend/tests/unit/services/backup/test_environment_clone_status.py \
  backend/tests/functional/graphql/test_environment_clone.py -v
```

Expected: all pass. In particular, the cross-target restore renders the label selector and the in-place restore does not; the restore steps include "Create and delete service aliases" for a cross-target restore only; a refused alias write fails the restore; an entry whose restore failed reads `FAILED` with the restore's error.

## E2E tests

Run one variant per pytest session, with `--pdb`, from a non-interactive shell:

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_backup_restore.py::test_environment_clone_lifecycle" \
  "backend/tests/e2e/test_backup_restore.py::test_environment_backup_and_restore_lifecycle" \
  -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-030-api.log
```

Repeat with `-k ui-chromium`. Expected: both nodes `PASSED` in each variant. Record the evidence that Constitution §V asks for (node id, command, timestamp, vcluster id and kubeconfig path, `PASSED` line).

## Manual check on a paused session

With the session paused after the first clone of `test_environment_clone_lifecycle`:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
# Each alias in a counterpart's namespace points into a namespace of the clone.
kubectl get svc -n styrmin-<counterpart id> -l styrmin.io/service-alias=true \
  -o custom-columns=NAME:.metadata.name,OWNER:.metadata.labels.styrmin\\.io/deployment-id,TARGET:.spec.externalName
# The Velero Restore of a counterpart has the label selector.
kubectl get restores.velero.io -n styrmin -o jsonpath='{range .items[*]}{.metadata.name} mapping={.spec.namespaceMapping} selector={.spec.labelSelector}{"\n"}{end}'
```

`--pdb` pauses only on a failure. To pause a passing run, add a temporary `breakpoint()` right after the SC-001 check of the first clone. The test deletes the first clone's environment soon after that check, so without a pause the counterparts' aliases exist for less than 30 seconds.

Expected: every `TARGET` names `styrmin-<id>` of a deployment of the new environment, and `OWNER` is that id. The cross-target Restores, which have a namespace mapping, show the `NotIn` selector; in-place Restores show neither a mapping nor a selector.
