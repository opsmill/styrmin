# Contract: GraphQL Schema Deltas

These deltas trip the GraphQL governance gate. After implementing: regenerate `schema.graphql` (`uv run styrmin export graphql-schema schema.graphql`), run `uv run invoke generate`, and ship propagation tests (§Propagation below).

All additive — no field is renamed or removed, so existing operations are unaffected.

## 1. Input: extend `ComponentConfigInput`

**File**: `backend/styrmin_backend/api/definitions/deployment/inputs.py`

```graphql
input ComponentConfigInput {
  name: String!
  envVars: [EnvVarInput!]          # existing
  command: [String!]               # NEW — entrypoint override; null = "do not touch", omit-from-list semantics
  args: [String!]                  # NEW — args override
}
```

Field descriptions (Strawberry `description=`):

- `command`: *"Container entrypoint override for this component, scoped to this deployment. A non-empty list of strings; an empty list raises `INVALID_CONTAINER_COMMAND`. `null`/omitted leaves the persisted value untouched (clear by submitting the component block without it under full-replacement). Passed through verbatim — no templating."*
- `args`: *"Container args override for this component. Same shape and rules as `command`, raising `INVALID_CONTAINER_ARGS`."*

**Semantics (ADR-018, unchanged from env-vars)**: top-level `components` is full-replacement; within an entry, omitting `command`/`args` (via `_convert_value` dropping `None`) means the field is absent from the persisted block → effectively cleared on a full-replacement write. Submitting `command: []` is an explicit invalid value (rejected), NOT a clear.

**Conversion (`_flatten_components`)**: `command`/`args` pass through unchanged — they are already plain `list[str]`; no flatten step. Duplicate component `name` continues to raise `DUPLICATE_COMPONENT_NAME`.

No change required to top-level `UpdateDeploymentInput` (the new fields live on the per-component entry) or to the `deploy` mutation (its `config: JSON` carries `components[<name>].command/args` opaquely).

## 2. Output: new `ComponentContainerOverrides` + resolver

**File**: `backend/styrmin_backend/api/definitions/deployment/model.py`

```graphql
type ComponentContainerOverrides {
  component: String!
  command: [String!]      # null when no command override resolved for this component
  args: [String!]         # null when no args override resolved for this component
  isOrphaned: Boolean!    # true when the current driver no longer declares this component
}

extend type Deployment {
  componentContainerOverrides: [ComponentContainerOverrides!]!
}
```

Resolver behaviour (mirrors `Deployment.component_env_vars`):

- Loads `DeploymentConfig.components[<name>].{command,args}`, the driver's declared component names, and runs `ContainerOverridesResolver`.
- **Live** components with neither `command` nor `args` set are omitted (tidy surface).
- **Orphaned** blocks are always surfaced with `isOrphaned: true` and the stored values; never injected into pods (FR-005, FR-013).
- Cleared fields are returned as `null` (absent) — FR-007 Sc.3.

## 3. Driver doc surface: `ApplicationDriverVersion.containerOverrides`

**File**: `backend/styrmin_backend/api/definitions/application_driver/model.py`

```graphql
type DriverContainerOverrideDoc {
  component: String!
  description: String!
  container: String        # informational: which rendered container the override targets
  command: Boolean!        # advertises command overridability
  args: Boolean!           # advertises args overridability
}

extend type ApplicationDriverVersion {
  containerOverrides: [DriverContainerOverrideDoc!]!
}
```

Resolver mirrors `ApplicationDriverVersion.env_vars`: reads the JSON column, returns `[]` when absent, hydrates each entry from the stored dict. Doc-only — informational (FR-010/FR-011).

## Propagation tests (Constitution §V, ADR-014) — mandatory

**Directory**: `backend/tests/functional/graphql/`

1. **Per-field round-trip** (`test_container_overrides_propagation.py`):
   - `updateDeployment` with `components: [{name, command, args}]` → assert persisted `Deployment.config["components"][name]["command"/"args"]` exactly equals input; assert `componentContainerOverrides` projects it back.
   - Clear: omit `command` under full-replacement → assert key absent from persisted block and from read.
   - Unknown component → assert `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE` extension code + `known_components` payload; assert no write occurred.
   - Empty list → assert `INVALID_CONTAINER_COMMAND` / `INVALID_CONTAINER_ARGS`.
   - Non-string element → assert the corresponding typed code.
   - Orphan after driver upgrade → assert `componentContainerOverrides` returns the block with `isOrphaned: true`.
2. **Schema-walking field coverage** (extend the existing `ComponentConfigInput`/introspection test): assert
   `set(ComponentConfigInput fields) == {camelCase(f) for f in ComponentConfigBlock.model_fields}`
   so any future field added to `ComponentConfigBlock` (or the input) without its counterpart fails CI.
3. **Driver doc propagation**: materialise a driver whose spec declares a `container_overrides` block → assert `ApplicationDriverVersion.containerOverrides` returns it with correct `component`/`command`/`args`/`container`.
