# Contract: Component-container post-render patches

Emitted by `build_component_container_patches(context)`
(`services/component_container/patch_builder.py`) and appended last in
`ApplicationHelmReleaseBuilder.build()`.

## Emission rule

For each component `N` with component container `C` (`component.config.container`):

- `env` = resolved env vars when present, non-orphaned and non-empty, else none;
- `image` = `component.image_override` when present (live components only), substituted and
  validated (research D-006 to D-008), else none;
- if neither: emit nothing (no reorder, no new Helm revision for that component);
- else, for `kind` in `("Deployment", "StatefulSet")`, both targeted by
  `{kind, labelSelector: <identifier label>}`:

### 1. Strategic merge (`ContainerEnvPatch`, env optional)

```yaml
apiVersion: apps/v1
kind: <kind>
metadata: {name: any}
spec:
  template:
    spec:
      containers:
      - name: <C>
        env:                    # omitted when no env vars apply
        - {name: K, value: V, valueFrom: null}
```

### 2. JSON6902 (`ComponentContainerPatch`)

`G` = `/spec/template/spec/styrmin.io~1component-container~1<esc(N)>~1<esc(C)>`, where `esc`
JSON-pointer-escapes (`~` → `~0`, `/` → `~1`).

With an image override:

```yaml
- {op: move, from: /spec/template/spec/containers/0, path: G}
- {op: remove, path: G/image}
- {op: add, path: G/image, value: <resolved reference>}
- {op: move, from: G, path: /spec/template/spec/containers/0}
```

Env vars only:

```yaml
- {op: move, from: /spec/template/spec/containers/0, path: G}
- {op: copy, from: G/image, path: G/styrmin-image}
- {op: remove, path: G/image}
- {op: move, from: G/styrmin-image, path: G/image}
- {op: move, from: G, path: /spec/template/spec/containers/0}
```

## Guarantees (verified, research D-001 to D-003)

| Situation | Outcome |
|---|---|
| `C` exists in the matched workload | `C` at `containers[0]` with the new image (and env); other containers, `initContainers`, and `imagePullPolicy` unchanged |
| `C` missing from a matched workload | Render fails with `error in remove for path: 'G/image' …`; no container is added; the HelmRelease is not upgraded |
| Kind matches no workload | No-op |
| `Job`, `CronJob`, `DaemonSet` sharing the label | Never targeted |
| Steady state | Patches are a pure function of the context, so the HelmRelease is identical across reconciles and no pods restart |
| Clear | Patches are regenerated each render; with no override the image patch is gone and the chart image renders |

## Operator signature match

The operator treats a HelmRelease `Ready=False` condition whose message contains
`styrmin.io~1component-container~1` as a guard failure, parses `<esc(N)>` and `<esc(C)>` from the
key that precedes `/image`, unescapes them, and fails the deployment with
`COMPONENT_CONTAINER_NOT_FOUND` ([errors.md](errors.md)).
