# Data Model: Per-Component Image Overrides via Post-Render

No database schema change and no Alembic revision: the override lives in the existing
`Deployment.config` JSON column, like env vars and container overrides.

## 1. Stored: `ComponentConfigBlock.image`

`backend/styrmin_backend/context/models/config.py`

| Field | Type | Default | Notes |
|---|---|---|---|
| `env_vars` | `dict[str, str] \| None` | `None` | existing |
| `command` | `list[str] \| None` | `None` | existing (014) |
| `args` | `list[str] \| None` | `None` | existing (014) |
| **`image`** | **`str \| None`** | **`None`** | new: one full image reference, optionally containing `{{ app.version }}` |

Validation rules (`services/image_overrides/reference.py`, research D-006 to D-008):

- non-empty string with no surrounding whitespace;
- after replacing every `\{\{\s*app\.version\s*\}\}` with a version, no `{{`, `}}`, `{%` or `%}`
  remains (`INVALID_IMAGE_REFERENCE`, reason `template_expression`);
- the substituted string matches the image-reference grammar (reason `grammar`) and carries an
  explicit tag or digest (reason `missing_tag_or_digest`);
- the model-level field validator checks the stored string with the token replaced by a neutral
  placeholder tag (`0`), so stored configs re-validate on read without knowing the version. The
  write path and the renderer then re-check with the real application version (reason
  `after_substitution` when only the real version breaks it).

Semantics: `None` or an omitted key means "no override, chart image". An empty string is rejected,
never a clear. Under `updateDeployment` full replacement, omitting `image` from a submitted
component block clears it.

## 2. Context: `ComponentContext.image_override`

`backend/styrmin_backend/context/models/components.py`

```text
ResolvedComponentImageOverride (extra="forbid")
  reference: str        # stored string, token NOT substituted
  is_orphaned: bool = False

ComponentContext
  ... existing fields ...
  image_override: ResolvedComponentImageOverride | None = None
```

- Populated by `services/context.py::_populate_component_image_overrides` from
  `ImageOverridesResolver.resolve_for_deployment(component_overrides, driver_components)`.
- Attached only to live components that have an override; orphans never reach a component context.
- `None` for every component without an override, so contexts of deployments without overrides
  keep the same shape (SC-002).
- Substitution happens in the patch builder (render time), against `context.app.version`.

## 3. Read surface: `ComponentImageOverride` (GraphQL)

```text
ComponentImageOverride
  component: String!           # component name
  reference: String!           # stored reference
  resolvedReference: String!   # token replaced with the deployment's application version
  isOrphaned: Boolean!         # driver no longer declares the component
  isApplicable: Boolean!       # not isOrphaned and the component declares a component container
```

`Deployment.componentImageOverrides: [ComponentImageOverride!]!` returns one entry per component
with a stored override, live first (driver order), then orphans (by name). Components without an
override are omitted.

## 4. Render-time patches

Per component with a component container `C` and at least one of (applicable env vars, image
override), per kind in `(Deployment, StatefulSet)`, targeted by the identifier label selector:

| Order | Patch | Type | Content |
|---|---|---|---|
| 1 | `ContainerEnvPatch` (extended) | strategic merge | `containers: [{name: C}]`, plus `env` entries when env vars apply |
| 2 | `ComponentContainerPatch` (new) | JSON6902 | move `containers/0` to the guard key; guard + optional image set; move back (research D-002) |

Both come after every other post-render patch, as ADR-057 requires for env patches.
`build_component_container_patches(context)` replaces `build_env_var_patches(context)` as the
builder's single entry point.

## 5. Driver contract: `get_component_images`

| Before | After |
|---|---|
| images of every container, pod-template order | same images; the component container's image first when the component declares one and it is present |

## 6. Operator status on a guard failure

| CR status field | Value |
|---|---|
| `phase` | `Failed` |
| `displayState` | `Error` |
| condition `HelmReleaseReady` | `False`, reason `ComponentContainerNotFound` |
| `message` | `ComponentContainerNotFoundError` message naming the component and the container |

## 7. SDK

- `ApplyOutcome.pinned_image_components: list[str] = []`: components whose effective image override
  has no token, filled only when `apply` changes the application version.
- `styrmin_sdk.models.image_reference`: `APP_VERSION_TOKEN_RE`, `has_app_version_token(ref)`, and
  `pinned_image_components(overrides)`, a pure helper used by `apply` and the E2E API driver.

## State transitions

```text
(no override) --set (valid, container declared)--> applied
applied --clear--> (no override)                      [chart image back next reconcile]
applied --driver upgrade drops container--> stored, not applicable (never injected)
applied --driver upgrade drops component--> stored, orphaned (never injected)
stored-not-applicable --remove--> (no override)       [removal always allowed]
applied --render with wrong container name--> reconcile Failed (COMPONENT_CONTAINER_NOT_FOUND)
applied --upgrade to version producing invalid ref--> upgrade rejected (INVALID_IMAGE_REFERENCE)
```
