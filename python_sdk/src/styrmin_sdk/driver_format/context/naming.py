"""Names that Styrmin derives for a deployment: Kubernetes references and Helm chart names."""

from uuid import UUID


def get_kubernetes_reference(resource_id: UUID) -> str:
    """Determine the kubernetes resource name based on its matching counterpart UUID in the database."""

    return f"styrmin-{resource_id}"


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
