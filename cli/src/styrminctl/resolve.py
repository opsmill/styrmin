"""Resolve a deployment reference to its id or to its active application instance.

The backup/restore commands operate on an application *instance* or on a
deployment's backup history, but operators think in terms of *deployments*.
These helpers turn a deployment name or id (or a raw instance id escape hatch)
into the deployment id or the active instance id, reusing the existing SDK
surface — no backend changes required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from styrmin_sdk import StyrminClient


#: Appended when a lookup by name finds nothing: a deleted deployment is reached by id only.
DELETED_DEPLOYMENT_HINT = (
    " The lookup by name does not find a deleted deployment: to list a deleted deployment's"
    " backup history, pass its deployment id with --id."
)


@dataclass(frozen=True)
class ResolvedTarget:
    """The outcome of resolving a deployment reference.

    ``deployment_id`` is ``None`` when the caller targeted a raw instance id
    directly (the escape hatch), in which case no deployment context is known.
    """

    instance_id: str
    deployment_id: str | None


def _active_instance_id(deployment: Any) -> str:  # noqa: ANN401
    """Return the active instance id of a deployment, or raise if there is none."""
    instance = deployment.application_instance
    if instance is None:
        raise ValueError(f"Deployment '{deployment.name}' has no active instance — it may not be running yet.")
    return str(instance.id)


def _validate_selectors(
    deployment_name: str | None,
    deployment_id: str | None,
    instance_id: str | None,
    environment: str | None,
) -> None:
    """Ensure exactly one target selector is set and ``--environment`` is used correctly."""
    selectors = [s for s in (instance_id, deployment_id, deployment_name) if s is not None]
    if len(selectors) == 0:
        raise ValueError("Provide a deployment name, --id, or --instance-id.")
    if len(selectors) > 1:
        raise ValueError("Provide only one of a deployment name, --id, or --instance-id.")
    if environment is not None and deployment_name is None:
        raise ValueError("--environment only applies when looking up a deployment by name.")


async def _resolve_by_name(
    sdk: StyrminClient,
    deployment_name: str,
    environment: str | None,
    not_found_hint: str = "",
) -> Any:  # noqa: ANN401
    """Find the single deployment matching ``deployment_name``, optionally scoped to ``environment``.

    ``not_found_hint`` is appended to the error when no deployment matches.
    """
    environments = await sdk.environments.list()
    if environment is not None:
        environments = [e for e in environments if e.name == environment]
        if not environments:
            raise ValueError(f"No environment named '{environment}'.")

    matches = []
    for env in environments:
        for deployment in await sdk.deployments.list(env.id):
            if deployment.name == deployment_name:
                matches.append(deployment)

    if not matches:
        scope = f" in environment '{environment}'" if environment else ""
        raise ValueError(f"No deployment named '{deployment_name}'{scope}.{not_found_hint}")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple deployments named '{deployment_name}' across environments — "
            "narrow the lookup with --environment."
        )
    return matches[0]


async def _find_deployment(
    sdk: StyrminClient,
    deployment_name: str | None,
    deployment_id: str | None,
    environment: str | None,
    not_found_hint: str = "",
) -> Any:  # noqa: ANN401
    """Fetch the deployment selected by ``deployment_id`` or ``deployment_name``."""
    if deployment_id is not None:
        return await sdk.deployments.get(deployment_id)
    if deployment_name is not None:
        return await _resolve_by_name(sdk, deployment_name, environment, not_found_hint)
    # Unreachable after _validate_selectors.
    raise ValueError("Provide a deployment name, --id, or --instance-id.")  # pragma: no cover


async def resolve_deployment_id(
    sdk: StyrminClient,
    *,
    deployment_name: str | None,
    deployment_id: str | None,
    environment: str | None,
    not_found_hint: str = DELETED_DEPLOYMENT_HINT,
) -> str:
    """Resolve a deployment name or id to the deployment's id.

    Exactly one of ``deployment_id`` or ``deployment_name`` must be provided;
    ``environment`` only applies to the name lookup. Unlike
    :func:`resolve_active_instance`, the deployment does not need an active
    instance. ``deployment_id`` also reaches a deleted deployment, which the
    name lookup does not list. ``not_found_hint`` is appended to the error
    when no deployment has the name.
    """
    _validate_selectors(deployment_name, deployment_id, None, environment)
    deployment = await _find_deployment(sdk, deployment_name, deployment_id, environment, not_found_hint=not_found_hint)
    return str(deployment.id)


async def resolve_active_instance(
    sdk: StyrminClient,
    *,
    deployment_name: str | None = None,
    deployment_id: str | None = None,
    instance_id: str | None = None,
    environment: str | None = None,
) -> ResolvedTarget:
    """Resolve a target application instance from a deployment reference.

    Exactly one of ``instance_id``, ``deployment_id`` or ``deployment_name``
    must be provided. ``environment`` only applies to the name lookup and
    disambiguates deployments that share a name across environments.
    """
    _validate_selectors(deployment_name, deployment_id, instance_id, environment)

    # Escape hatch: a raw instance id is used as-is.
    if instance_id is not None:
        return ResolvedTarget(instance_id=instance_id, deployment_id=None)

    deployment = await _find_deployment(sdk, deployment_name, deployment_id, environment)
    return ResolvedTarget(instance_id=_active_instance_id(deployment), deployment_id=str(deployment.id))


async def resolve_environment_id(
    sdk: StyrminClient,
    *,
    name: str | None,
    environment_id: str | None,
    cluster: str,
    cluster_id: str | None,
) -> str:
    """Resolve an environment to its UUID from a name (cluster-scoped) or ``--id``.

    The environment-level mutations and queries that take a UUID only
    (``createEnvironmentBackup``, ``environmentBackups``, ``environmentClones``)
    need this; the name lookup goes through the ``environment`` query — which is
    where the ADR-0031 dual-identifier resolution actually lives (server-side,
    with the cluster scoping rules). The CLI never reimplements the name
    matching.

    Raises ``ValueError`` on any invalid identifier combination.
    """
    if name is not None and environment_id is not None:
        raise ValueError("Provide either an environment name or --id, not both")
    if name is None and environment_id is None:
        raise ValueError("Either an environment name or --id is required")
    if cluster_id is not None and cluster != "default":
        raise ValueError("Provide either --cluster or --cluster-id, not both")

    if environment_id is not None:
        return environment_id

    environment = await sdk.environments.get(
        environment_name=name,
        cluster_id=cluster_id,
        cluster_name=cluster if cluster_id is None else None,
    )
    return str(environment.id)
