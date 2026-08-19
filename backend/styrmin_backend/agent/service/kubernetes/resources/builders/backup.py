from __future__ import annotations

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackup,
    VeleroBackupHook,
    VeleroRestore,
    VeleroRestoreHook,
)

# `<fullname>-<key>` of `velero.configMaps.restore-pvc-patch` in helm/styrmin/values.yaml;
# every Velero Restore references it. Guarded by backend/tests/unit/test_helm_velero_naming.py.
VELERO_RESTORE_PVC_PATCH_CONFIGMAP = "velero-restore-pvc-patch"


def build_velero_backup(
    name: str,
    velero_namespace: str,
    target_namespace: str,
    instance_id: str,
    driver_name: str,
    ttl: str,
    hooks: list[VeleroBackupHook] | None = None,
    storage_location: str | None = None,
) -> VeleroBackup:
    """Build a VeleroBackup resource for an Styrmin instance.

    ``ttl`` is required: retention is resolved by the caller from the
    deployment/environment/cluster config chain (``services/backup/ttl.py``),
    and this builder stays a pure renderer with no policy of its own.
    """
    return VeleroBackup(
        name=name,
        namespace=velero_namespace,
        included_namespaces=[target_namespace],
        labels={
            "styrmin.io/instance": instance_id,
            "styrmin.io/driver": driver_name,
        },
        hooks=hooks or [],
        ttl=ttl,
        storage_location=storage_location,
    )


def build_velero_restore(
    name: str,
    velero_namespace: str,
    backup_name: str,
    source_namespace: str,
    target_namespace: str,
    instance_id: str,
    driver_name: str,
    existing_resource_policy: str | None = None,
    hooks: list[VeleroRestoreHook] | None = None,
    target_instance_id: str | None = None,
) -> VeleroRestore:
    """Build a VeleroRestore resource for an Styrmin instance.

    ``instance_id`` identifies the instance the backup was taken from. For a
    **cross-target** restore (environment clone) that is the source instance,
    which is not what the Restore CR should be attributed to — pass
    ``target_instance_id`` and ``styrmin.io/instance`` names the counterpart
    instance the data lands in, with the source recorded under
    ``styrmin.io/source-instance`` so provenance is not lost (research D2.6).
    Omitting it keeps the in-place labelling untouched.
    """
    namespace_mapping = None
    if source_namespace != target_namespace:
        namespace_mapping = {source_namespace: target_namespace}

    labels = {
        "styrmin.io/instance": target_instance_id or instance_id,
        "styrmin.io/driver": driver_name,
    }
    if target_instance_id is not None and target_instance_id != instance_id:
        labels["styrmin.io/source-instance"] = instance_id

    return VeleroRestore(
        name=name,
        namespace=velero_namespace,
        backup_name=backup_name,
        namespace_mapping=namespace_mapping,
        labels=labels,
        hooks=hooks or [],
        restore_pvs=False,
        existing_resource_policy=existing_resource_policy,
        preserve_node_ports=False,
        resource_modifier_ref=VELERO_RESTORE_PVC_PATCH_CONFIGMAP,
    )
