from styrmin_sdk.driver_format.context.naming import (  # noqa: F401  re-exported (ADR-0089)
    get_chart_name_from_chart_url,
    get_chart_repository_from_chart_url,
)


def get_helm_repository_type(url: str) -> str:
    """Determine the Flux HelmRepository type from the URL.

    OCI registries use ``oci``, HTTP(S) repositories use ``default``.

    Args:
        url: The repository URL.

    Returns:
        The HelmRepository type string (``oci`` or ``default``).
    """
    if url.startswith("oci://"):
        return "oci"
    return "default"
