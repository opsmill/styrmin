"""Ordered deployment pipeline for StyrminDeployment CRDs.

Implements the three-phase deployment sequence:
  Phase 1: NetworkPolicies + Secrets (prerequisites)
  Phase 2: HelmRelease (blocked until phase 1 complete)
  Phase 3: Services + Middlewares (blocked until phase 2 complete)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_resource,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.operator.crd.schema import (
    ConditionType,
)
from styrmin_backend.operator.crd.status import is_condition_true
from styrmin_backend.operator.state import (
    build_desired_resources,
)

logger = logging.getLogger(__name__)

_PREREQUISITE_KINDS = {"NetworkPolicy", "Secret"}
_SERVICE_KINDS = {"Service"}
_MIDDLEWARE_API_PREFIX = "traefik"


@dataclass
class PhaseResult:
    """Result of a pipeline phase execution."""

    success: bool = True
    errors: list[str] = field(default_factory=list)
    created_count: int = 0
    resource_details: dict[str, int] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.success = False


def build_desired_resources_from_crd(
    crd_spec: dict[str, Any],
    namespace: str,
) -> list[dict[str, Any]]:
    """Build desired resources from a StyrminDeployment CRD spec.

    Deserializes the GlobalContext from the CRD spec and uses the
    existing utility resource builders to compute desired resources.
    """
    context_data = crd_spec.get("context", {})
    release_reference = crd_spec.get("releaseReference", "")

    try:
        context = GlobalContext.model_validate(context_data)
    except Exception:
        logger.exception("Failed to deserialize GlobalContext from CRD spec")
        raise

    return build_desired_resources(
        context=context,
        release_reference=release_reference,
        namespace=namespace,
    )


def _is_prerequisite(resource: dict[str, Any]) -> bool:
    """Check if a resource is a prerequisite (NetworkPolicy or Secret)."""
    return resource.get("kind") in _PREREQUISITE_KINDS


def _is_service_or_middleware(resource: dict[str, Any]) -> bool:
    """Check if a resource is a Service or Middleware (post-HelmRelease phase)."""
    kind = resource.get("kind", "")
    api_version = resource.get("apiVersion", "")
    return kind == "Service" or _MIDDLEWARE_API_PREFIX in api_version


async def execute_phase_prerequisites(
    crd_spec: dict[str, Any],
    namespace: str,
) -> PhaseResult:
    """Phase 1: Create NetworkPolicies and Secrets.

    Returns a PhaseResult indicating success/failure with details.
    """
    result = PhaseResult()

    try:
        all_resources = build_desired_resources_from_crd(crd_spec, namespace)
    except Exception as exc:
        result.add_error(f"Failed to build desired resources: {exc}")
        return result

    prerequisites = [r for r in all_resources if _is_prerequisite(r)]

    netpol_count = 0
    secret_count = 0

    for resource in prerequisites:
        kind = resource.get("kind", "")
        name = resource.get("metadata", {}).get("name", "")
        try:
            await apply_kubernetes_resource(resource=resource, namespace=namespace)
            result.created_count += 1
            if kind == "NetworkPolicy":
                netpol_count += 1
            elif kind == "Secret":
                secret_count += 1
            logger.info("Applied %s/%s in %s", kind, name, namespace)
        except Exception as exc:
            result.add_error(f"Failed to apply {kind}/{name}: {exc}")
            logger.error("Failed to apply %s/%s: %s", kind, name, exc)

    result.resource_details = {
        "networkPolicies": netpol_count,
        "secrets": secret_count,
    }
    return result


async def execute_phase_helmrelease(
    crd_spec: dict[str, Any],
    namespace: str,
) -> PhaseResult:
    """Phase 2: Create Flux source objects and the HelmRelease.

    Creates the HelmRepository and HelmChart in the styrmin namespace
    (Flux source objects are cluster-scoped resources), then creates
    the HelmRelease in the deployment namespace.
    """
    from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
        ApplicationHelmReleaseBuilder,
    )
    from styrmin_backend.agent.service.kubernetes.resources.utilities.factory import (
        load_utilities,
    )

    result = PhaseResult()

    try:
        context_data = crd_spec.get("context", {})
        context = GlobalContext.model_validate(context_data)
        helm = context.app.helm
    except Exception as exc:
        result.add_error(f"Failed to deserialize context: {exc}")
        logger.error("Failed to deserialize context: %s", exc)
        return result

    from styrmin_backend.agent.service.kubernetes.primitives import (
        upsert_custom_resource,
    )
    from styrmin_backend.services.helm.renderer import (
        render_helm_chart_spec,
        render_helm_repository_spec,
    )
    from styrmin_backend.services.utils import get_helm_repository_type

    # Step 1: Create HelmRepository in styrmin namespace
    try:
        helm_repo_spec = render_helm_repository_spec(
            repository_id=helm.repository.id,
            repository_url=helm.repository.url,
            repository_type=get_helm_repository_type(helm.repository.url),
        )
        await upsert_custom_resource(
            plurals="helmrepositories",
            body=helm_repo_spec,
            group="source.toolkit.fluxcd.io",
            version="v1",
            namespace="styrmin",
        )
        logger.info("Created HelmRepository for %s", helm.repository.url)
    except Exception as exc:
        result.add_error(f"Failed to create HelmRepository: {exc}")
        logger.error("Failed to create HelmRepository: %s", exc)
        return result

    # Step 2: Create HelmChart in styrmin namespace
    try:
        helm_chart_spec = render_helm_chart_spec(
            helm_chart_id=helm.chart.id,
            name=helm.chart.name,
            version=helm.chart.version,
            repository_id=helm.repository.id,
        )
        await upsert_custom_resource(
            plurals="helmcharts",
            body=helm_chart_spec,
            group="source.toolkit.fluxcd.io",
            version="v1",
            namespace="styrmin",
        )
        logger.info("Created HelmChart %s:%s", helm.chart.name, helm.chart.version)
    except Exception as exc:
        result.add_error(f"Failed to create HelmChart: {exc}")
        logger.error("Failed to create HelmChart: %s", exc)
        return result

    # Step 3: Create HelmRelease in deployment namespace
    try:
        builder = ApplicationHelmReleaseBuilder(context=context)
        utility_kinds = [u.kind for u in context.utilities]
        utilities = load_utilities(utility_kinds)
        helm_release = builder.build(utilities=utilities)
        release_spec = helm_release.render()

        await upsert_custom_resource(
            plurals="helmreleases",
            body=release_spec,
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace=namespace,
        )
        logger.info(
            "Created HelmRelease %s in %s",
            context.instance.release_reference,
            namespace,
        )
    except Exception as exc:
        result.add_error(f"Failed to create HelmRelease: {exc}")
        logger.error("Failed to create HelmRelease: %s", exc)
        return result

    result.created_count = 3
    result.resource_details = {"helmRepositories": 1, "helmCharts": 1, "helmReleases": 1}
    return result


async def execute_phase_services(
    crd_spec: dict[str, Any],
    namespace: str,
) -> PhaseResult:
    """Phase 3: Create Services and Middlewares.

    These are created after the HelmRelease is Ready.
    """
    result = PhaseResult()

    try:
        all_resources = build_desired_resources_from_crd(crd_spec, namespace)
    except Exception as exc:
        result.add_error(f"Failed to build desired resources: {exc}")
        return result

    services_and_middlewares = [
        r for r in all_resources if _is_service_or_middleware(r)
    ]

    service_count = 0
    middleware_count = 0

    for resource in services_and_middlewares:
        kind = resource.get("kind", "")
        name = resource.get("metadata", {}).get("name", "")
        try:
            await apply_kubernetes_resource(resource=resource, namespace=namespace)
            result.created_count += 1
            if kind == "Service":
                service_count += 1
            else:
                middleware_count += 1
            logger.info("Applied %s/%s in %s", kind, name, namespace)
        except Exception as exc:
            result.add_error(f"Failed to apply {kind}/{name}: {exc}")
            logger.error("Failed to apply %s/%s: %s", kind, name, exc)

    result.resource_details = {
        "services": service_count,
        "middlewares": middleware_count,
    }
    return result


def should_proceed_to_helmrelease(conditions: list[dict[str, str]]) -> bool:
    """Check if phase 1 (prerequisites) is complete and phase 2 can begin."""
    return is_condition_true(
        conditions, ConditionType.NETWORK_POLICIES_READY
    ) and is_condition_true(conditions, ConditionType.SECRETS_READY)


def should_proceed_to_services(conditions: list[dict[str, str]]) -> bool:
    """Check if phase 2 (HelmRelease) is complete and phase 3 can begin."""
    return should_proceed_to_helmrelease(conditions) and is_condition_true(
        conditions, ConditionType.HELM_RELEASE_READY
    )
