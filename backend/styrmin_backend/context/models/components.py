from typing import Any, ItemsView, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from .config import SchedulingConfig


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


class ArbitrarySectionModel(BaseModel):
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
    lists (or ``None`` = unset → chart default). ``is_orphaned`` is set when
    the targeted component is no longer declared by the deployment's current
    driver (FR-005); orphaned blocks are surfaced on read but skipped by the
    renderer so no value reaches a container.
    """

    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None
    args: list[str] | None = None
    is_orphaned: bool = False

    @model_validator(mode="after")
    def _reject_empty_lists(self) -> "ResolvedComponentContainerOverride":
        """Reject the empty-list state so it can never reach the renderer.

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
