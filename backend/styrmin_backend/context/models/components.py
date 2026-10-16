from collections.abc import Callable, Mapping
from typing import Any, ItemsView, Literal, Self

from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    RootModel,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    ValidationError,
    ValidationInfo,
    model_serializer,
    model_validator,
)

from .config import MAX_REPLICA_COUNT, SchedulingConfig


class LabelIdentifier(RootModel):
    root: dict[str, str]

    def __getitem__(self, item: str) -> str:
        """Get an item from the components context.

        Args:
            item (str): The item key.

        Returns:
            str: The item value.
        """
        return self.root[item]

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def items(self) -> ItemsView[str, str]:
        return self.root.items()

    def label_selectable(self) -> str:
        key = next(iter(self.root.keys()))
        value = next(iter(self.root.values()))
        return f"{key}={value}"


class Identifier(BaseModel):
    label: LabelIdentifier


class ReplicaDeclaration(BaseModel):
    """The ``replicas`` and ``singleton`` keys of a driver component declaration (023).

    Shared by the driver-load model and the context model, so both type the keys the same way.
    Each key is left out of a dump at its default, so a declaration that uses neither key dumps
    as it did before the keys were typed.
    """

    replicas: StrictInt | None = Field(default=None, ge=1, le=MAX_REPLICA_COUNT)
    singleton: StrictBool = False

    @model_validator(mode="after")
    def _singleton_runs_one_replica(self) -> Self:
        if self.singleton and self.replicas is not None and self.replicas > 1:
            raise ValueError(
                f"a singleton component runs exactly 1 replica; `singleton: true` "
                f"cannot be combined with `replicas: {self.replicas}`"
            )
        return self

    @model_serializer(mode="wrap")
    def _omit_replica_defaults(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        data = handler(self)
        if data.get("replicas", 0) is None:
            del data["replicas"]
        if data.get("singleton") is False:
            del data["singleton"]
        return data


# ``singleton`` first: when both keys conflict, the count is dropped and the component runs 1 pod.
_REPLICA_KEYS = ("singleton", "replicas")


def driver_version_label(driver_version_id: Any) -> str:
    """Name a driver version in log messages."""
    return f"driver version {driver_version_id}"


def split_replica_keys(
    declaration: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split the replica keys of a stored declaration into the valid ones and the invalid ones."""
    kept: dict[str, Any] = {}
    for key in _REPLICA_KEYS:
        if key not in declaration:
            continue
        candidate: dict[str, Any] = {**kept, key: declaration[key]}
        try:
            ReplicaDeclaration.model_validate(candidate)
        except ValidationError:
            continue
        kept = candidate
    dropped: dict[str, Any] = {
        k: declaration[k] for k in _REPLICA_KEYS if k in declaration and k not in kept
    }
    return kept, dropped


def _warn_dropped_replica_keys(
    dropped: Mapping[str, Any], *, component: str, driver_version: str | None
) -> None:
    keys = ", ".join(f"{key}={value!r}" for key, value in dropped.items())
    logger.warning(
        "Ignoring the invalid keys {} of component {}{}",
        keys,
        component,
        f" in {driver_version}" if driver_version else "",
    )


def parse_stored_replica_declaration(
    declaration: Mapping[str, Any], *, component: str, driver_version: str | None = None
) -> ReplicaDeclaration:
    """Parse the replica keys of a stored component declaration; an invalid key reads as unset."""
    kept, dropped = split_replica_keys(declaration)
    if dropped:
        _warn_dropped_replica_keys(
            dropped, component=component, driver_version=driver_version
        )
    return ReplicaDeclaration.model_validate(kept)


def validate_ignoring_invalid_replica_keys[T](
    validate: Callable[[dict[str, Any]], T],
    declaration: Mapping[str, Any],
    *,
    component: str,
    driver_version: str | None = None,
) -> T:
    """Run ``validate`` on a stored component declaration, ignoring invalid replica keys (023).

    A driver version loaded before 023 may hold ``replicas`` or ``singleton`` values that the
    typed keys reject. When dropping the invalid keys makes ``validate`` pass, they are dropped
    with a warning; any other error is raised unchanged. The driver load path does not call this.
    """
    try:
        return validate(dict(declaration))
    except ValidationError as err:
        _, dropped = split_replica_keys(declaration)
        if not dropped:
            raise
        try:
            result = validate(
                {k: v for k, v in declaration.items() if k not in dropped}
            )
        except ValidationError:
            raise err from None
    _warn_dropped_replica_keys(
        dropped, component=component, driver_version=driver_version
    )
    return result


class ArbitrarySectionModel(ReplicaDeclaration):
    model_config = ConfigDict(extra="allow")

    identifier: Identifier
    # Validated at driver load; ``None`` on contexts stored before the field.
    container: str | None = None

    def __getitem__(self, item: Any) -> Any:
        assert self.__pydantic_extra__ is not None
        return self.__pydantic_extra__[item]


ProvenanceLevel = Literal["environment", "deployment", "component"]


class ResolvedComponentScheduling(BaseModel):
    """Per-component effective scheduling configuration plus provenance.

    ``config`` is the fully merged :class:`SchedulingConfig` for one component
    (env → deployment → component layers combined). ``provenance`` maps each
    effective field (dotted path, e.g. ``"resources.requests.cpu"``) to the
    level that contributed its final value.
    """

    model_config = ConfigDict(extra="forbid")

    config: SchedulingConfig
    provenance: dict[str, ProvenanceLevel] = Field(default_factory=dict)


class ResolvedComponentEnvVars(BaseModel):
    """Per-component effective env vars plus provenance.

    Mirrors :class:`ResolvedComponentScheduling`: ``config`` is the fully
    merged ``dict[str, str]`` for one component (env → deployment → component
    layers combined, per-key deepest-wins per data-model.md §2.2);
    ``provenance`` maps each effective env var name to the level that
    contributed its final value. ``is_orphaned`` is set when the targeted
    component is no longer declared by the deployment's current driver
    (FR-029..FR-033). Orphaned blocks are kept in the resolved context so
    the GraphQL surface can expose them, but the patch builder skips them.
    """

    model_config = ConfigDict(extra="forbid")

    config: dict[str, str]
    provenance: dict[str, ProvenanceLevel] = Field(default_factory=dict)
    is_orphaned: bool = False


class ResolvedComponentContainerOverride(BaseModel):
    """Per-component effective container ``command``/``args`` override.

    Unlike :class:`ResolvedComponentEnvVars` there is **no provenance field**:
    container overrides are component-scope-only (no environment/deployment
    layering — research.md D2), so each slot has exactly one possible source
    and provenance is meaningless. ``command`` / ``args`` are the resolved
    lists, or ``None`` when unset so the chart's value applies. The patch
    builder writes set lists into the component container's merge patch
    (ADR-069). ``is_orphaned`` is set when the targeted component is no longer
    declared by the deployment's current driver (FR-005); orphaned blocks are
    surfaced on read but never patched.
    """

    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None
    args: list[str] | None = None
    is_orphaned: bool = False

    @model_validator(mode="after")
    def _reject_empty_lists(self) -> "ResolvedComponentContainerOverride":
        """Reject the empty-list state so it can never reach the merge patch.

        ``[]`` is an invalid value upstream (the write boundary and
        ``validate_container_override`` reject it; "clear" is ``None``/omit,
        not ``[]`` — FR-007). Enforcing the same invariant here makes "no
        empty list" local to this type instead of relying on every caller, so
        the resolver's ``not block.command`` and the context populator's
        ``command is None`` emptiness checks are provably equivalent, and a
        future direct-construction caller cannot smuggle an ``[]`` past them.
        """
        for slot in ("command", "args"):
            if getattr(self, slot) == []:
                raise ValueError(
                    f"{slot} must be a non-empty list or None, never [] "
                    "(clear is None/omit, not [])"
                )
        return self


class ResolvedComponentImageOverride(BaseModel):
    """Per-component image override for the component container (018).

    Component-scope only, like :class:`ResolvedComponentContainerOverride`, so there is no
    provenance. ``reference`` is the stored string with ``{{ app.version }}`` NOT substituted;
    the patch builder substitutes ``context.app.version`` at render time. ``is_orphaned`` is set
    when the driver no longer declares the component; orphans surface on read only.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str
    is_orphaned: bool = False


class ComponentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: ArbitrarySectionModel
    name: str
    enabled: bool
    scheduling: ResolvedComponentScheduling | None = None
    env_vars: ResolvedComponentEnvVars | None = None
    container_override: ResolvedComponentContainerOverride | None = None
    image_override: ResolvedComponentImageOverride | None = None
    # ``DeploymentConfig.components[<name>].replicas``; declared components only (023).
    replica_override: StrictInt | None = Field(default=None, ge=1, le=MAX_REPLICA_COUNT)

    @model_validator(mode="wrap")
    @classmethod
    def _ignore_invalid_stored_replica_keys(
        cls, data: Any, handler: ModelWrapValidatorHandler[Self], info: ValidationInfo
    ) -> Self:
        # Pass ``context={"driver_version": ...}`` to name the driver version in the warning.
        if not isinstance(data, dict) or not isinstance(data.get("config"), Mapping):
            return handler(data)
        return validate_ignoring_invalid_replica_keys(
            lambda config: handler({**data, "config": config}),
            data["config"],
            component=str(data.get("name")),
            driver_version=(info.context or {}).get("driver_version"),
        )

    @model_serializer(mode="wrap")
    def _omit_unset_replica_override(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        # An agent or server of the release before 023 rejects the key (``extra="forbid"``).
        data = handler(self)
        if data.get("replica_override", 0) is None:
            del data["replica_override"]
        return data


class ComponentsContext(RootModel):
    root: dict[str, ComponentContext]

    def __getitem__(self, item: str) -> ComponentContext:
        """Get an item from the components context.

        Args:
            item (str): The item key.

        Returns:
            ComponentContext: The item value.
        """
        return self.root[item]

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def items(self) -> ItemsView[str, ComponentContext]:
        return self.root.items()
