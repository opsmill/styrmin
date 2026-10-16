# ADR-073: Kubernetes Objects Named and Found by Record Id

**Status**: Accepted
**Date**: 2026-10-16
**Decision-makers**: Fatih Acar
**Source**: [issue #488](https://github.com/opsmill/styrmin/issues/488);
[PR #479](https://github.com/opsmill/styrmin/pull/479) (known limit: renaming a location does not rename its Velero object)
**Related**: [ADR-034](0034-affinity-by-deployment-reference-via-label.md) (pod labels carry the deployment id),
[ADR-056](0056-environment-clone-record-and-cross-target-restore.md) (release name kept from the active instance)

## Context

Styrmin creates Kubernetes objects for its records. Most of them are named after the record's id:
the namespace, the `StyrminDeployment` CR, the HelmRelease and the HelmRepository of a deployment
are `styrmin-<deployment id>` (`get_kubernetes_reference` in `agent/service/kubernetes/utils.py`).
The Velero `BackupStorageLocation` and the credentials Secret of a backup storage location were
named after the location's name (`styrmin-bsl-<name>`), and every later step rebuilt the name
from the location's current name.

An administrator can rename a location. After a rename, the objects kept the old name and nothing
rebuilt it: backups named a Velero location that did not exist, a credentials update patched a
Secret that did not exist, and an unassign deleted nothing, which left the Secret with the S3 keys
in the cluster (#488). No rule said which of the two naming schemes new code must follow.

## Decision drivers

- A rename of a record must not change which cluster objects belong to it.
- Styrmin must find an object again to update or delete it, for the whole life of the record.
- Objects that earlier versions created must keep working after an upgrade. A Velero restore needs
  the `BackupStorageLocation` named in the backup's `spec.storageLocation`, so Styrmin cannot
  rename one that backups already name.

## Considered options

1. Name objects after the record's name, and on a rename create objects with the new name and
   delete the old ones.
2. Name objects after the record's name, and store each object's name on the record when it is
   created.
3. Name objects after the record's id, put the id on each object as a label, and find each object
   by that label or by its id-based name to update or delete it.

## Decision

We chose option 3. For every Kubernetes object that Styrmin creates for a record:

- the name is built from the record's id;
- the object carries a label with the id, such as `styrmin.io/bsl-id`;
- updates and deletes find the object by that label or by a name built only from the id, never by
  a name built from a field a user can change. While objects that an earlier version named
  differently can still exist, they select by the label, which also finds those objects;
- flows that act on cluster objects take the record's id, not its name.

When the name is what the user asked for, such as a service-name override, which names the
Service, the name stays, and updates and deletes select the object by an id label.

Option 1 fails the third driver: Kubernetes object names cannot be changed, so a rename means a
new object, and Velero backups that name the old `BackupStorageLocation` could no longer be
restored. Option 2 adds a column to each record that owns cluster objects, and a lost or stale
value leaves the objects behind, as in #488.

## Consequences

- Good, because a rename changes nothing in the cluster, and another record can take the old name
  without a name collision in the cluster.
- Good, because a label selector also finds objects that an earlier version named differently, so
  a naming change needs no migration of existing objects.
- Good, because names built from a UUID are always valid Kubernetes names. Record names are not
  checked against Kubernetes name rules, so a name with capitals or spaces could not become one.
- Bad, because an administrator who runs `kubectl get` sees ids, not names, and must look the id up in
  Styrmin or select by label.
- Bad, because an update or delete that selects by label costs a list call, and the service
  account needs `list` on the object type.
- Bad, because objects that versions before #488 named after the location's name stay under that
  name until the location is unassigned. Code must keep selecting by label, not by the id-based
  name, for as long as such objects can exist.

## Confirmation

Nothing automated. Enforced at review, with the rule in
[`dev/guidelines/backend/python.md`](../guidelines/backend/python.md#name-a-kubernetes-object-after-its-records-id-and-find-it-by-the-id)
and `AGENTS.md`.

## More information

- The ExternalName alias Services that `agent/tasks/service_aliases.py` creates are named after
  the service's resolved name, which a service-name override sets, and carry the
  `styrmin.io/deployment-id` label of the deployment that owns the service. A deployment's flow
  deletes its aliases whose name it no longer uses, so an alias with an old override name does
  not stay in the other deployments' namespaces
  ([#491](https://github.com/opsmill/styrmin/issues/491)). Aliases that earlier versions created
  have no such label; the flow finds their owner from the namespace that `spec.externalName`
  points into, which is built from the deployment's id.
- Known case that does not follow the decision yet: deleting a deployment leaves its aliases in the
  other deployments' namespaces, because the operator's teardown acts only in the deployment's own
  namespace ([#503](https://github.com/opsmill/styrmin/issues/503)).
- The open feature request [#5](https://github.com/opsmill/styrmin/issues/5) asks for namespace
  names built from the environment and deployment names, renamed on each rename. That is option 1
  of this record; implementing it needs a record that supersedes this one.
