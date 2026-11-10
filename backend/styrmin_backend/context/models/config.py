import re
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)


class IngressServiceConfig(BaseModel):
    """Configuration for the ingress controller's Kubernetes Service.

    Attributes:
        type: The Kubernetes Service type (e.g., "LoadBalancer", "ClusterIP", "NodePort").
        annotations: Annotations to add to the Service (e.g., for LB reuse).
        load_balancer_ip: Static IP for the LoadBalancer.
        external_traffic_policy: External traffic policy (Cluster or Local).
        ip_families: Optional list pinning the Service to specific IP families.
            Use ``["IPv6"]`` + ``ip_family_policy="SingleStack"`` to publish a
            v6-only Service on a dual-stack cluster. Set ``["IPv4", "IPv6"]``
            with ``RequireDualStack`` only when the cluster has both families
            configured; ``PreferDualStack`` opts into dual-stack with
            single-family fallback.
        ip_family_policy: Service dual-stack policy. One of ``"SingleStack"``,
            ``"PreferDualStack"``, ``"RequireDualStack"``.
        node_port: Fixed NodePort applied to the Traefik ``websecure``
            entrypoint (HTTPS). Only meaningful when ``type == "NodePort"``.
            Pinned to ``websecure`` only — Kubernetes does not allow two
            ports on the same Service to share a ``nodePort``, and the
            Cloudflare/Infrahub recipe terminates TLS at the cluster, so
            ``websecure`` is the entrypoint the external origin actually
            targets. Pinning ``web`` (or both entrypoints independently)
            is a future extension.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = "LoadBalancer"
    annotations: dict[str, str] | None = None
    load_balancer_ip: str | None = None
    external_traffic_policy: str | None = None
    ip_families: list[Literal["IPv4", "IPv6"]] | None = None
    ip_family_policy: (
        Literal["SingleStack", "PreferDualStack", "RequireDualStack"] | None
    ) = None
    node_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("ip_families", mode="after")
    @classmethod
    def _validate_ip_families(
        cls, v: list[Literal["IPv4", "IPv6"]] | None
    ) -> list[Literal["IPv4", "IPv6"]] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "ip_families must not be empty when set; "
                "remove the field to use the cluster default."
            )
        if len(set(v)) != len(v):
            raise ValueError(f"ip_families must not contain duplicates; got {v!r}.")
        return v

    @model_validator(mode="after")
    def _validate_node_port_requires_nodeport_type(self) -> "IngressServiceConfig":
        if self.node_port is not None and self.type != "NodePort":
            raise ValueError(
                f"node_port is only valid when type == 'NodePort'; "
                f"got type={self.type!r} with node_port={self.node_port}."
            )
        return self


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
    service: IngressServiceConfig = IngressServiceConfig()


class StandardStorage(BaseModel):
    """Standard storage configuration.

    Holds the configuration for the standard storage class in the kubernetes cluster.

    Attributes:
        storage_class (str): The storage class name.
    """

    model_config = ConfigDict(extra="forbid")

    storage_class: str


class FastStorage(BaseModel):
    """Fast storage configuration.

    Holds the configuration for the fast (typically NVMe / local SSD)
    storage class in the kubernetes cluster.

    Attributes:
        storage_class (str): The storage class name.
    """

    model_config = ConfigDict(extra="forbid")

    storage_class: str


_K8S_QUANTITY_RE = re.compile(
    r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)"
    r"(?:[eE][+-]?[0-9]+|[numkKMGTPE]|[KMGTPE]i)?$"
)

_DNS_1123_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-.]*[a-z0-9])?$")

_EXTENDED_RESOURCE_KEY_RE = re.compile(
    r"^"
    r"(?:[a-z0-9]([-a-z0-9]*[a-z0-9])?"
    r"(?:\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*/)?"
    r"[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?"
    r"$"
)


def _parse_k8s_quantity(value: str) -> str:
    """Validate that *value* is a parseable Kubernetes quantity string.

    Raises ``ValueError`` on empty string or an unrecognised suffix/format.
    Returns the input unchanged on success (we do not canonicalise here so
    round-tripping a config payload is lossless).
    """
    if not isinstance(value, str) or not value:
        raise ValueError("Kubernetes quantity must be a non-empty string.")
    if not _K8S_QUANTITY_RE.match(value):
        raise ValueError(
            f"Invalid Kubernetes quantity: {value!r}. "
            "Expected a number optionally followed by a unit suffix "
            "(e.g. '100m', '2', '256Mi', '2Gi', '1.5')."
        )
    return value


def _validate_extended_key(key: str) -> str:
    """Validate a Kubernetes extended-resource key (e.g. ``nvidia.com/gpu``)."""
    if not isinstance(key, str) or not key:
        raise ValueError("Extended resource key must be a non-empty string.")
    if any(ch.isspace() for ch in key):
        raise ValueError(f"Extended resource key {key!r} must not contain whitespace.")
    if not _EXTENDED_RESOURCE_KEY_RE.match(key):
        raise ValueError(
            f"Invalid extended resource key: {key!r}. "
            "Expected a Kubernetes resource name, optionally prefixed with a "
            "DNS-subdomain and '/' (e.g. 'nvidia.com/gpu', 'hugepages-2Mi')."
        )
    return key


class LabelSelectorRequirement(BaseModel):
    """Single ``matchExpressions`` entry on a Kubernetes label selector."""

    model_config = ConfigDict(extra="forbid")

    key: str
    operator: Literal["In", "NotIn", "Exists", "DoesNotExist"]
    values: list[str] | None = None


class LabelSelector(BaseModel):
    """Kubernetes-style label selector (``matchLabels`` and/or ``matchExpressions``)."""

    model_config = ConfigDict(extra="forbid")

    match_labels: dict[str, str] | None = None
    match_expressions: list[LabelSelectorRequirement] | None = None


class DeploymentReference(BaseModel):
    """Reference to another deployment in the same environment by platform identifier.

    At resolve time the reference is expanded into a label selector keyed on
    the platform-generated ``styrmin/deployment_id`` identity label and,
    when ``components`` is set, the ``styrmin/component`` label.
    """

    model_config = ConfigDict(extra="forbid")

    deployment_id: UUID | None = None
    deployment_name: str | None = None
    components: list[str] | None = None

    @model_validator(mode="after")
    def _require_one_identifier(self) -> "DeploymentReference":
        if (self.deployment_id is None) == (self.deployment_name is None):
            raise ValueError(
                "Exactly one of deployment_id or deployment_name must be set."
            )
        return self


class AffinityTerm(BaseModel):
    """Single affinity term.

    Carries either a ``label_selector`` (escape hatch) or a
    ``deployment_ref`` that the resolver expands into a ``label_selector``.
    For ``node_affinity``, ``topology_key`` is ignored and may be empty.
    """

    model_config = ConfigDict(extra="forbid")

    topology_key: str
    namespaces: list[str] | None = None
    namespace_selector: LabelSelector | None = None
    label_selector: LabelSelector | None = None
    deployment_ref: DeploymentReference | None = None
    match_label_keys: list[str] | None = None
    mismatch_label_keys: list[str] | None = None

    @model_validator(mode="after")
    def _require_one_selector(self) -> "AffinityTerm":
        if (self.label_selector is None) == (self.deployment_ref is None):
            raise ValueError(
                "Exactly one of label_selector or deployment_ref must be set."
            )
        return self


class WeightedAffinityTerm(BaseModel):
    """Weighted affinity term for a ``preferred`` rule (weight in 1..100)."""

    model_config = ConfigDict(extra="forbid")

    weight: int
    term: AffinityTerm

    @field_validator("weight")
    @classmethod
    def _weight_range(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("weight must be between 1 and 100.")
        return v


class AffinityBlock(BaseModel):
    """One affinity kind (pod / pod-anti / node) at one level.

    ``required`` and ``preferred`` accumulate across levels; ``replace: true``
    discards all shallower-level terms for the affected affinity kind.
    """

    model_config = ConfigDict(extra="forbid")

    required: list[AffinityTerm] = Field(default_factory=list)
    preferred: list[WeightedAffinityTerm] = Field(default_factory=list)
    replace: bool = False


class TopologySpreadConstraint(BaseModel):
    """One topology-spread constraint on the pod template."""

    model_config = ConfigDict(extra="forbid")

    max_skew: int
    topology_key: str
    when_unsatisfiable: Literal["DoNotSchedule", "ScheduleAnyway"]
    label_selector: LabelSelector | None = None
    min_domains: int | None = None
    node_affinity_policy: Literal["Honor", "Ignore"] | None = None
    node_taints_policy: Literal["Honor", "Ignore"] | None = None
    match_label_keys: list[str] | None = None


class ResourceSpec(BaseModel):
    """Pod-container ``resources.requests`` or ``resources.limits`` payload."""

    model_config = ConfigDict(extra="forbid")

    cpu: str | None = None
    memory: str | None = None
    ephemeral_storage: str | None = None
    extended: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_quantities(self) -> "ResourceSpec":
        for value in (self.cpu, self.memory, self.ephemeral_storage):
            if value is not None:
                _parse_k8s_quantity(value)
        for key, value in self.extended.items():
            _validate_extended_key(key)
            _parse_k8s_quantity(value)
        return self


class ResourceRequirements(BaseModel):
    """Container resource requirements (``requests`` and ``limits``)."""

    model_config = ConfigDict(extra="forbid")

    requests: ResourceSpec | None = None
    limits: ResourceSpec | None = None


class Toleration(BaseModel):
    """Single pod toleration entry."""

    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    operator: Literal["Exists", "Equal"] | None = None
    value: str | None = None
    effect: Literal["NoSchedule", "PreferNoSchedule", "NoExecute"] | None = None
    toleration_seconds: int | None = None


class PostRenderInjection(BaseModel):
    """Per-feature opt-out flags for the default post-renderer injection.

    Meaningful at deployment and component scopes only; environment-scope
    ``inject`` is accepted by the schema for symmetry but ignored at
    resolution time (the merge emits a warning log in that case — see
    :func:`styrmin_backend.context.resolvers._merge_inject_flags`). Each
    flag is three-valued: ``None`` inherits from the next shallower level;
    ``True`` opts the feature in; ``False`` opts it out. A ``None`` all
    the way up the chain resolves to ``True`` (the default behaviour).
    Component-level flags override deployment-level flags per field.
    """

    model_config = ConfigDict(extra="forbid")

    pod_affinity: bool | None = None
    node_affinity: bool | None = None
    topology_spread: bool | None = None
    resources: bool | None = None
    tolerations: bool | None = None
    runtime_class: bool | None = None


class SchedulingConfig(BaseModel):
    """Hierarchical pod scheduling & resource configuration section.

    Attached to every configuration level (environment, deployment, component).
    Absent fields inherit from the next shallower level per the platform's
    merge rules. See ``specs/001-pod-scheduling-config/data-model.md``.
    """

    model_config = ConfigDict(extra="forbid")

    pod_affinity: AffinityBlock | None = None
    pod_anti_affinity: AffinityBlock | None = None
    node_affinity: AffinityBlock | None = None
    topology_spread_constraints: list[TopologySpreadConstraint] | None = None
    resources: ResourceRequirements | None = None
    tolerations: list[Toleration] | None = None
    runtime_class: str | None = None
    inject: PostRenderInjection | None = None

    @field_validator("runtime_class")
    @classmethod
    def _validate_runtime_class(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v or not _DNS_1123_SUBDOMAIN_RE.match(v):
            raise ValueError(
                "runtime_class must be a non-empty DNS-1123 subdomain (e.g. 'kata')."
            )
        return v


class BaseConfigSection(BaseModel):
    """Base context section.

    Attributes:
        ingress_class (str): The ingress class name.
        db_size (str): The database size.
        backup_ttl (str | None): Retention applied to backups taken for this
            scope, as a strictly positive Go duration in ``h``/``m``/``s``
            units (e.g. ``"720h"``). Resolved deepest-wins across cluster,
            environment, and deployment scope at backup time; ``None`` means
            "no policy at this scope" and falls through to the next shallower
            one, ultimately the built-in
            :data:`~styrmin_backend.services.backup.ttl.DEFAULT_BACKUP_TTL`.
        fqdn_suffix (str): The fully qualified domain name suffix.
        external_url_scheme (str): Scheme used for user-facing service URLs
            ("http" or "https"). Defaults to "https" when not set.
        external_url_port (int): Port to include in user-facing service URLs.
            Omitted from rendered URLs when it matches the scheme default
            (80 for http, 443 for https). Used for local demos that expose
            the cluster on a non-default port (e.g. via `kubectl port-forward`).
        external_dns_endpoints_type (Literal["NodeExternalIP", "ClusterIP"] | None):
            Optional override of the external-dns endpoints-type. Set to
            "NodeExternalIP" on IPv6 / dual-stack clusters where external-dns
            must publish AAAA records that resolve to the node's external IP
            rather than the Service ClusterIP.
        scheduling (SchedulingConfig): Optional hierarchical pod scheduling
            and resource configuration. Absent fields inherit from shallower
            levels during resolution.
    """

    model_config = ConfigDict(extra="forbid")

    ingress_class: str | None = None
    db_size: str | None = None
    backup_ttl: str | None = None
    fqdn_suffix: str | None = None
    external_url_scheme: Literal["http", "https"] | None = None
    external_url_port: int | None = Field(default=None, ge=1, le=65535)
    external_dns_endpoints_type: Literal["NodeExternalIP", "ClusterIP"] | None = Field(
        default=None,
        description=(
            "Optional value emitted as the "
            "external-dns.alpha.kubernetes.io/endpoints-type annotation on "
            "the application Ingress. Set to 'NodeExternalIP' on IPv6 / "
            "dual-stack clusters where external-dns must publish AAAA "
            "records that resolve to the node's external IP rather than "
            "the Service ClusterIP. Leave unset to omit the annotation "
            "entirely (external-dns falls back to its default behaviour)."
        ),
    )
    scheduling: SchedulingConfig | None = None

    @field_validator("backup_ttl")
    @classmethod
    def _validate_backup_ttl(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Imported lazily, mirroring ``_validate_env_vars`` below: the rule
        # lives with the resolver in ``services.backup.ttl`` (single home for
        # the retention contract) and the config models stay free of
        # module-load-time dependencies on the services layer.
        from styrmin_backend.services.backup.ttl import validate_backup_ttl

        return validate_backup_ttl(v)


CLUSTER_SCHEDULING_REJECTED = (
    "a cluster does not take this setting, because no pod gets it from the "
    "cluster; set it on the environment or the deployment"
)


class ClusterConfig(BaseConfigSection):
    """The Cluster context.

    Attributes:
        runtime_class (str | None): The runtime class.
        dedicated_ingress (DedicatedIngressConfig | None): The dedicated ingress controller config.
            ``None`` turns the controller off; any object, including ``{}``,
            turns it on with the default values.
        standard_storage (StandardStorage | None): The standard storage.
        fast_storage (FastStorage | None): The fast storage.

    ``scheduling`` is refused whatever its value, ``null`` included: no pod
    gets a cluster's scheduling value (ADR-033, #482).
    """

    model_config = ConfigDict(extra="forbid")

    runtime_class: str | None = None
    dedicated_ingress: DedicatedIngressConfig | None = None
    standard_storage: StandardStorage | None = None
    fast_storage: FastStorage | None = None

    @field_validator("scheduling")
    @classmethod
    def _reject_cluster_scheduling(
        cls, v: SchedulingConfig | None
    ) -> SchedulingConfig | None:
        # Runs only when the key is sent. DeploymentConfig inherits this class and takes scheduling.
        if cls is ClusterConfig:
            raise ValueError(CLUSTER_SCHEDULING_REJECTED)
        return v


class EnvironmentConfig(BaseConfigSection):
    """Environment context.

    Holds the environment context information.

    Attributes:
        ip_whitelist (list[str] | None): The IP whitelist.
        dedicated_ingress (DedicatedIngressConfig | None): The dedicated ingress controller config.
            ``None`` turns the controller off; any object, including ``{}``,
            turns it on with the default values.
        env_vars (dict[str, str] | None): Free-form environment variables to
            inject into every component's containers (008-deployment-env-vars,
            FR-001/FR-006..FR-008). Per-key validated through
            :func:`styrmin_backend.services.env_vars.validator.validate_env_vars_dict`.
    """

    model_config = ConfigDict(extra="forbid")

    ip_whitelist: list[str] | None = None
    dedicated_ingress: DedicatedIngressConfig | None = None
    env_vars: dict[str, str] | None = None

    @field_validator("env_vars")
    @classmethod
    def _validate_env_vars(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        # Imported lazily to avoid a circular import at module load time
        # (the validator module depends on services.exceptions, which itself
        # imports nothing from context.models).
        from styrmin_backend.services.env_vars.validator import (
            validate_env_vars_dict,
        )

        return validate_env_vars_dict("environment", v)


# Kubernetes ``spec.replicas`` is an ``int32``.
MAX_REPLICA_COUNT = 2_147_483_647


def _check_replica_count(value: Any, component_name: str | None) -> Any:
    """Return ``value`` when it is ``None`` or an ``int`` from 1 to ``MAX_REPLICA_COUNT``."""
    if value is None or (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= MAX_REPLICA_COUNT
    ):
        return value
    from styrmin_backend.services.replicas.exceptions import InvalidReplicaCountError

    raise InvalidReplicaCountError(
        component_name=component_name, requested_replicas=value
    )


class ComponentConfigBlock(BaseModel):
    """Per-component override block carried under ``DeploymentConfig.components``.

    Carries the per-component free-form ``env_vars`` dict (008-deployment-env-vars,
    FR-001 component scope, FR-002 deepest-wins precedence), the
    component-scope container ``command``/``args`` overrides
    (014-component-container-overrides), the component container's
    ``image`` override (018-component-image-overrides), and the component's
    ``replicas`` override (023-per-component-replicas). Future iterations may
    add per-component ``scheduling`` or ``inject`` overrides under the same
    block.

    The ``env_vars`` dict is validated against the same caps as the
    deployment-scope dict via :func:`validate_env_vars_dict` with
    ``scope="component"``. ``command`` and ``args`` are two independent,
    optional, nullable slots — ``None`` means "unset" (the chart's value
    applies); each is validated through
    :func:`validate_container_override` (non-empty list-of-string, empty-string
    elements accepted, ``[]`` rejected). ``image`` is one full image reference,
    optionally containing ``{{ app.version }}``; ``None`` means "chart image".
    It is validated through :func:`validate_stored_reference`, which
    substitutes a placeholder version because the real one is unknown here.

    These four reach the pod only through post-render patches to the component
    container, and only when the driver declares one (ADR-057, ADR-058, ADR-069).

    ``replicas`` is an integer from 1 to ``MAX_REPLICA_COUNT``; ``None`` means
    "no override" (the driver default or the chart's count applies). A ``bool``,
    a non-integer or a value out of range raises ``InvalidReplicaCountError``
    before type conversion. It is patched onto the workload, not the component
    container, so it needs no component container.
    """

    model_config = ConfigDict(extra="forbid")

    env_vars: dict[str, str] | None = None
    command: list[str] | None = None
    args: list[str] | None = None
    image: str | None = None
    replicas: int | None = None

    @field_validator("env_vars")
    @classmethod
    def _validate_component_env_vars(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        if v is None:
            return v
        from styrmin_backend.services.env_vars.validator import (
            validate_env_vars_dict,
        )

        return validate_env_vars_dict("component", v)

    # ``mode="before"`` so the validator sees the raw, un-coerced value: a
    # non-list or non-string element raises the typed
    # ``InvalidContainerCommandError`` / ``InvalidContainerArgsError`` directly
    # (a ``ServiceError``, which Pydantic v2 propagates un-wrapped) instead of
    # Pydantic's ``list[str]`` coercion failing first into a generic
    # ``ValidationError``. This keeps the typed ``extensions.code`` intact on
    # every path that builds the model — including read/CRD-sourced resolution
    # that bypasses the mutation-boundary pre-validator (symmetry with the
    # write path).
    @field_validator("command", mode="before")
    @classmethod
    def _validate_command(cls, v: Any) -> Any:
        from styrmin_backend.services.container_overrides.validator import (
            validate_container_override,
        )

        return validate_container_override("command", v)

    @field_validator("args", mode="before")
    @classmethod
    def _validate_args(cls, v: Any) -> Any:
        from styrmin_backend.services.container_overrides.validator import (
            validate_container_override,
        )

        return validate_container_override("args", v)

    # ``mode="before"`` for the same reason as ``command``/``args``: a non-string raises the
    # typed ``InvalidImageReferenceError`` instead of a generic ``ValidationError``.
    @field_validator("image", mode="before")
    @classmethod
    def _validate_image(cls, v: Any) -> Any:
        from styrmin_backend.services.image_overrides.reference import (
            validate_stored_reference,
        )

        return validate_stored_reference(v)

    # ``mode="before"`` so ``True``, ``"2"`` and ``2.0`` raise the typed error, not a coerced int.
    # The component name comes from the validation context or ``DeploymentConfig.components``.
    @field_validator("replicas", mode="before")
    @classmethod
    def _validate_replicas(cls, v: Any, info: ValidationInfo) -> Any:
        context = info.context if isinstance(info.context, dict) else {}
        return _check_replica_count(v, context.get("component_name"))

    @model_serializer(mode="wrap")
    def _omit_unset_replicas(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        # A release before 023 rejects the key (``extra="forbid"``) in a deployment context.
        data = handler(self)
        if data.get("replicas", 0) is None:
            del data["replicas"]
        return data


_FQDN_SUFFIX_MAX_LENGTH = 253
_FQDN_SUFFIX_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def validate_service_fqdn_suffix(value: str) -> str:
    """Validate the FQDN suffix of a service ingress override.

    The suffix must be a DNS name: dot-separated labels of lowercase letters, digits and
    hyphens (a label starts and ends with a letter or a digit and has at most 63
    characters), at most 253 characters in total, with no leading, trailing or doubled dot.
    The cluster, environment and deployment ``fqdn_suffix`` have no such check; the
    override is the one input that does (specs/033-service-ingress-override/data-model.md).
    """
    if not value:
        raise ValueError("fqdn_suffix must not be empty; remove the field to clear it.")
    if len(value) > _FQDN_SUFFIX_MAX_LENGTH:
        raise ValueError(
            f"fqdn_suffix {value!r} is longer than {_FQDN_SUFFIX_MAX_LENGTH} characters."
        )
    for label in value.split("."):
        if not _FQDN_SUFFIX_LABEL_RE.match(label):
            raise ValueError(
                f"fqdn_suffix {value!r} is not a DNS name: each dot-separated label must "
                "have 1 to 63 lowercase letters, digits or hyphens, and start and end "
                "with a letter or a digit."
            )
    return value


class ServiceConfigBlock(BaseModel):
    """Ingress override of one service of a deployment (#598).

    Stored in ``DeploymentConfig.services`` under the driver service name. A field left as
    ``None`` means: use the resolved cluster, environment or deployment value. A block with
    both fields ``None`` is not stored.

    Attributes:
        ingress_class (str | None): Ingress class of this service. A non-empty string.
        fqdn_suffix (str | None): FQDN suffix of this service, used in its readable host.
    """

    model_config = ConfigDict(extra="forbid")

    ingress_class: str | None = Field(default=None, min_length=1)
    fqdn_suffix: str | None = None

    @field_validator("fqdn_suffix")
    @classmethod
    def _validate_fqdn_suffix(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_service_fqdn_suffix(v)

    @property
    def is_empty(self) -> bool:
        return self.ingress_class is None and self.fqdn_suffix is None


class DeploymentConfig(ClusterConfig, EnvironmentConfig):
    """Deployment context.

    Holds the deployment context information. This section is used to generate the resolved context
    and is not included directly in the global context.

    Attributes:
        ip_whitelist (list[str] | None): The IP whitelist.
        env_vars (dict[str, str] | None): Deployment-scope free-form env vars
            (008-deployment-env-vars). Overrides matching keys from the
            environment scope per FR-002 deepest-wins precedence.
        components (dict[str, ComponentConfigBlock] | None): Per-component
            override blocks keyed by component name (US3). Each block carries
            the component-scope ``env_vars`` dict, the component-scope
            container ``command``/``args`` overrides
            (014-component-container-overrides), the component
            container's ``image`` override (018-component-image-overrides),
            and the ``replicas`` override (023-per-component-replicas).
            Component names that do not match a driver-declared component are
            rejected at the service boundary with
            ``UnknownComponentEnvVarError`` (env-var block),
            ``UnknownComponentContainerOverrideError`` (command/args block,
            FR-004), ``UnknownComponentImageOverrideError`` (image), or
            ``UnknownComponentReplicaOverrideError`` (an added or changed
            ``replicas``; an unchanged stored one is kept).
        services (dict[str, ServiceConfigBlock] | None): Per-service ingress
            override blocks keyed by driver service name (#598). A block with
            both fields ``None`` is dropped, and ``services`` is ``None`` when
            no block is left. The key is omitted from a dump when ``None``, so
            the stored config of a deployment without an override is unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    components: dict[str, ComponentConfigBlock] | None = None
    services: dict[str, ServiceConfigBlock] | None = None

    @field_validator("services", mode="after")
    @classmethod
    def _drop_empty_service_blocks(
        cls, v: dict[str, ServiceConfigBlock] | None
    ) -> dict[str, ServiceConfigBlock] | None:
        if v is None:
            return v
        kept = {name: block for name, block in v.items() if not block.is_empty}
        return kept or None

    @model_serializer(mode="wrap")
    def _omit_unset_services(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        # A release before this key rejects it (``extra="forbid"``), and the no-op check of a
        # deployment update must not see a difference for a deployment without an override.
        data = handler(self)
        if data.get("services", 0) is None:
            del data["services"]
        return data

    @field_validator("components", mode="before")
    @classmethod
    def _validate_component_replicas(cls, v: Any) -> Any:
        # Runs before each block is built so the error names the component (the dict key).
        if isinstance(v, dict):
            for name, block in v.items():
                if isinstance(block, dict):
                    _check_replica_count(block.get("replicas"), name)
        return v

    @field_validator("env_vars")
    @classmethod
    def _validate_deployment_env_vars(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        if v is None:
            return v
        from styrmin_backend.services.env_vars.validator import (
            validate_env_vars_dict,
        )

        return validate_env_vars_dict("deployment", v)


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
