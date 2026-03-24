from uuid import UUID


def get_kubernetes_reference(resource_id: UUID) -> str:
    """Determine the kubernetes resource name based on its matching counterpart UUID in the database."""

    return f"styrmin-{resource_id}"
