# Data Model: A Clone Writes Its Own Service Aliases and Restores None of the Source's

No database table, column or GraphQL type changes. The entities below exist already; this page states what changes in how they are written or read.

## Service alias (Kubernetes `Service`, existing)

- `metadata.name`: the resolved name of the service it aliases.
- `metadata.labels`: `app.kubernetes.io/managed-by=styrmin`, `styrmin.io/service-alias=true`, `styrmin.io/deployment-id=<owner deployment id>`.
- `spec.type: ExternalName`, `spec.externalName: <name>.styrmin-<owner id>.svc.<cluster domain>`.

Changes:

- A cross-target restore no longer restores any alias from the backup.
- At the end of a cross-target restore, the step "Create and delete service aliases" writes, for counterpart C of new environment E:
  - into `styrmin-<C>`, one alias per service of every other deployment of E that has recorded services and whose namespace exists;
  - into the namespace of each of those deployments, one alias per service of C.
- Invariant after a clone (SC-001): in each counterpart's namespace, the set of aliases equals one per service of every other deployment of E that has recorded services and a namespace, and `styrmin.io/deployment-id` names the deployment that the `externalName` namespace belongs to.

## Velero Restore (Kubernetes custom resource, existing)

| Field | In-place restore | Cross-target restore |
|-------|------------------|----------------------|
| `namespaceMapping` | absent | `{styrmin-<source>: styrmin-<counterpart>}` |
| `excludedResources` | `ciliumendpoints.cilium.io` | plus `helmreleases.helm.toolkit.fluxcd.io` |
| `labelSelector` | absent | `matchExpressions: [{key: styrmin.io/service-alias, operator: NotIn, values: ["true"]}]` (new) |

## Restore steps (existing `Step` rows of a restore)

| Order | Key | Name | In-place | Cross-target |
|-------|-----|------|----------|--------------|
| 1 | `restore:namespace` | Delete the namespace | yes | yes |
| 2 | `restore:velero` | Run the Velero restore | yes | yes |
| 3 | `restore:recovery` | Run the recovery | yes | yes |
| 4 | `resource:service-aliases` | Create and delete service aliases | no | yes, when there is an alias to write or delete (new) |

## Restore and counterpart deployment states

```text
recovery succeeded ──► alias step succeeded ──► restore COMPLETED, deployment RUNNING
                   └─► alias step failed ─────► restore FAILED (error "Service alias step failed: …"),
                                                deployment FAILED, then the status reported by its
                                                StyrminDeployment (DEPLOYING, then RUNNING)
recovery failed ───────────────────────────────► unchanged: restore FAILED, deployment FAILED
```

After an alias failure, the counterpart reads `RUNNING` again once its StyrminDeployment is `Ready`, but its aliases are missing until an update or an upgrade that changes it runs the alias step (research R-004, R-005).

## Clone deployment result (`EnvironmentClone.deployment_results[]`, existing JSON)

Stored as today. The value users read through the API changes for one case:

| Stored outcome | Restore row | Outcome read | Reason read |
|----------------|-------------|--------------|-------------|
| `cloned` | `FAILED` | `failed` (changed) | `the restore failed: <restore error_message>`, or `the restore failed` |
| `cloned` | non-terminal, `COMPLETED`, or missing | `cloned` | stored reason |
| `skipped` or `failed` | any | stored outcome | stored reason |

`counterpartDeploymentId` and `restoreId` are returned as stored in every case.
