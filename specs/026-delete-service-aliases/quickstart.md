# Quickstart: Validating That a Deleted Deployment Leaves No Service Alias

## Prerequisites

- `uv sync` done at the repo root.
- For the E2E test: `docker` and `vcluster` on `PATH`; build the server image first (`docker compose build server`), because the fixture's parallel builds race on one tag.

## Unit tests

```bash
uv run pytest backend/tests/unit/agent/test_service_aliases.py \
  backend/tests/unit/agent/test_apply_service.py \
  backend/tests/unit/test_deployment_deletion_operator.py \
  backend/tests/unit/services/test_context_deleting_peer_services.py -v
```

Expected: all pass. They cover, in order of the spec's FR-014:

1. The teardown deletes labelled and unlabelled aliases of the deployment and keeps other deployments' aliases ([contract](contracts/internal-interfaces.md#_delete_service_aliases-deployment_id-str-namespace-str-logger---none-new)).
2. A 404 counts as deleted; another error is logged and the namespace deletion still runs.
3. The alias flow writes no alias of a departing deployment and nothing into its namespace, and creates no namespace, both when the context was built while the deployment is `DELETING` and when it was built before the request (the deletion flag appears between the flow's two reads).
4. The context lists a `DELETING` peer's services.
5. The skip-teardown annotation deletes no alias.
6. `apply_service` replaces an alias with a `ClusterIP` Service on 409.

## E2E test

One variant per session, with `--pdb` so a failure keeps the vcluster alive:

```bash
sleep infinity | uv run pytest \
  "backend/tests/e2e/test_service_discovery.py" -k "api-chromium" -v -s --pdb 2>&1 | tee /tmp/e2e-503.log
```

Expected: the three tests of the module pass, the new one last:

```text
PASSED backend/tests/e2e/test_service_discovery.py::test_deleted_deployment_leaves_no_alias[api-chromium]
```

## Manual check on a paused session

While pytest is paused, or against the dev stack after deleting a deployment `A` next to a deployment `B`:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
# No Service in any namespace is labelled with A's id.
kubectl get svc -A -l styrmin.io/service-alias=true,styrmin.io/deployment-id=<A id>
# No alias points into A's namespace.
kubectl get svc -A -l styrmin.io/service-alias=true \
  -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.externalName}{"\n"}{end}' \
  | grep "styrmin-<A id>"
```

Expected: both commands print nothing once `A`'s status is `DELETED`.

The operator log of the deletion shows the new teardown step first:

```text
Teardown step 1: service aliases of <A id> in all namespaces
Deleted <n> service aliases of <A id>
```
