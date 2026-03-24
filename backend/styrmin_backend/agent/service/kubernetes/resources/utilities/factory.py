from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
from styrmin_backend.agent.service.kubernetes.resources.utilities.ingress import (
    IngressUtility,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.service_discovery import (
    ServiceDiscoveryUtility,
)
from styrmin_backend.context.models.contexts import UtilityKind


def load_utilities(utilities: list[UtilityKind]) -> list[Utility]:
    return [build_utility(utility_kind=utility.value) for utility in utilities]


def build_utility(utility_kind: str) -> Utility:
    """Build a utility instance based on the kind.

    Args:
        utility_kind: The kind of the utility.

    Returns:
        The utility instance.
    """
    match utility_kind:
        case "ingress":
            return IngressUtility()
        case "service-discovery":
            return ServiceDiscoveryUtility()
    raise ValueError(f"Unknown utility kind: {utility_kind}")
