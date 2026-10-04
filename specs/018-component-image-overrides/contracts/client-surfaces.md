# Contract: Client surfaces (UI, CLI, SDK, driver actions)

## Token check (shared)

`\{\{\s*app\.version\s*\}\}`, in `frontend/src/lib/image-reference.ts` and
`styrmin_sdk/models/image_reference.py`. The image-reference grammar check (frontend only on the
client side) uses the shared vectors in `frontend/src/lib/image-reference.vectors.json`, which the
backend unit tests also read.

## UI

| Surface | Behaviour |
|---|---|
| Configuration drawer → component section, component **with** a component container | "Image" text input; empty = no override; inline error for grammar, missing tag/digest, or a foreign `{{ }}`/`{% %}`; hint: "Use `{{ app.version }}` to follow the application version; a literal tag pins the image." |
| Same, component **without** a component container | No input. A stored override is shown read-only with a Remove action, and the "not applied" text the env var editor uses |
| Read summary (`ComponentOverridesSummary`) | Per component: stored reference, resolved reference, and an "applied" / "not applied" badge from `isApplicable` |
| Drawer footer | Review & apply is disabled while any image field is invalid, with the hint "Fix the invalid image reference on <components> before applying." |
| Upgrade dialog (deployment detail page) | When at least one applicable override has no token: a warning before Confirm listing those components: "These components keep their pinned image after the upgrade: server (registry.example/acme/app-patched:1.0.0)." |
| Review & apply diff dialog | Shows image additions, changes, and removals like other component fields |

## CLI: `styrminctl deployments apply`

When a manifest changes an existing deployment's application version and the effective config
carries token-free image overrides, one line per deployment goes to stderr after its outcome line:

```text
updated my-app
warning: my-app: pinned image override on server will not follow version 1.1.0 (no {{ app.version }} token)
1 created, 1 updated, 0 unchanged, 0 failed
```

Exit code is unchanged (warning only). Not emitted on create.

## SDK

- `DeploymentResource.get()` returns `component_image_overrides`.
- `ApplyOutcome.pinned_image_components: list[str]` (every token-free effective override; applicability not consulted).
- `ApplyOutcome.target_version: str | None`, set on an `updated` outcome that changes the version (the CLI warning names it).
- `styrmin_sdk.models.image_reference.pinned_image_components(overrides) -> list[str]`.

## Driver actions: `get_component_images(component, context)`

Same signature and return type (`list[str]`). When `context.components[component].config.container`
is set and present in the pod template, its image is element 0. The in-repo `upgrade` actions use
`images[0]`, strip any `@digest`, and strip the tag only when the part after the last `:` has no
`/` (a registry port survives).
