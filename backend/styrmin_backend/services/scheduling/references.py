"""Keep the affinity rules that name a deployment pointed at it when it is renamed.

A ``deployment_ref`` may name its target by ``deployment_name``, which
:func:`~styrmin_backend.services.scheduling.validator.resolve_deployment_reference`
looks up in the environment on every reconcile. A rename therefore rewrites
the old name to the new one in every rule of the environment (#492).
"""

from __future__ import annotations

import copy
from typing import Any

from loguru import logger

from styrmin_backend.domain.models import Deployment
from styrmin_backend.services.unit_of_work import UnitOfWork

# The kinds whose terms are expanded by ``expand_deployment_references``.
_REFERENCING_AFFINITY_KINDS = ("pod_affinity", "pod_anti_affinity")


def _affinity_terms(block: Any) -> list[Any]:
    if not isinstance(block, dict):
        return []
    terms = list(block.get("required") or [])
    for weighted in block.get("preferred") or []:
        if isinstance(weighted, dict):
            terms.append(weighted.get("term"))
    return terms


def rename_deployment_references(
    config: dict | None, old_name: str, new_name: str
) -> dict | None:
    """Return a copy of ``config`` whose affinity terms name ``new_name`` instead of ``old_name``.

    Returns ``None`` when no term names ``old_name``, so callers write only the
    configs that change.
    """
    if not isinstance(config, dict) or not isinstance(config.get("scheduling"), dict):
        return None
    renamed = copy.deepcopy(config)
    changed = False
    for kind in _REFERENCING_AFFINITY_KINDS:
        for term in _affinity_terms(renamed["scheduling"].get(kind)):
            ref = term.get("deployment_ref") if isinstance(term, dict) else None
            if isinstance(ref, dict) and ref.get("deployment_name") == old_name:
                ref["deployment_name"] = new_name
                changed = True
    return renamed if changed else None


async def rename_affinity_references(
    uow: UnitOfWork, deployment: Deployment, *, old_name: str
) -> None:
    """Replace ``old_name`` with ``deployment.name`` in the affinity rules of its environment.

    Rewrites the rules of the environment and of every other deployment of the
    environment, and those of ``deployment`` in memory, which the caller saves.
    The rendered rules do not change, because they select the deployment's id.
    """
    new_name = deployment.name
    environment = await uow.environments.get(deployment.environment_id)
    if environment is not None:
        config = rename_deployment_references(environment.config, old_name, new_name)
        if config is not None:
            environment.config = config
            logger.info(
                "Renamed affinity references {!r} -> {!r} in environment {}",
                old_name,
                new_name,
                environment.id,
            )
    for other in await uow.deployments.find_all_by_environment(
        deployment.environment_id
    ):
        if other.id == deployment.id:
            continue
        config = rename_deployment_references(other.config, old_name, new_name)
        if config is not None:
            await uow.deployments.update_config(other.id, config)
            logger.info(
                "Renamed affinity references {!r} -> {!r} in deployment {}",
                old_name,
                new_name,
                other.id,
            )
    config = rename_deployment_references(deployment.config, old_name, new_name)
    if config is not None:
        deployment.config = config
