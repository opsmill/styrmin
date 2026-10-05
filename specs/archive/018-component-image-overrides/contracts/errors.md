# Contract: Typed errors

All subclass `ServiceError`. Raised from a GraphQL resolver, they surface `extensions.code` plus
metadata through `StructuredErrorExtension`; a render failure in the operator reaches the user only
as the CR status message (see `COMPONENT_CONTAINER_NOT_FOUND`).

## New

### `INVALID_IMAGE_REFERENCE` — `InvalidImageReferenceError`

`services/image_overrides/exceptions.py`. Raised on write (`deploy`, `updateDeployment`), on
`updateDeploymentVersion`, and at render (operator).

| Metadata | Type | Notes |
|---|---|---|
| `component_name` | `str` | |
| `reference` | `str` | stored string |
| `reason` | `"grammar" \| "missing_tag_or_digest" \| "template_expression" \| "after_substitution"` | |
| `application_version` | `str \| null` | the version substituted, when one was |

Message example: `Image override for component 'server' is invalid: "registry.example/acme/app" has no tag or digest (add ":<tag>", "@sha256:<digest>", or ":{{ app.version }}").`

At render the operator records it as `HelmRelease creation failed: <message>` (ADR-057 §4 path);
the code itself does not survive the StyrminDeployment CR → operator hop.

### `UNKNOWN_COMPONENT_IMAGE_OVERRIDE` — `UnknownComponentImageOverrideError`

Raised on write when a block with a non-null `image` names a component the deployment's driver
version does not declare. Metadata: `component_name`, `known_components`. Mirrors
`UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`.

### `COMPONENT_CONTAINER_NOT_FOUND` — `ComponentContainerNotFoundError`

`services/component_container/exceptions.py`. Built by the operator when a HelmRelease fails on the
guard (research D-004). Recorded on the StyrminDeployment status (reason
`ComponentContainerNotFound`, message below) and synced to `Deployment.crdStatus`.

| Metadata | Type |
|---|---|
| `component_name` | `str` |
| `container` | `str` |

Message: `Component 'server': component container 'wrong-name' was not found in its rendered workload. Styrmin never adds a container; fix components.server.container in the driver specification file.`

## Changed

### `COMPONENT_CONTAINER_NOT_DECLARED` — `ComponentContainerNotDeclaredError`

Now raised for image overrides too. New metadata key `override: "env_vars" | "image"` (defaults to
`"env_vars"`, so existing callers and messages are unchanged). The image message reads:
`Image override targets component 'database', which declares no component container in the deployment's driver. Components that accept overrides: ['server']`.
