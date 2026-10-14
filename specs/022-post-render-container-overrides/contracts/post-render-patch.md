# Contract: Post-Render Patches for the Component Container

**Feature**: [../spec.md](../spec.md) | Research D-001, D-003. Extends [018 contracts/post-render-patch.md](../../archive/018-component-image-overrides/contracts/post-render-patch.md).

## When patches are built

For each component in the rendering context, `build_component_container_patches` builds patches when:

1. the component declares a component container (`config.container`), and
2. `applicable_overrides(name, component, app.version)` is not empty: at least one of env vars, image, `command` or `args` applies (not orphaned).

Otherwise the component gets no component container patch. A cleared override contributes nothing.

## What is built, per workload kind (`Deployment`, `StatefulSet`)

Both target `kind` + the component's label selector, in this order, after every other patch in `spec.postRenderers`:

1. **Merge patch** (strategic merge, `ContainerMergePatch`):

   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: any
   spec:
     template:
       spec:
         containers:
         - name: <component container>
           env:                # only when env vars apply (unchanged)
           - name: LOG_LEVEL
             value: debug
             valueFrom: null
           command:            # only when a command override applies (new)
           - /bin/sh
           - -c
           args:               # only when an args override applies (new)
           - --log-level
           - debug
   ```

2. **Guard** (JSON6902, `ComponentContainerPatch`, unchanged): moves `containers/0` to the guard key, removes and restores (or sets) `image`, moves it back.

## Guarantees (tested on real `kubectl kustomize`)

| Guarantee | Test |
|-----------|------|
| A set `command` or `args` replaces the whole list on the component container | integration, FR-002 |
| A field with no override keeps the chart's value (for example an `args`-only override keeps the chart's `command`) | integration, edge case 1 |
| Other containers and init containers are byte-for-byte unchanged | integration, FR-002 |
| The component container moves to `containers[0]` | integration (existing behaviour, ADR-057 §3) |
| A wrong container name fails the render at the guard, also with only `command` or `args` set; `parse_guard_failure` returns `(component, container)` | integration, FR-004 |
| Strings such as `yes`, `8000`, `""`, `null`, `$(VAR)` reach the container as the same strings | unit (patch text) + integration |
| Env-only output is unchanged by this feature | existing integration test `TestEnvOnly` |

## Values that pass through unchanged

`command` and `args` are written as stored. Styrmin does not substitute `{{ app.version }}` in them (out of scope). Kubernetes still expands `$(VAR)` references from the container's env at runtime, as it did on the values path.
