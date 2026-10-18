"""Shared builders for the clone-counterpart ``StyrminDeployment`` CR body.

Not a test module: it exists so the *producer* of a counterpart CR body and its
*consumers* are joined by construction rather than by two hand-written
look-alikes that can drift apart silently.

The producer chain is:

``make_context`` (a counterpart-shaped resolved context: its **own** namespace,
the **source's** adopted Helm release name — 010 research D2)
→ ``_build_counterpart_crd_body`` (workflows/templates/backup.py)
→ ``build_styrmin_deployment_body`` (operator/crd/builder.py)

and the consumer is ``restore_recovery.reapply_with_counterpart_identity``,
which replaces the source-named CR Velero restored into the counterpart's
namespace. Feeding the consumer :func:`build_counterpart_body` means a change to
either end fails a fast test instead of only the 20-minute E2E.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
    Instance,
    InstanceStatus,
)
from styrmin_backend.workflows.templates.backup import _build_counterpart_crd_body

SOURCE_DEPLOYMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
COUNTERPART_DEPLOYMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
CHART_ID = UUID("33333333-3333-3333-3333-333333333333")
REPOSITORY_ID = UUID("44444444-4444-4444-4444-444444444444")

#: The Helm release the source owns — and the one a counterpart adopts.
SOURCE_RELEASE_REFERENCE = f"styrmin-{SOURCE_DEPLOYMENT_ID}"
#: The counterpart's own namespace, which is also its CR name.
COUNTERPART_NAMESPACE = f"styrmin-{COUNTERPART_DEPLOYMENT_ID}"


def make_context(
    *,
    deployment_id: UUID,
    namespace: str,
    release_reference: str,
    instance_id: UUID | None = None,
) -> GlobalContext:
    """A minimal resolved context, parameterised on the two names under test."""
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="rehearsal", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            id=instance_id,
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=release_reference,
        ),
        app=ApplicationContext(
            name="simple-app",
            version="1.6.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=CHART_ID,
                    name="simple-app",
                    version="0.1.0",
                    values_template="name: {{ app.name }}",
                ),
                repository=RepositoryInfo(
                    id=REPOSITORY_ID, url="https://helm.example.com"
                ),
            ),
        ),
        labels={"deployment_id": str(deployment_id)},
        parameters={"license": "ent"},
    )


def counterpart_context(instance_id: UUID | None = None) -> GlobalContext:
    """A clone counterpart's context: own namespace, source's release name."""
    return make_context(
        deployment_id=COUNTERPART_DEPLOYMENT_ID,
        namespace=COUNTERPART_NAMESPACE,
        release_reference=SOURCE_RELEASE_REFERENCE,
        instance_id=instance_id,
    )


class StubDeploymentRepository:
    """Just the one accessor ``_build_counterpart_crd_body`` uses."""

    def __init__(self, deployment: Deployment | None) -> None:
        self._deployment = deployment

    async def find(self, deployment_id: UUID) -> Deployment | None:
        if self._deployment is None or self._deployment.id != deployment_id:
            return None
        return self._deployment


class StubUnitOfWork:
    """``async with uow`` plus ``uow.deployments`` — the helper's whole surface."""

    def __init__(self, deployment: Deployment | None) -> None:
        self.deployments = StubDeploymentRepository(deployment)

    async def __aenter__(self) -> "StubUnitOfWork":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


def counterpart_deployment(
    *, with_instance: bool = True, internal: bool = False
) -> Deployment:
    """A clone counterpart: own namespace, the source's adopted release name."""
    deployment = Deployment(
        id=COUNTERPART_DEPLOYMENT_ID,
        name="infrahub",
        application_version="1.6.0",
        config={},
        parameters={},
        internal=internal,
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        deleted_at=None,
        status=DeploymentState.RESTORING,
        created_by_user_id=uuid4(),
    )
    if with_instance:
        instance_id = uuid4()
        deployment.set_active_instance(
            Instance(
                id=instance_id,
                name="infrahub-instance",
                application_version="1.6.0",
                status=InstanceStatus.RUNNING,
                deployment_id=deployment.id,
                application_driver_version_id=(
                    deployment.application_driver_version_id
                ),
                context=counterpart_context(instance_id),
            )
        )
    return deployment


async def build_counterpart_body(*, internal: bool = False) -> dict[str, Any]:
    """The real ``_build_counterpart_crd_body`` output for a counterpart.

    The single source of truth for "what a counterpart CR body looks like",
    consumed by the post-Velero recovery tests so the fixture they feed the
    consumer cannot drift from what the producer renders.
    """
    deployment = counterpart_deployment(internal=internal)
    counterpart = await _build_counterpart_crd_body(
        deployment_id=deployment.id, uow=StubUnitOfWork(deployment)
    )
    return counterpart.crd_body
