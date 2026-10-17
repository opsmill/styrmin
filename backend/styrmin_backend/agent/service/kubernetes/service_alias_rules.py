"""Labels and rules of service aliases that the alias flow and the operator share (#503).

This module imports no Prefect code, so the operator's teardown can import it.
"""

from kubernetes_asyncio.client import V1Namespace, V1Service

SERVICE_ALIAS_LABEL = "styrmin.io/service-alias"
DEPLOYMENT_ID_LABEL = "styrmin.io/deployment-id"


def is_alias_of_deployment(
    alias: V1Service, deployment_id: str, namespace: str
) -> bool:
    """Whether *alias* is for a service of the deployment *deployment_id*.

    Aliases created before the id label point into the deployment's *namespace*.
    """
    labels = alias.metadata.labels or {}
    if DEPLOYMENT_ID_LABEL in labels:
        return labels[DEPLOYMENT_ID_LABEL] == deployment_id
    external_name = (alias.spec.external_name if alias.spec else None) or ""
    return external_name.split(".")[1:2] == [namespace]


def is_gone_or_terminating(namespace: V1Namespace | None) -> bool:
    return namespace is None or (
        namespace.status is not None and namespace.status.phase == "Terminating"
    )


def teardown_deletes_aliases(
    *, deletion_requested: bool, namespace: V1Namespace | None
) -> bool:
    """Whether deleting a StyrminDeployment deletes the aliases of its deployment's services.

    Without a deletion request, a namespace that is gone or terminating keeps them: a restore
    deletes the namespace in this way, and the restored deployment keeps running (FR-017).
    """
    return deletion_requested or not is_gone_or_terminating(namespace)
