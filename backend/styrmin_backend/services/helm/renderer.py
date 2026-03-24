from uuid import UUID

from yaml import safe_load

from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference

from ._environment import get_jinja_environment


def render_helm_repository_spec(
    repository_id: UUID, repository_url: str, repository_type: str = "oci"
) -> dict:
    """Render a Helm Repository specification."""

    # Render the value template using jinja
    template = get_jinja_environment().get_template("repository_spec.j2")
    values = template.render(
        repository_reference=get_kubernetes_reference(repository_id),
        url=repository_url,
        repository_type=repository_type,
    )

    return safe_load(values)


def render_helm_chart_spec(
    helm_chart_id: UUID, name: str, version: str, repository_id: UUID
) -> dict:
    """Render a Helm Chart specification.

    Args:
        helm_chart_id (str): The ID of the Helm chart.
        name (str): The name of the Helm chart.
        version (str): The version of the Helm chart.
        repository_id (str): The ID of the Helm repository.
    """

    # Render the value template using jinja
    template = get_jinja_environment().get_template("chart_spec.j2")
    values = template.render(
        chart_reference=get_kubernetes_reference(helm_chart_id),
        chart_name=name,
        chart_version=version,
        repository_reference=get_kubernetes_reference(repository_id),
    )

    return safe_load(values)
