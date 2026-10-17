"""Read a StyrminDeployment custom resource."""

from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION

from .exceptions import CustomResourceNotFound
from .primitives import get_custom_resource


async def read_styrmin_deployment(*, name: str, namespace: str) -> dict | None:
    """The StyrminDeployment *name* in *namespace*, or None when there is none."""
    try:
        resource = await get_custom_resource(
            plural=CRD_PLURAL,
            name=name,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
        )
    except CustomResourceNotFound:
        return None
    assert isinstance(resource, dict)
    return resource
