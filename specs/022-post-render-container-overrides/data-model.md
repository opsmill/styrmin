# Data Model: Container `command` and `args` Overrides Applied by Post-Render

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No new entity. Names follow [`CONTEXT.md`](../../CONTEXT.md).

## Container override (stored, unchanged)

Stored in `Deployment.config` JSON as `components[<name>].command` and `components[<name>].args` (`ComponentConfigBlock` in [`context/models/config.py`](../../backend/styrmin_backend/context/models/config.py)).

| Field | Type | Rule |
|-------|------|------|
| `command` | `list[str] \| None` | `None` or omitted means "not set". A set value is a non-empty list of strings, at most 1024 elements and 256 KiB. `[]` is rejected (`INVALID_CONTAINER_COMMAND`). Unchanged |
| `args` | `list[str] \| None` | Same rules (`INVALID_CONTAINER_ARGS`). Unchanged |

No storage change and no data migration for deployments. A value stored before this change keeps its meaning.

## Resolved container override (rendering context, unchanged)

`ResolvedComponentContainerOverride` on `ComponentContext.container_override` ([`context/models/components.py`](../../backend/styrmin_backend/context/models/components.py)): `command`, `args`, `is_orphaned`. It stays in the rendering context as read-only data, as `env_vars` did after ADR-057. Only the template filters that read it are retired.

## Applicable overrides (new value object, not persisted)

`ApplicableOverrides` in [`services/component_container/overrides.py`](../../backend/styrmin_backend/services/component_container/overrides.py) (research D-002).

| Field | Type | Source |
|-------|------|--------|
| `env` | `dict[str, str]` | `component.env_vars.config` when it applies, else `{}` |
| `image` | `str \| None` | `image_override.reference` with `{{ app.version }}` substituted and validated, when it applies |
| `command` | `list[str] \| None` | `container_override.command` when it applies |
| `args` | `list[str] \| None` | `container_override.args` when it applies |
| `is_empty` (property) | `bool` | true when all four are empty or `None` |

Rule (`override_applies(container, is_orphaned)`): an override applies when the component declares a component container (`config.container` is not `None`) and the override is not orphaned.

## Container merge patch (changed post-render patch, not persisted)

`ContainerMergePatch` (renamed from `ContainerEnvPatch`) in [`blocks/patches.py`](../../backend/styrmin_backend/agent/service/kubernetes/resources/blocks/patches.py).

| Field | Type | Rendering |
|-------|------|-----------|
| `container` | `str` | always written as the container `name` (merge key) |
| `env` | `dict[str, str]` | written as `env` entries with `valueFrom: null` when not empty (unchanged) |
| `command` | `list[str] \| None` | written as `command` when not `None` (new) |
| `args` | `list[str] \| None` | written as `args` when not `None` (new) |
| `kind` | `str` | `Deployment` or `StatefulSet` |

Order inside `spec.postRenderers` is unchanged: every other patch, then per kind the merge patch, then the guard `ComponentContainerPatch` (ADR-057 §3, ADR-058).

## Application driver version (changed)

`ApplicationDriverVersion` in [`db/models.py`](../../backend/styrmin_backend/db/models.py):

| Change | Detail |
|--------|--------|
| Removed column | `container_overrides` (`JSON`, nullable), added by revision `a8b9c0d1e2f3` |
| Migration | new revision, `down_revision = "9548830f81cd"`. Upgrade: `op.drop_column("applicationdriverversion", "container_overrides")`. Downgrade: `op.add_column` with `sa.JSON()`, nullable, no data |

Driver specification file (`Specification` model): the `container_overrides` key is removed. `extra="forbid"` rejects it as an unknown key.

## Read surface (GraphQL)

`ComponentContainerOverrides` gains `isApplicable: Boolean!` = `override_applies(container of the component in the deployment's pinned driver version, isOrphaned)`. See [contracts/graphql.md](contracts/graphql.md).

## State of a stored override

```text
stored value ──► component orphaned?            ── yes ──► isOrphaned=true,  isApplicable=false, not applied
             └─► component container declared?  ── no  ──► isOrphaned=false, isApplicable=false, not applied
                                                 └─ yes ──► isApplicable=true, merge patch + guard built
cleared value ──► no field in the merge patch (no patches at all when nothing else applies)
```

Writes: an added or changed value on a component without a component container is rejected (`COMPONENT_CONTAINER_NOT_DECLARED`, `override: "command"` or `"args"`). A removal or the same value sent again is accepted.
