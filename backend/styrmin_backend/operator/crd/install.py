"""Apply the agent chart's CRDs before an install or upgrade of the chart.

Helm installs the files in ``crds/`` only when a CRD does not exist yet and never updates them,
so the chart's pre-install and pre-upgrade hook runs ``styrmin agent apply-crds`` instead.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException
from loguru import logger

from styrmin_backend.exceptions import StyrminError

FIELD_MANAGER = "styrmin-agent"
_DELETE_TIMEOUT_SECONDS = 60.0
_DELETE_POLL_SECONDS = 1.0


class CrdApplyAction(StrEnum):
    APPLIED = "applied"
    RECREATED = "recreated"


@dataclass(frozen=True)
class CrdApplyResult:
    name: str
    action: CrdApplyAction


class CrdApplyError(StyrminError):
    """A CRD of the chart cannot be applied."""


def load_crd_files(directory: Path) -> list[dict[str, Any]]:
    """Read every CustomResourceDefinition in the ``*.yaml`` files of ``directory``, sorted by file name."""
    crds: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if not document:
                continue
            if document.get("kind") != "CustomResourceDefinition":
                msg = f"{path.name} holds a {document.get('kind')}, not a CustomResourceDefinition"
                raise CrdApplyError(msg)
            crds.append(document)
    return crds


def removed_stored_versions(
    existing: dict[str, Any], desired: dict[str, Any]
) -> list[str]:
    """The versions the cluster stored objects in that ``desired`` no longer lists.

    The API server rejects such an update, because objects can still be stored in those versions.
    """
    listed = {version["name"] for version in desired["spec"]["versions"]}
    stored = (existing.get("status") or {}).get("storedVersions") or []
    return [version for version in stored if version not in listed]


def _served_version(crd: dict[str, Any]) -> str:
    versions = crd["spec"]["versions"]
    return next((v["name"] for v in versions if v.get("storage")), versions[0]["name"])


async def _read_crd(
    api: kubeclient.ApiextensionsV1Api, name: str
) -> dict[str, Any] | None:
    try:
        crd = await api.read_custom_resource_definition(name=name)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise
    return api.api_client.sanitize_for_serialization(crd)


async def _has_objects(client: ApiClient, crd: dict[str, Any]) -> bool:
    custom_api = kubeclient.CustomObjectsApi(client)
    objects = await custom_api.list_cluster_custom_object(
        group=crd["spec"]["group"],
        version=_served_version(crd),
        plural=crd["spec"]["names"]["plural"],
        limit=1,
    )
    return bool(objects.get("items"))


async def _wait_until_deleted(api: kubeclient.ApiextensionsV1Api, name: str) -> None:
    deadline = time.monotonic() + _DELETE_TIMEOUT_SECONDS
    while await _read_crd(api, name) is not None:
        if time.monotonic() >= deadline:
            msg = f"CRD {name} was not deleted within {_DELETE_TIMEOUT_SECONDS:.0f}s"
            raise CrdApplyError(msg)
        await asyncio.sleep(_DELETE_POLL_SECONDS)


async def _server_side_apply(
    api: kubeclient.ApiextensionsV1Api, crd: dict[str, Any]
) -> None:
    await api.patch_custom_resource_definition(
        name=crd["metadata"]["name"],
        body=crd,
        field_manager=FIELD_MANAGER,
        force=True,
        _content_type="application/apply-patch+yaml",  # type: ignore[call-arg]
    )


async def apply_crd(client: ApiClient, crd: dict[str, Any]) -> CrdApplyResult:
    """Server-side apply ``crd``; recreate it first when it would drop a stored version.

    A CRD is recreated only when no object of it exists, since deleting a CRD deletes its objects.
    """
    api = kubeclient.ApiextensionsV1Api(client)
    name = crd["metadata"]["name"]
    existing = await _read_crd(api, name)
    removed = removed_stored_versions(existing, crd) if existing is not None else []
    if existing is None or not removed:
        await _server_side_apply(api, crd)
        logger.info("Applied CRD {}", name)
        return CrdApplyResult(name=name, action=CrdApplyAction.APPLIED)

    if await _has_objects(client, existing):
        msg = (
            f"CRD {name} has objects stored in version(s) {', '.join(removed)}, which the new"
            f" CRD no longer lists. Migrate them to version {_served_version(crd)} and remove"
            " the old versions from the CRD's status.storedVersions, then run the upgrade again."
        )
        raise CrdApplyError(msg)
    logger.info(
        "Recreating CRD {}: it has no objects and stored version(s) {}", name, removed
    )
    await api.delete_custom_resource_definition(name=name)
    await _wait_until_deleted(api, name)
    await _server_side_apply(api, crd)
    return CrdApplyResult(name=name, action=CrdApplyAction.RECREATED)


async def apply_crds(
    client: ApiClient, crds: list[dict[str, Any]]
) -> list[CrdApplyResult]:
    return [await apply_crd(client, crd) for crd in crds]
