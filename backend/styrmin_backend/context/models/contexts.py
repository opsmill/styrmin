from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .components import ComponentsContext
from .config import ClusterConfig, DeploymentConfig, EnvironmentConfig, ResolvedConfig
from .helm import HelmInfo


class ApplicationContext(BaseModel):
    """Application context.

    Holds the application context information.

    Attributes:
        name (str): The application name.
        version (str): The application version.
        helm (HelmInfo): Helm information for the application (repository, chart, version).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    helm: HelmInfo


class ClusterContext(BaseModel):
    """Cluster context.

    Holds the cluster context information, that may be overridden by the environment context or the deployment context.
    """

    model_config = ConfigDict(extra="forbid")

    config: ClusterConfig
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _drop_rejected_scheduling(cls, data: Any) -> Any:  # noqa: ANN401
        # Contexts stored before #482 can hold the cluster's scheduling value, which no pod got.
        if not isinstance(data, dict) or not isinstance(data.get("config"), dict):
            return data
        config = data["config"]
        if "scheduling" not in config:
            return data
        return {
            **data,
            "config": {k: v for k, v in config.items() if k != "scheduling"},
        }


class EnvironmentContext(BaseModel):
    """Environment context.

    Holds the environment context information, that may be overridden by the deployment context.

    Attributes:
        name (str): The environment name.
        config (EnvironmentConfig): The environment configuration.
        capabilities (dict): Hierarchical capability declarations for this environment.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    config: EnvironmentConfig
    capabilities: dict[str, Any] = Field(default_factory=dict)


class DeploymentContext(BaseModel):
    """Deployment context.

    Holds the deployment context information, which may override the environment and cluster contexts.
    """

    model_config = ConfigDict(extra="forbid")

    config: DeploymentConfig


class InstanceContext(BaseModel):
    """Instance context.

    Holds the instance context information, which is derived from the deployment context and includes the resolved configuration.

    Attributes:
        config (ResolvedConfig): The configuration for the instance, resolved from the deployment, environment, and cluster contexts.
        id (UUID): The unique identifier for the application instance this context
            represents. Used to correlate CRD status reports back to the specific
            instance that was active when the CRD was written.
        deployment_id (UUID): The unique identifier for the deployment.
        namespace (str): The namespace for the instance.
        release_reference (str): The reference of the helm release resource on the Kubernetes cluster.
    """

    model_config = ConfigDict(extra="forbid")

    config: ResolvedConfig

    id: UUID | None = None
    deployment_id: UUID
    namespace: str
    release_reference: str


class UtilityKind(str, Enum):
    INGRESS = "ingress"
    SERVICE_DISCOVERY = "service-discovery"


class UtilityContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: UtilityKind


class GlobalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: ClusterContext
    environment: EnvironmentContext
    deployment: DeploymentContext
    instance: InstanceContext
    app: ApplicationContext
    labels: dict[str, Any] = Field(default_factory=dict)
    components: ComponentsContext | None = None
    utilities: list[UtilityContext] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    services: dict[str, Any] = Field(default_factory=dict)
    deployed_services: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _drop_removed_node_selector(cls, data: Any) -> Any:
        # StyrminDeployment resources written before #472 still carry node_selector.
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for scope in ("cluster", "deployment", "instance"):
            section = data.get(scope)
            if isinstance(section, dict) and isinstance(section.get("config"), dict):
                config = section["config"]
                if "node_selector" in config:
                    config = {k: v for k, v in config.items() if k != "node_selector"}
                    data[scope] = {**section, "config": config}
        return data
