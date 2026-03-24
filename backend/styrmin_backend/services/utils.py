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


def get_chart_name_from_chart_url(chart_url: str) -> str:
    """Get the chart name from the chart url.

    Example:
        >>> get_chart_name_from_chart_url("https://test.com/test_chart")
        "test_chart"
        >>> get_chart_name_from_chart_url("https://test.com/test_chart/")
        "test_chart"

    Args:
        chart_url (str): The chart url.

    Returns:
        str: The chart name.
    """
    return chart_url.rstrip("/").split("/")[-1]


def get_chart_repository_from_chart_url(chart_url: str) -> str:
    """Get the chart repository from the chart url.

    Args:
        chart_url (str): The chart url.

    Returns:
        str: The chart repository.
    """
    return "/".join(chart_url.rstrip("/").split("/")[:-1])
