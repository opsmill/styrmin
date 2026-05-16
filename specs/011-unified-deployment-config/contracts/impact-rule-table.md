# Contract — Impact rule table format

**Status**: Internal contract for the v1 frontend impact heuristic. Designed to be swappable with a backend-computed impact response in a future iteration without restructuring the dialog UI.

## File

`frontend/src/lib/impact-rules.ts`

## Schema

```ts
export interface ImpactRule {
  /**
   * Glob-style path matcher applied to DiffEntry.path.
   *
   * Glob syntax:
   *   - `.` segment separator (matching dotted paths from the diff)
   *   - `*` matches a single path segment, e.g. `scheduling.resources.*`
   *   - `**` matches zero or more segments, e.g. `scheduling.**`
   *   - `[*]` matches any array index/key segment
   *
   * Value qualifier (optional, space-separated suffix):
   *   - `value:X`  — only fires when DiffEntry.after === "X"
   *   - `kind:add` / `kind:remove` / `kind:change` — only fires for that change kind
   *
   * Examples:
   *   "name"
   *   "scheduling.resources.**"
   *   "tolerations[*].effect value:NoExecute"
   *   "envVars[*] kind:add"
   */
  matcher: string;

  /** Consequence text rendered in the dialog's Impact section. */
  consequence: string;

  severity: 'informational' | 'warning' | 'high';
}
```

## Rule evaluation contract

`lib/config-impact.ts::evaluateImpact(diff: ConfigurationDiff, rules: ImpactRule[]): ImpactSummary` MUST:

1. Iterate `diff.entries`; for each entry, find every rule whose matcher matches.
2. Group rule firings by `consequence` text (case-sensitive) to deduplicate. The output `ImpactEntry` records every triggering `DiffEntry.path` under `triggeringPaths`.
3. Order the output by descending severity (high → warning → informational), then by first appearance.
4. Compute `topSeverity` as the maximum across all entries.
5. Return `{entries: [], topSeverity: 'informational'}` for an empty diff — never crash.

## Initial rule table

The rules below ship in slice 4. They are deliberately approximate; the critique phase reviews them and may refine wording or severity. Later iterations may add or refine entries as production telemetry shows what changes actually trigger restarts.

| Matcher | Consequence | Severity |
|---|---|---|
| `name` | Deployment will be renamed; no pod restart | informational |
| `parameters.**` | Driver will be re-rendered; pods may restart depending on parameter semantics | warning |
| `scheduling.resources.**` | Pods will be recreated with new resource limits | warning |
| `scheduling.tolerations` | Pods on affected tainted nodes may be evicted | warning |
| `scheduling.tolerations[*].effect value:NoExecute` | Existing pods on tainted nodes will be drained immediately | high |
| `scheduling.nodeAffinity` | Pods will be rescheduled to match new node affinity | warning |
| `scheduling.podAffinity` | Pods will be rescheduled to match new pod affinity | warning |
| `scheduling.podAntiAffinity` | Pods will be rescheduled to match new pod anti-affinity | warning |
| `scheduling.topologySpreadConstraints` | Pods will be redistributed across topology domains | warning |
| `scheduling.runtimeClass` | Pods will be recreated under new runtime class | warning |
| `envVars[*]` | Pods will be recreated to pick up new environment | warning |
| `ipWhitelist` | Ingress controller allowlist will be reconfigured | informational |
| `dedicatedIngress` | Dedicated ingress controller will be reconciled | warning |
| `ingressClass` | Ingress + external DNS records will be reconfigured | warning |
| `fqdnSuffix` | External DNS records will be republished under the new suffix | warning |
| `externalUrlScheme` | External URL scheme will change; clients with hard-coded schemes may need updates | warning |
| `externalUrlPort` | External URL port will change; clients with hard-coded ports may need updates | warning |
| `externalDnsEndpointsType` | External DNS endpoint source will change; records may be republished | warning |
| `dbSize` | Database resize may schedule a managed-DB action and trigger a brief unavailability window | warning |
| `standardStorage.storageClass` | Standard storage class change applies to newly-provisioned volumes only; existing volumes are unaffected | informational |
| `nodeSelector` | Pods will be rescheduled to match new node selector | warning |
| `serviceNameOverrides` | Kubernetes Service objects will be renamed; DNS clients will see new names | high |
| `components[*].resources.**` | Affected component's pods will be recreated | warning |
| `components[*]` | Component override block changed; affected component will reconcile | warning |

## Future evolution

When the backend gains a `previewUpdateDeployment(input: UpdateDeploymentInput!): UpdatePreview!` query, `lib/config-impact.ts` will replace its rule-table evaluation with a call to that query. The `ImpactSummary` return shape stays identical, so no consumers (the dialog, tests) change. This is the explicit reason the rule table lives behind a function rather than being inlined into the dialog.
