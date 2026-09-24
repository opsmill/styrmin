from dataclasses import dataclass, field
from typing import Any


@dataclass
class VeleroBackupHookExec:
    command: list[str]
    container: str | None = None
    on_error: str = "Fail"
    timeout: str = "600s"


@dataclass
class VeleroBackupHook:
    name: str
    included_namespaces: list[str]
    label_selector: dict[str, dict[str, str]]
    pre: list[VeleroBackupHookExec] | None = None
    post: list[VeleroBackupHookExec] | None = None

    def render(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "includedNamespaces": self.included_namespaces,
            "labelSelector": self.label_selector,
        }
        if self.pre:
            result["pre"] = [self._render_hook_exec(h) for h in self.pre]
        if self.post:
            result["post"] = [self._render_hook_exec(h) for h in self.post]
        return result

    @staticmethod
    def _render_hook_exec(h: VeleroBackupHookExec) -> dict[str, Any]:
        exec_spec: dict[str, Any] = {
            "command": h.command,
            "onError": h.on_error,
            "timeout": h.timeout,
        }
        if h.container:
            exec_spec["container"] = h.container
        return {"exec": exec_spec}


@dataclass
class VeleroBackup:
    name: str
    namespace: str
    included_namespaces: list[str]
    # Retention is policy, not a rendering concern: the caller resolves it
    # (deployment → environment → cluster → built-in default) and passes it
    # in. Deliberately has no default so this renderer cannot silently
    # disagree with the resolved policy — see services/backup/ttl.py.
    ttl: str
    labels: dict[str, str] = field(default_factory=dict)
    hooks: list[VeleroBackupHook] = field(default_factory=list)
    include_cluster_resources: bool = False
    storage_location: str | None = None

    def render(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "includedNamespaces": self.included_namespaces,
            "includeClusterResources": self.include_cluster_resources,
            "ttl": self.ttl,
        }
        if self.storage_location:
            spec["storageLocation"] = self.storage_location
        if self.hooks:
            spec["hooks"] = {"resources": [h.render() for h in self.hooks]}

        result: dict[str, Any] = {
            "apiVersion": "velero.io/v1",
            "kind": "Backup",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
            },
            "spec": spec,
        }
        if self.labels:
            result["metadata"]["labels"] = self.labels
        return result


@dataclass
class VeleroBackupStorageLocation:
    """Represents a Velero BackupStorageLocation CRD + credential Secret."""

    name: str
    namespace: str
    bucket: str
    region: str
    endpoint: str
    credential_secret_name: str
    bsl_id: str
    labels: dict[str, str] = field(default_factory=dict)

    def render_bsl(self) -> dict[str, Any]:
        """Render the Velero BackupStorageLocation CRD manifest."""
        labels = {
            "styrmin.io/managed": "true",
            "styrmin.io/bsl-id": self.bsl_id,
            **self.labels,
        }
        return {
            "apiVersion": "velero.io/v1",
            "kind": "BackupStorageLocation",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "provider": "aws",
                "objectStorage": {
                    "bucket": self.bucket,
                },
                "config": {
                    "region": self.region,
                    "s3ForcePathStyle": "true",
                    "s3Url": self.endpoint,
                },
                "credential": {
                    "name": self.credential_secret_name,
                    "key": "cloud",
                },
            },
        }

    def render_secret(
        self, access_key_id: str, secret_access_key: str
    ) -> dict[str, Any]:
        """Render the credential Secret manifest."""
        labels = {
            "styrmin.io/managed": "true",
            "styrmin.io/bsl-id": self.bsl_id,
            **self.labels,
        }
        cloud_credentials = (
            f"[default]\n"
            f"aws_access_key_id = {access_key_id}\n"
            f"aws_secret_access_key = {secret_access_key}\n"
        )
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": self.credential_secret_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "type": "Opaque",
            "stringData": {
                "cloud": cloud_credentials,
            },
        }


@dataclass
class VeleroRestoreHookExec:
    command: list[str]
    container: str | None = None
    on_error: str = "Fail"
    # Velero's ExecRestoreHook field is `execTimeout`; a bare `timeout` (the backup
    # hook field) is pruned by the Restore CRD and velero falls back to its 30s default.
    exec_timeout: str = "600s"
    wait_for_ready: bool = True


@dataclass
class VeleroRestoreHook:
    name: str
    included_namespaces: list[str]
    label_selector: dict[str, dict[str, str]]
    post: list[VeleroRestoreHookExec]

    def render(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "includedNamespaces": self.included_namespaces,
            "labelSelector": self.label_selector,
        }
        result["postHooks"] = [self._render_hook_exec(h) for h in self.post]
        return result

    @staticmethod
    def _render_hook_exec(h: VeleroRestoreHookExec) -> dict[str, Any]:
        exec_spec: dict[str, Any] = {
            "command": h.command,
            "onError": h.on_error,
            "execTimeout": h.exec_timeout,
            "waitForReady": h.wait_for_ready,
        }
        if h.container:
            exec_spec["container"] = h.container
        return {"exec": exec_spec}


@dataclass
class VeleroRestore:
    name: str
    namespace: str
    backup_name: str
    namespace_mapping: dict[str, str] | None = None
    labels: dict[str, str] = field(default_factory=dict)
    hooks: list[VeleroRestoreHook] = field(default_factory=list)
    restore_pvs: bool = True
    existing_resource_policy: str | None = None
    preserve_node_ports: bool = True
    resource_modifier_ref: str | None = None
    excluded_resources: list[str] = field(default_factory=list)

    def render(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "backupName": self.backup_name,
            "restorePVs": self.restore_pvs,
            "preserveNodePorts": self.preserve_node_ports,
        }
        if self.namespace_mapping:
            spec["namespaceMapping"] = self.namespace_mapping
        if self.excluded_resources:
            spec["excludedResources"] = self.excluded_resources
        if self.existing_resource_policy:
            spec["existingResourcePolicy"] = self.existing_resource_policy
        if self.resource_modifier_ref:
            spec["resourceModifier"] = {
                "kind": "ConfigMap",
                "name": self.resource_modifier_ref,
            }
        if self.hooks:
            spec["hooks"] = {"resources": [h.render() for h in self.hooks]}

        result: dict[str, Any] = {
            "apiVersion": "velero.io/v1",
            "kind": "Restore",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
            },
            "spec": spec,
        }
        if self.labels:
            result["metadata"]["labels"] = self.labels
        return result
