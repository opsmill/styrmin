# Data Model: Deleting a Deployment Deletes Its Service Aliases

No database table, column or GraphQL type changes. The entities below are Kubernetes objects and in-memory models of the agent and the operator.

## Service alias (Kubernetes `Service`, existing)

Built by `build_external_name_service` ([`service_aliases.py`](../../backend/styrmin_backend/agent/tasks/service_aliases.py)); unchanged by this feature.

| Field | Value |
| --- | --- |
| `metadata.name` | the service's resolved name |
| `metadata.namespace` | the **holder namespace**: the namespace of the deployment whose pods resolve the name |
| `metadata.labels["app.kubernetes.io/managed-by"]` | `styrmin` |
| `metadata.labels["styrmin.io/service-alias"]` | `"true"` |
| `metadata.labels["styrmin.io/deployment-id"]` | the **owner**: id of the deployment that owns the service. Absent on aliases written before #506 |
| `spec.type` | `ExternalName` |
| `spec.externalName` | `<name>.<owner namespace>.svc.<cluster domain>` |

Derived values:

- **Owner namespace**: `styrmin-<owner id>` from the label; for an alias without the label, the second dot-separated part of `spec.externalName`.
- **Belongs to deployment D**: `is_alias_of_deployment(alias, D id, styrmin-<D id>)`, unchanged from #506.

## Departing namespace (derived, new)

A namespace `N` is departing when one of these holds (research R-003):

- the Namespace `N` does not exist;
- `N.status.phase == "Terminating"`;
- the StyrminDeployment `N` in namespace `N` exists and has `spec.deletionRequested == true` or `metadata.deletionTimestamp` set.

State over a deployment's deletion:

| Moment | Namespace | StyrminDeployment | Departing |
| --- | --- | --- | --- |
| Running | `Active` | exists, no flag | no |
| User requested the deletion | `Active` | `spec.deletionRequested: true` | yes |
| Operator requested the namespace deletion | `Terminating` | `deletionTimestamp` set | yes |
| Namespace gone, status `DELETED` | absent | absent | yes |
| `kubectl delete styrmindeployment` | `Active` | `deletionTimestamp` set | yes |
| New deployment, before its CR write | `Active` or absent | absent | no if `Active`; yes if absent |

## `WrittenAlias` (Pydantic model, new, agent)

Returned by the task that writes one alias, so the flow can delete it again after its second read (R-004).

| Field | Type | Meaning |
| --- | --- | --- |
| `namespace` | `str` | holder namespace |
| `name` | `str` | alias name |
| `owner_namespace` | `str` | owner namespace |
| `resource_version` | `str \| None` | `metadata.resourceVersion` returned by the create or replace |

## `StaleAlias` (Pydantic model, existing)

Unchanged. The flow drops a stale alias whose `namespace` is departing, because that namespace's deletion removes it.

## StyrminDeployment (CR, existing)

Read, not changed. Fields used:

- `metadata.name`, `metadata.namespace`: equal for every CR a flow writes.
- `metadata.deletionTimestamp`: set by `kubectl delete` and by the namespace deletion.
- `metadata.annotations["styrmin.io/skip-teardown"]`: `"true"` on the copy that a cross-target restore deletes.
- `spec.deploymentId`: the deployment's id; the teardown deletes aliases only when `metadata.namespace == styrmin-<spec.deploymentId>` (R-001).
- `spec.deletionRequested`: set by the server when the user requests the deletion.
