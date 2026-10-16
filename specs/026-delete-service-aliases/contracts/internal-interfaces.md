# Internal Interfaces: Deleting a Deployment Deletes Its Service Aliases

The feature changes no GraphQL, SDK or CLI surface. These are the internal interfaces that change, with the behaviour the tests check. Names are proposals for the implementation; the behaviour is the contract.

## Kubernetes primitives (`agent/service/kubernetes/primitives.py`)

### `get_namespace(name: str) -> V1Namespace | None` (new)

- Returns the Namespace, or `None` on 404.
- Raises `ApiException` on any other error.

### `apply_service(resource: dict, namespace: str) -> V1Service` (new)

- Creates the Service; on 409 replaces it with `resource`.
- Returns the object the API server stored, so the caller has its `metadata.resourceVersion`.
- Raises `ApiException` on any other error, including 404 and 403.
- The `Service` branch of `apply_kubernetes_resource` calls it, so there is one create-then-replace implementation for Services.

### `is_namespace_gone_error(exc: ApiException) -> bool` (new)

- `True` for a 404, and for a 403 whose status body lists a cause of type `NamespaceTerminating`.
- `False` for anything else, including a 403 without that cause.

## Service alias flow (`agent/tasks/service_aliases.py`)

### `find_departing_namespaces(namespaces: Iterable[str]) -> set[str]` (new, async)

- For each namespace, reads the Namespace and the StyrminDeployment of the same name in it.
- Returns the departing ones, by the rule in [data-model.md](../data-model.md#departing-namespace-derived-new).
- Propagates any read error other than 404.

### `apply_single_alias(alias_namespace, alias_name, resource) -> WrittenAlias | None` (changed task)

- Writes with `apply_service`.
- Returns `None`, and logs, when `is_namespace_gone_error` is true for the error.
- Propagates any other error, as today.

### `apply_service_aliases(aliases: list[dict], stale_aliases: list[StaleAlias] | None = None) -> None` (changed flow)

The `namespace_labels` parameter is removed. The flow no longer calls `apply_namespace`.

1. Collects the holder and owner namespaces of `aliases` and the namespaces of `stale_aliases`, and calls `find_departing_namespaces` on them.
2. Skips, and logs, each alias whose holder or owner namespace is departing, and each stale alias whose namespace is departing.
3. Writes the remaining aliases with `apply_single_alias`.
4. Deletes the remaining stale aliases, as today.
5. Calls `find_departing_namespaces` on the owner namespaces of the written aliases. For each written alias whose owner namespace is now departing and whose holder namespace is not, deletes it with `delete_service` and the `resource_version` of the write.

Callers: `_apply_service_aliases_step` (the three CRD flows) and the unregistered legacy flows `create_instance`, `update_instance` and `upgrade_instance`. All drop the `namespace_labels` argument.

## Operator teardown (`operator/handlers/styrmin_deployment.py`)

### `_teardown_owned_resources(*, namespace, release_reference, deployment_id, name, logger)` (changed)

- New keyword argument `deployment_id: str`, from `spec.deploymentId`.
- New first step "Service aliases" (`_delete_service_aliases`), before the existing Services/Middlewares, HelmRelease and NetworkPolicies/Secrets steps.
- Both callers pass `spec.get("deploymentId", "")`:
  - `kopf_on_styrmin_deployment_deletion_requested`;
  - `kopf_on_styrmin_deployment_delete`, after its skip-teardown branch.

### `_delete_service_aliases(*, deployment_id: str, namespace: str, logger) -> None` (new)

- When `deployment_id` is not a UUID, or `namespace != get_kubernetes_reference(deployment_id)`: logs a warning and returns without a call to the API server.
- Lists the Services labelled `styrmin.io/service-alias=true` in all namespaces. On a listing error: logs it with `logger.exception` and returns.
- For each listed alias for which `is_alias_of_deployment(alias, deployment_id, namespace)` is true: calls `delete_service(name, namespace)`.
  - A `False` result (404) counts as deleted.
  - Any exception is logged with `logger.exception`, naming the alias's namespace and name, and the loop continues.
- Never raises.
- Logs one info line with the number of aliases deleted.
