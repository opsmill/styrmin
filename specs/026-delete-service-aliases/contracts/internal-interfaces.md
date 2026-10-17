# Internal Interfaces: Deleting a Deployment Deletes Its Service Aliases

The feature changes no GraphQL, SDK or CLI surface. These are the internal interfaces that change, with the behaviour the tests check. Names are proposals for the implementation; the behaviour is the contract.

> Changed on 2026-10-17, after the code review: step 5 of `apply_service_aliases` uses the new `find_deleted_deployment_namespaces`, which follows the operator teardown's rule, and deletes a written alias whatever namespace holds it (research R-004).
>
> Changed on 2026-10-17, after the review of PR #516: the alias step reads the current services from the server (`with_current_peer_services`, research R-012), in place of the 60-second wait for a missing namespace that commit `c4fd1534` added. The labels and the shared rules move to `service_alias_rules.py`, and the StyrminDeployment read to `styrmin_deployment.py`, so the operator imports no Prefect module. The teardown lists the aliases with two label selectors and deletes them with a `resourceVersion` precondition.

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

- `True` for a 404 (the namespace or the Service is gone), and for a 403 whose status body lists a cause of type `NamespaceTerminating` or whose message contains "because it is being terminated", the message of Kubernetes' `NamespaceLifecycle` plugin.
- `False` for anything else, including an RBAC 403.

## Shared alias rules (`agent/service/kubernetes/service_alias_rules.py`, new)

Imports no Prefect code, so the operator imports it.

- `SERVICE_ALIAS_LABEL`, `DEPLOYMENT_ID_LABEL`: the two labels of an alias.
- `is_alias_of_deployment(alias, deployment_id, namespace) -> bool`: the label holds `deployment_id`, or, without the label, `spec.externalName` points into `namespace`.
- `is_gone_or_terminating(namespace: V1Namespace | None) -> bool`.
- `teardown_deletes_aliases(*, deletion_requested: bool, namespace: V1Namespace | None) -> bool`: true when `deletion_requested`, or when the Namespace exists and is not `Terminating`. The operator's `_delete_service_aliases` and the flow's second read both use it.

## StyrminDeployment read (`agent/service/kubernetes/styrmin_deployment.py`, new)

- `read_styrmin_deployment(*, name, namespace) -> dict | None`: the custom resource, or `None` on 404. `orchestration.py` and the alias flow both use it.

## Current services of an environment (`agent/tasks/environment_services.py`, new)

### `read_environment_services(environment_id: str) -> list[dict[str, str]]` (new, async)

- Sends the `ListEnvironmentServices` query (`agent/tasks/list_environment_services.graphql`, `environmentServices`) with the flow's action token, and returns `resolved_name` and `deployment_id` for each service.
- Raises `EnvironmentServicesReadError` when there is no token, the request fails, the response is not JSON, it carries GraphQL errors, or it has no `environmentServices`.

## Service alias flow (`agent/tasks/service_aliases.py`)

### `with_current_peer_services(context: GlobalContext) -> GlobalContext` (new, async)

- Reads the environment's services with `read_environment_services(context.labels["environment_id"])`.
- Returns a copy of `context` whose `deployed_services` holds the deployment's own entries from the context and the other deployments' entries from the server. Logs the ids of the deployments that the server lists and the context does not.
- Returns `context` unchanged, with a warning, when the labels have no `environment_id` or the read raises `EnvironmentServicesReadError`.
- `_apply_service_aliases_step` calls it before `compute_service_aliases` and `find_stale_service_aliases`.

### `find_departing_namespaces(namespaces: Iterable[str]) -> set[str]` (new, async)

- For each namespace, reads the Namespace and the StyrminDeployment of the same name in it. The reads run concurrently, at most `MAX_CONCURRENT_NAMESPACE_READS` (10) namespaces at the same time.
- Returns the departing ones, by the rule in [data-model.md](../data-model.md#departing-namespace-derived-new). A namespace that does not exist yet counts as departing; the alias step of its deployment writes the skipped aliases later (research R-012).
- Propagates any read error other than 404.

### `find_deleted_deployment_namespaces(namespaces: Iterable[str]) -> set[str]` (new, async)

- Reads as `find_departing_namespaces` does, concurrently.
- Returns the namespaces whose StyrminDeployment has `spec.deletionRequested: true`, or has a `metadata.deletionTimestamp` while the Namespace exists and is not `Terminating`, by the rule in [data-model.md](../data-model.md#owner-namespace-of-a-deleted-deployment-derived-new). A Namespace that is missing or `Terminating` without a deletion request does not count.

### `apply_single_alias(alias_namespace, alias_name, resource) -> WrittenAlias | None` (changed task)

- Writes with `apply_service`.
- Returns `None`, and logs the status with its meaning, when `is_namespace_gone_error` is true for the error: 404 (the namespace or the Service is gone), or 403 (the namespace is terminating).
- Propagates any other error, as today.

### `apply_service_aliases(aliases: list[dict], stale_aliases: list[StaleAlias] | None = None) -> None` (changed flow)

The `namespace_labels` parameter is removed. The flow no longer calls `apply_namespace`.

1. Collects the holder and owner namespaces of `aliases` and the namespaces of `stale_aliases`, and calls `find_departing_namespaces` on them.
2. Skips, and logs, each alias whose holder or owner namespace is departing, and each stale alias whose namespace is departing. The log names the departing namespace: the owner's when it matched, otherwise the holder's.
3. Writes the remaining aliases with `apply_single_alias`.
4. Deletes the remaining stale aliases, as today.
5. Calls `find_deleted_deployment_namespaces` on the owner namespaces of the written aliases. For each written alias whose owner namespace it returns, whatever namespace holds the alias, deletes it with `delete_service` and the `resource_version` of the write, and logs whether the delete deleted the alias.

Callers: `_apply_service_aliases_step` (the three CRD flows) and the unregistered legacy flows `create_instance`, `update_instance` and `upgrade_instance`. All drop the `namespace_labels` argument.

## Operator teardown (`operator/handlers/styrmin_deployment.py`)

### `_teardown_owned_resources(*, namespace, release_reference, deployment_id, deletion_requested, name, logger)` (changed)

- New keyword arguments `deployment_id: str`, from `spec.deploymentId`, and `deletion_requested: bool`, from `spec.deletionRequested`.
- New first step "Service aliases" (`_delete_service_aliases`), before the existing Services/Middlewares, HelmRelease and NetworkPolicies/Secrets steps.
- Both callers pass `spec.get("deploymentId", "")` and `spec.get("deletionRequested", False)`:
  - `kopf_on_styrmin_deployment_deletion_requested`, where the flag is true;
  - `kopf_on_styrmin_deployment_delete`, after its skip-teardown branch.

### `_delete_service_aliases(*, deployment_id: str, namespace: str, deletion_requested: bool, logger) -> None` (new)

- When `deployment_id` is not a UUID, or `namespace != get_kubernetes_reference(deployment_id)`: logs a warning and returns without a call to the API server.
- When `deletion_requested` is false: reads the Namespace with `get_namespace` (research R-011).
  - The Namespace is missing or `Terminating`: logs that the namespace is being deleted without a deletion request, as a restore does, and returns.
  - The read raises: logs it with `logger.exception` and returns.
  - Otherwise (`kubectl delete styrmindeployment`): continues.
- Lists the aliases in all namespaces with two label selectors: `styrmin.io/service-alias=true,styrmin.io/deployment-id=<deployment_id>`, and `styrmin.io/service-alias=true,!styrmin.io/deployment-id`. On an error of one listing: logs it with `logger.exception`, naming the selector, and goes on with the other.
- For each listed alias for which `is_alias_of_deployment(alias, deployment_id, namespace)` is true: calls `delete_service(name, namespace, resource_version)` with the `resourceVersion` of the listing.
  - A `False` result (404, or 409 because the Service changed since the listing) is logged, naming the alias, and is no error.
  - Any exception is logged with `logger.exception`, naming the alias's namespace and name, and the loop continues.
- Never raises.
- Logs one info line with the number of aliases it deleted.
