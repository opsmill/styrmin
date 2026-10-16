"""Deployment references in the affinity terms of stored configs.

Works on the raw snake_case config dicts that Styrmin stores, not on the Pydantic
models, so that every other key of a config stays as the operator wrote it.
A deployment reference sits at
``scheduling.{pod_affinity,pod_anti_affinity}.required[i].deployment_ref`` or
``scheduling.{pod_affinity,pod_anti_affinity}.preferred[i].term.deployment_ref``.
Node affinity terms select nodes and carry no deployment reference.

:func:`bind_deployment_references` replaces each name with the deployment's id
when a config is written; :func:`remap_deployment_references` points the ids of a
copied config at other deployments (the counterpart deployments of a clone).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, overload
from uuid import UUID

from styrmin_backend.services.exceptions import UnresolvableAffinityReferenceError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from styrmin_backend.services.unit_of_work import UnitOfWork

_POD_AFFINITY_KINDS = ("pod_affinity", "pod_anti_affinity")


@dataclass(frozen=True)
class ReferenceSite:
    """One deployment reference in a config, with the path of its affinity term."""

    path: str
    deployment_ref: dict[str, Any]


def iter_reference_sites(
    config: dict[str, Any] | None, path_prefix: str
) -> Iterator[ReferenceSite]:
    """Yield every deployment reference in ``config``, in document order.

    Paths read ``<path_prefix>.scheduling.pod_affinity.required[0]`` or
    ``<path_prefix>.scheduling.pod_anti_affinity.preferred[1].term``. The yielded
    dicts are the ones inside ``config``: changing them changes ``config``.
    """
    if not isinstance(config, dict):
        return
    scheduling = config.get("scheduling")
    if not isinstance(scheduling, dict):
        return
    base = f"{path_prefix}.scheduling" if path_prefix else "scheduling"
    for kind in _POD_AFFINITY_KINDS:
        block = scheduling.get(kind)
        if not isinstance(block, dict):
            continue
        required = block.get("required")
        if isinstance(required, list):
            for idx, term in enumerate(required):
                ref = term.get("deployment_ref") if isinstance(term, dict) else None
                if isinstance(ref, dict):
                    yield ReferenceSite(
                        path=f"{base}.{kind}.required[{idx}]", deployment_ref=ref
                    )
        preferred = block.get("preferred")
        if isinstance(preferred, list):
            for idx, weighted in enumerate(preferred):
                term = weighted.get("term") if isinstance(weighted, dict) else None
                ref = term.get("deployment_ref") if isinstance(term, dict) else None
                if isinstance(ref, dict):
                    yield ReferenceSite(
                        path=f"{base}.{kind}.preferred[{idx}].term", deployment_ref=ref
                    )


def referenced_deployment_ids(
    config: dict[str, Any] | None, path_prefix: str
) -> dict[UUID, list[str]]:
    """Map each deployment id that ``config`` names to the paths of the terms that name it.

    For bound configs: a reference that gives a name and no id is left out.
    """
    found: dict[UUID, list[str]] = {}
    for site in iter_reference_sites(config, path_prefix):
        raw_id = site.deployment_ref.get("deployment_id")
        if raw_id is not None:
            found.setdefault(UUID(str(raw_id)), []).append(site.path)
    return found


def remap_deployment_references(
    config: dict[str, Any] | None,
    mapping: Mapping[UUID, UUID],
    *,
    path_prefix: str = "",
) -> tuple[dict[str, Any] | None, dict[UUID, list[str]]]:
    """Return a copy of ``config`` with each referenced id replaced by ``mapping[id]``.

    The second value maps each id that has no entry in ``mapping`` to the paths of
    the terms that name it; those references keep their id. ``config`` is not changed.
    """
    if config is None:
        return None, {}
    remapped = copy.deepcopy(config)
    unmapped: dict[UUID, list[str]] = {}
    for site in iter_reference_sites(remapped, path_prefix):
        raw_id = site.deployment_ref.get("deployment_id")
        if raw_id is None:
            continue
        source_id = UUID(str(raw_id))
        target_id = mapping.get(source_id)
        if target_id is None:
            unmapped.setdefault(source_id, []).append(site.path)
        else:
            site.deployment_ref["deployment_id"] = str(target_id)
    return remapped, unmapped


@overload
async def bind_deployment_references(
    uow: UnitOfWork,
    environment_id: UUID | None,
    config: dict[str, Any],
    *,
    path_prefix: str,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> dict[str, Any]: ...


@overload
async def bind_deployment_references(
    uow: UnitOfWork,
    environment_id: UUID | None,
    config: dict[str, Any] | None,
    *,
    path_prefix: str,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> dict[str, Any] | None: ...


async def bind_deployment_references(
    uow: UnitOfWork,
    environment_id: UUID | None,
    config: dict[str, Any] | None,
    *,
    path_prefix: str,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> dict[str, Any] | None:
    """Return a copy of ``config`` in which each deployment reference gives an id only.

    ``upcoming_deployments`` maps the deployments that the current write creates or
    renames to their names after the write. ``environment_id=None`` means the
    environment does not exist yet, so only upcoming deployments match. The first
    term that names no live deployment of the environment raises
    :class:`UnresolvableAffinityReferenceError` with the term's path.
    A config without deployment references is returned as it is.

    Call it inside the caller's open unit of work. It opens none of its own, so a
    refusal inside a caller's savepoint rolls back only that savepoint.
    """
    if config is None or next(iter_reference_sites(config, path_prefix), None) is None:
        return config
    upcoming = dict(upcoming_deployments or {})
    upcoming_by_name = {name: deployment_id for deployment_id, name in upcoming.items()}
    bound = copy.deepcopy(config)
    for site in iter_reference_sites(bound, path_prefix):
        ref = site.deployment_ref
        target_id = await _bind_reference(
            uow, environment_id, ref, site.path, upcoming, upcoming_by_name
        )
        components = ref.get("components")
        ref.clear()
        ref["deployment_id"] = str(target_id)
        if components is not None:
            ref["components"] = components
    return bound


async def _bind_reference(
    uow: UnitOfWork,
    environment_id: UUID | None,
    ref: dict[str, Any],
    path: str,
    upcoming: Mapping[UUID, str],
    upcoming_by_name: Mapping[str, UUID],
) -> UUID:
    raw_id = ref.get("deployment_id")
    if raw_id is not None:
        return await _bind_id(uow, environment_id, raw_id, path, upcoming)
    name = ref.get("deployment_name")
    if name is None:
        raise UnresolvableAffinityReferenceError(path=path)
    if name in upcoming_by_name:
        return upcoming_by_name[name]
    if environment_id is not None:
        target = await uow.deployments.get_by_name(name, environment_id)
        # A row found under a name that the same write changes is not a match.
        if target is not None and target.id not in upcoming:
            return target.id
    raise UnresolvableAffinityReferenceError(deployment_name=name, path=path)


async def _bind_id(
    uow: UnitOfWork,
    environment_id: UUID | None,
    raw_id: object,
    path: str,
    upcoming: Mapping[UUID, str],
) -> UUID:
    try:
        target_id = UUID(str(raw_id))
    except ValueError:
        raise UnresolvableAffinityReferenceError(
            deployment_id=str(raw_id), path=path
        ) from None
    if target_id in upcoming:
        return target_id
    target = (
        await uow.deployments.find(target_id) if environment_id is not None else None
    )
    if target is None or target.environment_id != environment_id:
        raise UnresolvableAffinityReferenceError(
            deployment_id=str(target_id), path=path
        )
    if target.deleted_at is not None:
        raise UnresolvableAffinityReferenceError(
            deployment_id=str(target.id),
            deployment_name=target.name,
            path=path,
            deleted=True,
        )
    return target.id
