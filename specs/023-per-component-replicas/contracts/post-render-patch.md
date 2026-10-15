# Contract: Component Replica Post-Render Patch

**Feature**: [../spec.md](../spec.md) | Research: [D-003](../research.md#d-003-one-replica-resolver-for-the-patch-the-write-checks-and-the-read-field), [D-004](../research.md#d-004-how-the-replica-patch-reaches-the-workloads)

## Builder

`build_component_replica_patches(context: GlobalContext) -> list[TargetPatch]` in `services/replicas/patch_builder.py`. It replaces `ApplicationHelmReleaseBuilder.build_components_state_post_rendering_patches` and is called at the same place in `ApplicationHelmReleaseBuilder.build()`, so the patches keep the fourth position in `postRenderers[0].kustomize.patches`:

1. utility patches (ingress)
2. label patches
3. component label patches
4. **component replica patches** (this contract)
5. backup annotation patches
6. scheduling patches
7. component container patches (merge, then guard; must stay last)

## Output per component

For each component in `context.components` and each kind in `("Deployment", "StatefulSet")`:

| Component state | Resolved count | Patches emitted |
|-----------------|----------------|-----------------|
| stopped (`enabled: false`) | any | one, `value: 0` |
| running | `N` (override or driver default) | one, `value: N` |
| running | `None` (source `CHART`) | none |

At most one patch per kind per component, so no two patches write `/spec/replicas` on the same workload.

## Patch shape

```yaml
- target:
    kind: Deployment            # then the same for StatefulSet
    labelSelector: app.kubernetes.io/name=simple-app   # identifier.label.label_selectable()
  patch: |
    - op: add
      path: /spec/replicas
      value: 2
```

`SpecPatch(specs={"replicas": N})` renders the JSON6902 text; `N` is an `int`, never a user string. `add` replaces an existing `spec.replicas` and creates a missing one.

## Properties

- Needs no component container (FR-003): the target is the workload, not a container.
- `Job`, `CronJob` and `DaemonSet` are never targeted (ADR-057 §2). A selector that matches no `Deployment` or `StatefulSet` changes nothing.
- The same stored config gives the same patches (Constitution §I). Clearing an override removes its patch; `postRenderers` is replaced as a whole key on update, so the chart's count applies again.
- A singleton component without `replicas` gets `value: 1` even when the chart renders more (FR-007).
- A deployment whose driver declares no `replicas` and no `singleton` and has no override gets no replica patch (SC-006), the same output as before the change for running components.
- The builder logs component names and counts, never config values other than the count.
