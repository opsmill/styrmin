# ADR-035: Post-render injection — per-feature toggles applied to a static pod-template-bearing kind list

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-pod-scheduling-config/research.md (Decisions 8, 9)

## Context

Hierarchical scheduling config is materialised into Kubernetes manifests by post-render Kustomize patches applied to the Helm output. Two design questions arise:

1. **Opt-out granularity**: drivers occasionally produce manifests that already carry scheduling primitives (a chart that ships its own affinity, tolerations, or resource requests). Operators need a way to say "leave my pre-set affinity alone for this deployment / component" without disabling *all* injection. How fine-grained should the opt-out be?
2. **Patch targeting**: Kubernetes has many pod-template-bearing resource kinds (`Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`, plus assorted CRDs that embed `spec.template.spec`). Kustomize strategic-merge patches need a target selector — which kinds does the platform target?

Both decisions thread through a single ADR because the opt-out toggles are applied per-kind in the patch list, and the kind list determines the maximum surface the toggles can act on.

## Decision

### Opt-out granularity — per-feature booleans at deployment and component scope

`SchedulingConfig.inject: PostRenderInjection | None = None` is a sub-object with six independent booleans, all defaulting to `true`:

```python
class PostRenderInjection(BaseModel):
    pod_affinity: bool = True
    node_affinity: bool = True
    topology_spread: bool = True
    resources: bool = True
    tolerations: bool = True
    runtime_class: bool = True
```

A `false` value on any toggle means the post-renderer **leaves that feature untouched** for the scope it applies to. Opt-out is expressible at **deployment** and **component** scopes only — not at environment scope. The component-level flag takes precedence over the deployment-level flag for that component (matching the per-component override semantics of other fields in [[0033-scheduling-merge-semantics]]).

### Patch targeting — static list of pod-template-bearing kinds

Post-render Kustomize patches use a `target.kind` selector enumerating six kinds, with a kind-specific template path:

| Kind | Template path |
|------|---------------|
| `Deployment` | `spec.template.spec` |
| `StatefulSet` | `spec.template.spec` |
| `DaemonSet` | `spec.template.spec` |
| `Job` | `spec.template.spec` |
| `ReplicaSet` | `spec.template.spec` |
| `CronJob` | `spec.jobTemplate.spec.template.spec` |

The injector iterates `kinds × components × enabled-features` to produce one strategic-merge patch per `(kind, component, feature)` combination.

## Consequences

- Operators who run charts with pre-set scheduling primitives can preserve them surgically — opt out of `pod_affinity` without losing platform-applied `resources` injection, opt out per-component when one component is special.
- The schema is closed and easy to validate. The booleans-only approach was chosen over an enum (`"inject" | "skip" | "merge"`) because `merge` semantics for arbitrary scheduling shapes are ambiguous (whose key wins in a list merge?) and the `replace: true` per-kind escape in [[0033-scheduling-merge-semantics]] already covers the "merge with override" cases.
- Environment-scope opt-out is **not** supported (spec clarification Q4). Operators wanting to opt out across an environment must do so at each deployment — by design, to keep the opt-out surface narrow and discoverable.
- The six-kind list covers every core Kubernetes workload. Custom CRDs that embed `spec.template.spec` (e.g., Argo `Workflow`, Knative Service, batch operator CRDs) are **not** covered by injection in v1. Operators using such CRDs opt out of the relevant feature at deployment scope and inject values themselves via driver templates.
- Patch list size is bounded by `O(kinds × components × features)`, not `O(resources × components × features)` — iterating kinds rather than concrete rendered resources keeps the Kustomize input small even for charts that render many copies of the same kind.

## Alternatives Considered

- **All-or-nothing `post_render_inject: bool`**: rejected by spec clarification Q4. Too coarse — operators routinely want platform-managed resources while preserving driver-managed affinity, or vice versa.
- **Per-resource-kind opt-out**: rejected by spec clarification Q4. Unnecessary granularity — operators opt out by *feature* (affinity, resources, etc.), not by Kubernetes kind. Tying opt-outs to specific Kubernetes kinds also leaks Kubernetes-version-specific knowledge into operator config.
- **Enum `inject` / `skip` / `merge` per feature**: considered but rejected as overdesign. `merge` semantics across nested scheduling shapes are not single-valued (which key wins in a labelSelector merge? which weight wins for preferred affinity?). The boolean form composes with the explicit merge semantics elsewhere in the design.
- **Wildcard kind selector with JSONPath introspection**: rejected. Kustomize does not support "match only resources that contain `spec.template.spec`" — the kind has to be enumerated. A wildcard would still need a path expression that probes the rendered structure, which Kustomize's strategic-merge engine cannot do.
- **Discover kinds at render time by scanning rendered manifests**: rejected. The HelmRelease's Kustomize pipeline is declarative; pre-listing the kinds we target is simpler and predictable. Run-time discovery would tie patch generation to materialised manifests, breaking the dry-run path.
