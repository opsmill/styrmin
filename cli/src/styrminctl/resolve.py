"""Resolve a deployment reference to its active application instance.

The backup/restore commands operate on an application *instance*, but
operators think in terms of *deployments*. These helpers turn a deployment
name or id (or a raw instance id escape hatch) into the active instance id,
reusing the existing SDK surface — no backend changes required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from styrmin_sdk import StyrminClient


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


async def _resolve_by_name(sdk: StyrminClient, deployment_name: str, environment: str | None) -> Any:  # noqa: ANN401
    """Find the single deployment matching ``deployment_name``, optionally scoped to ``environment``."""
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
        raise ValueError(f"No deployment named '{deployment_name}'{scope}.")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple deployments named '{deployment_name}' across environments — "
            "narrow the lookup with --environment."
        )
    return matches[0]


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

    if deployment_id is not None:
        deployment = await sdk.deployments.get(deployment_id)
    elif deployment_name is not None:
        deployment = await _resolve_by_name(sdk, deployment_name, environment)
    else:  # pragma: no cover — guaranteed unreachable by _validate_selectors
        raise ValueError("Provide a deployment name, --id, or --instance-id.")

    return ResolvedTarget(instance_id=_active_instance_id(deployment), deployment_id=str(deployment.id))
