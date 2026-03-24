from pydantic import BaseModel, ConfigDict


class IngressServiceConfig(BaseModel):
    """Configuration for the ingress controller's Kubernetes Service.

    Attributes:
        annotations: Annotations to add to the Service (e.g., for LB reuse).
        load_balancer_ip: Static IP for the LoadBalancer.
        external_traffic_policy: External traffic policy (Cluster or Local).
    """

    model_config = ConfigDict(extra="forbid")

    annotations: dict[str, str] | None = None
    load_balancer_ip: str | None = None
    external_traffic_policy: str | None = None


class DedicatedIngressConfig(BaseModel):
    """Configuration for a dedicated per-environment ingress controller.

    Attributes:
        implementation: The ingress controller product (e.g., "traefik").
        type: The routing mechanism (e.g., "ingress" for K8s Ingress, future "gateway" for GatewayAPI).
        service: Configuration for the ingress controller's Kubernetes Service.
    """

    model_config = ConfigDict(extra="forbid")

    implementation: str = "traefik"
    type: str = "ingress"
    service: IngressServiceConfig | None = None


class StandardStorage(BaseModel):
    """Standard storage configuration.

    Holds the configuration for the standard storage class in the kubernetes cluster.

    Attributes:
        storage_class (str): The storage class name.
    """

    model_config = ConfigDict(extra="forbid")

    storage_class: str


class BaseConfigSection(BaseModel):
    """Base context section.

    Attributes:
        ingress_class (str): The ingress class name.
        db_size (str): The database size.
        fqdn_suffix (str): The fully qualified domain name suffix.
    """

    model_config = ConfigDict(extra="forbid")

    ingress_class: str | None = None
    db_size: str | None = None
    fqdn_suffix: str | None = None


class ClusterConfig(BaseConfigSection):
    """The Cluster context.

    Attributes:
        runtime_class (str | None): The runtime class.
        node_selector (str | None): The node selector.
        dedicated_ingress (DedicatedIngressConfig | None): The dedicated ingress controller config.
        standard_storage (StandardStorage | None): The standard storage.
    """

    model_config = ConfigDict(extra="forbid")

    runtime_class: str | None = None
    node_selector: str | None = None
    dedicated_ingress: DedicatedIngressConfig | None = None
    standard_storage: StandardStorage | None = None


class EnvironmentConfig(BaseConfigSection):
    """Environment context.

    Holds the environment context information.

    Attributes:
        ip_whitelist (list[str] | None): The IP whitelist.
        dedicated_ingress (DedicatedIngressConfig | None): The dedicated ingress controller config.
    """

    model_config = ConfigDict(extra="forbid")

    ip_whitelist: list[str] | None = None
    dedicated_ingress: DedicatedIngressConfig | None = None


class DeploymentConfig(ClusterConfig, EnvironmentConfig):
    """Deployment context.

    Holds the deployment context information. This section is used to generate the resolved context
    and is not included directly in the global context.

    Attributes:
        ip_whitelist (list[str] | None): The IP whitelist.
    """

    model_config = ConfigDict(extra="forbid")


class ResolvedConfig(DeploymentConfig):
    """The resolved context.

    It is built by merging the cluster, environment and instance contexts with values of the
    righmost data sets overriding the leftmost data sets.
    """

    model_config = ConfigDict(extra="forbid")


class IngressConfig(BaseModel):
    """Ingress configuration.

    Holds the ingress configuration for the application.

    Attributes:
        ingress_class (str): The ingress class name.
        dedicated_ingress (DedicatedIngressConfig | None): The dedicated ingress controller config.
    """

    model_config = ConfigDict(extra="forbid")

    ingress_class: str | None = None
    dedicated_ingress: DedicatedIngressConfig | None = None
