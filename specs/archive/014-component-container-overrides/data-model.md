# Phase 1 Data Model: Component-Scope `command` / `args` Overrides

All persisted state rides existing JSON columns (ADR-029). The only DB-level addition is one informational column on `ApplicationDriverVersion` (mirrors `env_vars`). Field names use `snake_case` in Python/storage and `camelCase` on the GraphQL wire.

---

## 1. Component override slot — `ComponentConfigBlock` (extended)

**File**: `backend/styrmin_backend/context/models/config.py` (existing class, +2 fields)

```python
class ComponentConfigBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env_vars: dict[str, str] | None = None          # existing
    command: list[str] | None = None                # NEW — container entrypoint override
    args: list[str] | None = None                   # NEW — container args override

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v): ...   # -> validate_container_override("command", v)

    @field_validator("args")
    @classmethod
    def _validate_args(cls, v): ...      # -> validate_container_override("args", v)
```

| Field | Type | Optional | Nullable | Meaning |
|-------|------|----------|----------|---------|
| `command` | `list[str]` | yes | yes (`None` = unset → chart default) | Container entrypoint override, verbatim |
| `args` | `list[str]` | yes | yes (`None` = unset → chart default) | Container args override, verbatim |

**Storage**: under `Deployment.config["components"][<name>]`. No migration; absent keys deserialize to `None`.

**Independence (FR-001, FR-007 / US2, US3)**: `command` and `args` are two independent slots — setting/clearing one never affects the other.

**Validation rules** (enforced by `validate_container_override`, see §6 — applied both as a pre-Pydantic dict check at the mutation boundary *and* as the field validators above):

- Each list element MUST be a `str` → else `INVALID_CONTAINER_COMMAND` / `INVALID_CONTAINER_ARGS` (FR-006, US4 Sc.3).
- Empty-string elements (`""`) ARE accepted (FR-006, US4 Sc.4).
- A present list MUST be non-empty; `[]` is rejected with the per-field typed error (FR-006, US4 Sc.2).
- "Clear" is `None` / field omission — NOT `[]` (FR-007).
- A present list is bounded by a per-list element-count cap (1024) and serialised UTF-8 byte cap (256 KiB) → else `CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED`. Mirrors the env-vars caps; there is no separate post-merge cap because container overrides do not layer/merge (the input list IS the resolved value).
- Values are passed through verbatim; no templating/expansion (FR-014).

**`DeploymentConfig.components`** is unchanged in shape: `dict[str, ComponentConfigBlock] | None`. A block targeting a component the pinned driver does not declare is rejected on write (§5) and surfaced as orphaned on read (§4).

---

## 2. Resolved component override — `ResolvedComponentContainerOverride` (new)

**File**: `backend/styrmin_backend/context/models/components.py` (new model; attach to `ComponentContext`)

```python
class ResolvedComponentContainerOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None
    args: list[str] | None = None
    is_orphaned: bool = False


class ComponentContext(BaseModel):
    ...
    env_vars: ResolvedComponentEnvVars | None = None              # existing
    container_override: ResolvedComponentContainerOverride | None = None   # NEW
```

| Field | Type | Meaning |
|-------|------|---------|
| `command` | `list[str] \| None` | The resolved entrypoint for this component, or `None` (unset → chart default). **No layering** — equals the component block's value (D2). |
| `args` | `list[str] \| None` | The resolved args for this component, or `None`. |
| `is_orphaned` | `bool` | `True` when the component is no longer declared by the deployment's current driver version. Surfaced on read; **skipped by the renderer** — no value reaches a container (FR-005). |

**Note — no provenance field.** Unlike `ResolvedComponentEnvVars` (which carries `provenance` because it merges three scopes), container overrides are component-scope-only, so there is exactly one possible source and provenance is meaningless (D2).

---

## 3. Driver doc-only declaration — `DriverContainerOverrideDoc` (new)

**File**: `backend/styrmin_backend/services/driver/models/resources/container_overrides.py` (mirrors `env_vars.py`)

```python
class DriverContainerOverrideDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str                       # MUST reference a declared component (cross-validated at load)
    description: str = ""
    container: str | None = None         # informational: which rendered container the override targets
    command: bool = False                # advertises command overridability
    args: bool = False                   # advertises args overridability
```

- Parsed from an optional `spec` block in `driver.styrmin.yml` (alongside the existing `env_vars` doc block).
- **Doc-only / informational** (FR-010): the platform does NOT require a declared component to actually consume the override (US6 Sc.3 silent no-op). Cross-field validation at driver load time asserts each `component` references a declared component (mirrors `validate_driver_env_var_docs`); duplicate-name uniqueness mirrors `validate_env_var_doc_names_unique`.
- Materialised onto `ApplicationDriverVersion.container_overrides` (see §3a) and exposed via GraphQL (FR-011).

### 3a. `ApplicationDriverVersion.container_overrides` (new JSON column)

**File**: `backend/styrmin_backend/db/models.py`

```python
class ApplicationDriverVersion(StyrminModel, table=True):
    ...
    env_vars: list | None = Field(default=None, sa_column=Column(JSON))            # existing
    container_overrides: list | None = Field(default=None, sa_column=Column(JSON)) # NEW (doc-only decls)
```

Each entry shape matches `DriverContainerOverrideDoc`. `None`/empty when the driver omits the block. Created by `metadata.create_all()` (no Alembic). Governance gate acknowledged in plan.md.

---

## 4. Resolution & orphan detection — `ContainerOverridesResolver` (new)

**File**: `backend/styrmin_backend/services/container_overrides/resolver.py` (mirrors `services/env_vars/resolver.py` orphan branch; **no merge**)

```python
@dataclass(frozen=True)
class ResolvedContainerOverrideEntry:
    component_name: str
    resolved: ResolvedComponentContainerOverride


class ContainerOverridesResolver:
    @staticmethod
    def resolve_for_deployment(
        component_overrides: dict[str, ComponentConfigBlock | None] | None,
        driver_components: list[str] | None,
    ) -> list[ResolvedContainerOverrideEntry]:
        ...
```

Behaviour:

1. **Live entries** — for each name in `driver_components`, emit one entry with the component block's `command`/`args` (or `None`), `is_orphaned=False`. (Direct lookup; no env/dep layering — D2.)
2. **Orphan entries** (FR-005, US5) — for each stored block whose key is NOT in `driver_components` and that carries a non-empty `command` or `args`, emit one entry (sorted by name) with the stored values and `is_orphaned=True`. Blocks with neither field set are dropped (nothing to surface).
3. The renderer consumes **only** non-orphaned entries; orphan entries exist purely for the read surface.

**State transitions** (a single component override block over its lifetime):

```text
            set command/args (valid)            driver upgrade drops component
 (unset) ───────────────────────────► (active) ──────────────────────────────► (orphaned)
    ▲                                     │                                          │
    │     clear (null/omit) ◄─────────────┘                                          │
    └──────────────────── operator removes block via update-deployment ◄────────────┘
```

- **unset → active**: validated on write (§5/§6); triggers redeploy (FR-008); reaches the container next reconcile (US1/US2).
- **active → unset (clear)**: field set to `null`/omitted; chart default flows through next reconcile; absent from subsequent reads (FR-007 / US3).
- **active → orphaned**: driver upgrade renames/removes the component; block preserved, flagged orphaned, skipped by renderer; upgrade not blocked (FR-005/FR-015 / US5).
- **orphaned → removed**: operator removes the block via standard update-deployment; disappears from reads (US5 Sc.4).

---

## 5. Write-side validation targets (extended)

**File**: `backend/styrmin_backend/services/deployment.py`

Extend the existing pre-reconcile validation (runs before Pydantic so typed errors survive to GraphQL):

- A `components[<name>]` block carrying `command`/`args` whose `<name>` is NOT in the driver's declared set (`[cc.name for cc in (adv.component_configs or [])]`) → `UnknownComponentContainerOverrideError` with `component_name` + sorted `known_components` (FR-004, US4 Sc.1). Runs alongside (independent of) the existing `_validate_component_env_var_targets`.
- Each present `command`/`args` validated via `validate_container_override` (§6) → per-field typed error. No reconcile is planned on rejection (US4: zero containers restarted).

---

## 6. Validation helper — `validate_container_override` (new)

**File**: `backend/styrmin_backend/services/container_overrides/validator.py`

```python
def validate_container_override(field: Literal["command", "args"], value: list[str] | None) -> list[str] | None:
    if value is None:
        return None                                  # "unset" — allowed (clear/omit)
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise InvalidContainerCommandError(...) if field == "command" else InvalidContainerArgsError(...)
    if len(value) == 0:
        raise InvalidContainerCommandError(...) if field == "command" else InvalidContainerArgsError(...)
    return value                                     # empty-string elements OK; verbatim
```

| Input | Result |
|-------|--------|
| `None` | OK (unset / clear) |
| `["serve"]`, `["sh","-c",""]` | OK (empty-string element accepted) |
| `[]` | `INVALID_CONTAINER_{COMMAND,ARGS}` |
| `[123]`, `["ok", 5]` | `INVALID_CONTAINER_{COMMAND,ARGS}` (non-string element) |
| `>1024` elements, or `>256 KiB` serialised | `CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED` |

---

## 7. GraphQL surface (see `contracts/graphql-deltas.md`)

- **Input**: `ComponentConfigInput` gains `command: [String!]` and `args: [String!]` (nullable; full-replacement + null-clear per ADR-018).
- **Output**: new `ComponentContainerOverrides { component, command: [String!], args: [String!], isOrphaned }` + `Deployment.componentContainerOverrides: [ComponentContainerOverrides!]!` (non-null list, per the env-vars precedent).
- **Driver doc**: `ApplicationDriverVersion.containerOverrides: [DriverContainerOverrideDoc!]!`.

---

## Entity relationships

```text
ApplicationDriverVersion
  ├── component_configs: [ComponentConfig]   (declared components — source of truth for validation/orphan)
  └── container_overrides: [DriverContainerOverrideDoc]   (NEW, doc-only; references component_configs by name)

Deployment
  └── config (JSON)
        └── components: { <name>: ComponentConfigBlock{ env_vars?, command?, args? } }   (command/args NEW)

ComponentContext (resolved, per reconcile)
  ├── env_vars: ResolvedComponentEnvVars?
  └── container_override: ResolvedComponentContainerOverride{ command?, args?, is_orphaned }   (NEW)
        ▲
        └── produced by ContainerOverridesResolver(component_overrides, driver_components)
```
