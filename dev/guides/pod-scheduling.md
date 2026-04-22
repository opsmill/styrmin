# Pod scheduling configuration

This guide summarises how operators configure hierarchical pod scheduling
on Styrmin deployments, and how the platform injects those values onto
pod templates without driver-side changes. The authoritative reference is
`specs/001-pod-scheduling-config/`; the quickstart walks through each
feature step-by-step.

## Where to set

Styrmin resolves `scheduling` from three levels, deepest-wins per field:

```
environment.config.scheduling → deployment.config.scheduling → component.config.scheduling
```

Every field is optional; missing values inherit from the next shallower
level. Clearing a deeper level (omitting the key) reverts the effective
value to the shallower one (FR-020).

## Supported features

| Feature | Field | Merge rule |
|--|--|--|
| Pod affinity / anti-affinity | `pod_affinity`, `pod_anti_affinity` | required + preferred accumulate; `replace: true` per kind resets shallower terms |
| Node affinity | `node_affinity` | same as pod affinity; `topology_key` ignored |
| Topology spread | `topology_spread_constraints` | union keyed by `(topology_key, when_unsatisfiable)`; deepest wins per key |
| Resources | `resources.requests.*`, `resources.limits.*`, `extended` map | per-field deepest wins |
| Tolerations | `tolerations` | union with stable dedup on the full tuple |
| Runtime class | `runtime_class` | deepest wins; must be DNS-1123 and exist in the cluster |

## Affinity by deployment reference

Instead of a raw `label_selector`, an affinity term may carry a
`deployment_ref` that resolves to the platform-stamped
`styrmin/deployment_id` label on every pod template. Narrow further with
`components:` to pick specific components in the target deployment.

## Per-feature opt-out

Every feature group can be opted out at the deployment or component
scope via `scheduling.inject.*`. Component-level flags override
deployment-level flags per-field (not whole-object).

```yaml
scheduling:
  inject:
    pod_affinity: false     # keep driver template's affinity untouched
    resources: true         # still inject resource requests/limits
```

A `None` flag at every level resolves to `True` (inject).

## Post-renderer precedence (FR-015)

Scheduling patches are appended to the HelmRelease
`spec.postRenderers` pipeline **after** driver-template-derived patches,
so Kustomize applies them last — post-renderer wins over driver
template values. Flip the per-feature `inject.*` flag to opt out.

## Reading resolved values in drivers

Drivers that want to branch on the resolved scheduling (e.g. to set a
probe threshold based on resource limits) read
`context.components[*].scheduling.config` and
`context.components[*].scheduling.provenance` in their Jinja values
template. The same shape is available read-only via the GraphQL
`Deployment.resolvedScheduling` field for the UI.
