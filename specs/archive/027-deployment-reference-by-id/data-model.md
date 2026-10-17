# Data Model: Deployment References Stored by Id

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

No table, column or index changes, and no Alembic revision. What changes is the shape of a deployment reference inside three JSON columns, and some in-memory types.

## Stored configs that can hold a deployment reference

| Column | Written by | Path prefix in errors |
| --- | --- | --- |
| `environment.config` | `createEnvironment`, `updateEnvironment`, the clone flow (`create_environment`), environment restore (direct assignment, not bound) | `environment.config` |
| `deployment.config` | `deploy`, `updateDeployment`, `updateDeploymentVersion`, the clone flow (`deploy_application`) | `deployment.config` |
| `component.config` | `deploy` and `updateDeploymentVersion`, copied from the driver version's component definitions | `component[<name>].config` |

Inside each, a reference sits at `scheduling.{pod_affinity|pod_anti_affinity}.required[i].deployment_ref` or `scheduling.{pod_affinity|pod_anti_affinity}.preferred[i].term.deployment_ref`. See [contracts/stored-config.md](contracts/stored-config.md).

## Deployment reference

| Field | On write (GraphQL, SDK, manifest) | Stored |
| --- | --- | --- |
| `deployment_id` | optional UUID string | always set, canonical lowercase UUID string |
| `deployment_name` | optional string; exactly one of the two (`DeploymentReference._require_one_identifier`) | never present |
| `components` | optional list of component names | kept as written |

Validation rules:

- A name must match a non-tombstoned deployment of the same environment at the time of the write, after the write's own changes (FR-001, FR-007).
- An id must be a non-tombstoned deployment of the same environment (FR-002).
- At reconcile, an id of a tombstoned deployment is refused with the last name (FR-004).

State over the life of a term:

```text
written with name N ──bind──▶ stored with id I ──rename of I──▶ unchanged
                                      │
                                      ├──delete of I──▶ refused at each reconcile (FR-004)
                                      │                 └─ write the term again with a name
                                      └──clone──▶ copy stores id of I's counterpart (FR-008)
```

## In-memory types

- `ReferenceSite` (`services/scheduling/references.py`): `path`, and the reference dict it points to.
- Upcoming deployments: `Mapping[UUID, str]`, the deployments that the current operation creates or renames, with their names after the operation. Passed to `bind_deployment_references`, `create_environment`, `deploy_application`, `generate_instance_from_deployment` and the resolver.
- Counterpart id mapping: `dict[UUID, UUID]`, source deployment id to counterpart id, built by the clone flow before it creates anything.

## Errors

| Error | `extensions.code` | Metadata |
| --- | --- | --- |
| `UnresolvableAffinityReferenceError` | `VALIDATION_ERROR` | `path`, `deployment_id` and/or `deployment_name`, `deleted: true` when the named deployment is tombstoned (new) |
| `UnclonedDeploymentReferenceError` (new) | `VALIDATION_ERROR` | `deployments`: list of `{deployment_id, deployment_name, paths}` |

## Clone record values

- New attribution reason (open string): "an affinity term names deployment <name>, which was not cloned".
- New clone error step: `referenced_deployment_not_cloned`, always fatal, added to `CLONE_STEPS`.
- The stored `config_override` holds bound references (ids of source deployments).
