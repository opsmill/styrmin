"""Validators for the scheduling feature.

Hosts cross-cutting validation that cannot be expressed as a Pydantic field
validator: component-name validation against driver-declared components and
deployment-reference expansion for affinity-by-reference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    DeploymentReference,
    LabelSelector,
    LabelSelectorRequirement,
    SchedulingConfig,
    WeightedAffinityTerm,
)
from styrmin_backend.services.exceptions import (
    UnresolvableAffinityReferenceError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEPLOYMENT_ID_LABEL = "styrmin/deployment_id"
_COMPONENT_LABEL = "styrmin/component"


async def resolve_deployment_reference(
    uow: UnitOfWork,
    environment_id: UUID,
    ref: DeploymentReference,
    path: str | None = None,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> LabelSelector:
    """Expand a :class:`DeploymentReference` into a Kubernetes label selector.

    Uses the platform-generated ``styrmin/deployment_id`` identity label
    stamped on every pod template (see ``generate_context_from_deployment``).
    Narrowing by ``ref.components`` adds a ``styrmin/component`` ``In``
    ``matchExpressions`` requirement.

    Stored references give an id only, because the write that stores a config
    replaces each name with an id. An id in ``upcoming_deployments`` (the
    deployments that the current operation creates) is accepted without a
    lookup. Raises :class:`UnresolvableAffinityReferenceError` for a reference
    that gives a name, an id that is not a deployment of the caller's
    environment, or a tombstoned deployment (``deleted=True``, with its last
    name). Re-evaluated on every reconciliation (we do not cache the selector).
    """
    async with uow:
        if ref.deployment_id is None:
            raise UnresolvableAffinityReferenceError(
                deployment_name=ref.deployment_name, path=path
            )
        target_id = ref.deployment_id
        if target_id not in (upcoming_deployments or {}):
            target = await uow.deployments.find(target_id)
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

    match_expressions: list[LabelSelectorRequirement] | None = (
        [
            LabelSelectorRequirement(
                key=_COMPONENT_LABEL,
                operator="In",
                values=list(ref.components),
            )
        ]
        if ref.components
        else None
    )
    return LabelSelector(
        match_labels={_DEPLOYMENT_ID_LABEL: str(target_id)},
        match_expressions=match_expressions,
    )


async def _expand_term(
    uow: UnitOfWork,
    environment_id: UUID,
    term: AffinityTerm,
    path: str,
    upcoming_deployments: Mapping[UUID, str] | None,
) -> AffinityTerm:
    if term.deployment_ref is None:
        return term
    label_selector = await resolve_deployment_reference(
        uow,
        environment_id,
        term.deployment_ref,
        path=path,
        upcoming_deployments=upcoming_deployments,
    )
    return AffinityTerm(
        topology_key=term.topology_key,
        namespaces=term.namespaces,
        namespace_selector=term.namespace_selector,
        label_selector=label_selector,
        deployment_ref=None,
        match_label_keys=term.match_label_keys,
        mismatch_label_keys=term.mismatch_label_keys,
    )


async def _expand_affinity_block(
    uow: UnitOfWork,
    environment_id: UUID,
    block: AffinityBlock | None,
    path_prefix: str,
    upcoming_deployments: Mapping[UUID, str] | None,
) -> AffinityBlock | None:
    if block is None:
        return None
    required: list[AffinityTerm] = []
    for idx, term in enumerate(block.required):
        required.append(
            await _expand_term(
                uow,
                environment_id,
                term,
                path=f"{path_prefix}.required[{idx}]",
                upcoming_deployments=upcoming_deployments,
            )
        )
    preferred: list[WeightedAffinityTerm] = []
    for idx, weighted in enumerate(block.preferred):
        expanded_term = await _expand_term(
            uow,
            environment_id,
            weighted.term,
            path=f"{path_prefix}.preferred[{idx}].term",
            upcoming_deployments=upcoming_deployments,
        )
        preferred.append(
            WeightedAffinityTerm(weight=weighted.weight, term=expanded_term)
        )
    return AffinityBlock(required=required, preferred=preferred, replace=block.replace)


async def expand_deployment_references(
    uow: UnitOfWork,
    environment_id: UUID,
    config: SchedulingConfig,
    *,
    path_prefix: str = "scheduling",
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> SchedulingConfig:
    """Return a new :class:`SchedulingConfig` with every ``deployment_ref`` in
    pod-affinity and pod-anti-affinity terms replaced by its resolved
    ``label_selector``. Node-affinity terms do not carry deployment refs
    (they select against node labels), so they are passed through unchanged.

    ``path_prefix`` is the path of ``config`` itself, for example
    ``environment.config.scheduling``; error paths read
    ``<path_prefix>.pod_affinity.required[0]``.
    """
    pod_affinity = await _expand_affinity_block(
        uow,
        environment_id,
        config.pod_affinity,
        f"{path_prefix}.pod_affinity",
        upcoming_deployments,
    )
    pod_anti_affinity = await _expand_affinity_block(
        uow,
        environment_id,
        config.pod_anti_affinity,
        f"{path_prefix}.pod_anti_affinity",
        upcoming_deployments,
    )
    return SchedulingConfig(
        pod_affinity=pod_affinity,
        pod_anti_affinity=pod_anti_affinity,
        node_affinity=config.node_affinity,
        topology_spread_constraints=config.topology_spread_constraints,
        resources=config.resources,
        tolerations=config.tolerations,
        runtime_class=config.runtime_class,
        inject=config.inject,
    )
