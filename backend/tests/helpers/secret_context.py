"""A context that holds fake secrets where users and drivers put real ones (#573).

The values template is the Infrahub example driver's, which writes the Prefect
database password and the Erlang cookie of the message queue. The env vars and
the parameter are set at each scope that a user can set.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from styrmin_backend.context.models.config import (
    ClusterConfig,
    ComponentConfigBlock,
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

INFRAHUB_VALUES_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "driver"
    / "examples"
    / "infrahub"
    / "values.j2.yml"
).read_text()

#: The secrets of the Infrahub values template.
TEMPLATE_SECRETS = ("prefect-opsmill", "styrmin-infrahub-supersecret")


def secret_context(
    *,
    env_secret: str = "FAKE573-env-pw",
    plain_secret: str = "FAKE573-plain-value",
    parameter_secret: str = "FAKE573-param-pw",
    deployment_id: UUID | None = None,
    instance_id: UUID | None = None,
) -> GlobalContext:
    """A context whose env vars, parameters and values template hold secrets.

    ``plain_secret`` is the value of an env var whose name does not say it is a
    secret, so only code that leaves the values out keeps it out of a log.
    """
    env_vars = {"APP_ADMIN_PASSWORD": env_secret, "PLAIN_SETTING": plain_secret}
    component = ComponentConfigBlock(env_vars=env_vars)
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(
            name="local", config=EnvironmentConfig(env_vars=env_vars)
        ),
        deployment=DeploymentContext(
            config=DeploymentConfig(env_vars=env_vars, components={"app": component})
        ),
        instance=InstanceContext(
            id=instance_id or uuid4(),
            config=ResolvedConfig(env_vars=env_vars, components={"app": component}),
            deployment_id=deployment_id or uuid4(),
            namespace="styrmin-ns",
            release_reference="styrmin-rel",
        ),
        app=ApplicationContext(
            name="infrahub",
            version="1.11.7",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="infrahub",
                    version="4.0.0",
                    values_template=INFRAHUB_VALUES_TEMPLATE,
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        parameters={"admin_password": parameter_secret},
    )
