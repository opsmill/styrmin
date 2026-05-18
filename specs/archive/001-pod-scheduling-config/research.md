# Phase 0 Research — Hierarchical Pod Scheduling & Resource Configuration

All NEEDS CLARIFICATION items from the Technical Context are resolved below. The feature spec already captured high-level clarifications during its drafting session (2026-04-20); this document records the downstream technical decisions and their rationale.

## 1. How to extend the existing hierarchical configuration model

**Decision**: Add a single optional `scheduling: SchedulingConfig | None = None` field to `BaseConfigSection` (so it is inherited by `ClusterConfig`, `EnvironmentConfig`, `DeploymentConfig`, `ResolvedConfig`). Component-level scheduling lives on the existing `Component.config: dict` JSON column under the same `scheduling` key — the driver-arbitrary component fields continue to coexist because `ArbitrarySectionModel` uses `ConfigDict(extra="allow")`.

**Rationale**:
- Reuses the hierarchical pattern already established for `ingress_class`, `ip_whitelist`, and `dedicated_ingress` (`backend/styrmin_backend/context/models/config.py:52–122`). Operators discover the feature in the same place they set other hierarchical defaults.
- Zero database migration: the four existing `config: dict | None` JSON columns absorb the new section verbatim.
- `BaseConfigSection` inheritance already guarantees the field is resolvable at Cluster, Environment, and Deployment levels via the existing `_resolve_instance_config` dict-merge in `context/resolvers.py:53–63`.
- The spec explicitly places the feature's authoring interface "through the same mechanism they use for other hierarchical deployment settings today" (spec Assumptions → Authoring interface), so following the existing pattern is the lowest-risk path.

**Alternatives considered**:
- *A sibling table (`SchedulingConfig` with FKs to Cluster/Environment/Deployment/Component)*: Rejected. Requires a migration, doubles the read path, and duplicates the merge logic that already exists for `config`.
- *A single `pod_template_overrides: dict` catch-all patch field*: Rejected. Loses type safety, validation, and provenance metadata that Story 5 requires.

## 2. Cluster-level versus Environment-level scheduling defaults

**Decision**: Accept scheduling defaults at Environment, Deployment, and Component levels — not at Cluster level. The `scheduling` field is nonetheless placed on `BaseConfigSection` for Pydantic convenience; `ClusterConfig` sets `scheduling = None` by convention and the resolver ignores any cluster-level value.

**Rationale**:
- FR-001/FR-002/FR-003/FR-004 each specify environment/deployment/component — Cluster is out of scope.
- Cluster-level node labels and taints are a *cluster admin* concern, not a per-application concern. Matching that boundary in the data model avoids confusion about where to set what.
- Placing the field on `BaseConfigSection` is an implementation detail that keeps one Pydantic class per level consistent; skipping the cluster value in the merge step is a one-liner.

**Alternatives considered**:
- *Split the field class hierarchy to omit `scheduling` on `ClusterConfig` entirely*: rejected as more surface-area for marginal gain; the resolver-level skip is clearer.

## 3. Resource types covered by the `extended` map

**Decision**: CPU, memory, and ephemeral-storage are first-class fields on `ResourceSpec` (`requests.cpu`, `limits.memory`, etc.). Every other Kubernetes resource (hugepages variants, `nvidia.com/gpu`, vendor extended resources) goes into `requests.extended: dict[str, str]` and `limits.extended: dict[str, str]`. Each extended entry is validated as a parseable Kubernetes quantity via a shared `_validate_quantity()` helper, but no first-class per-resource semantics are implied.

**Rationale**:
- Matches the spec clarification (2026-04-20 session, Q3).
- Keeps the common case (CPU/memory/ephemeral-storage) strongly typed while the long tail stays permissive.
- Validating only the quantity syntax means we do not need to track a hand-maintained list of extended resource names — forward compatibility with future Kubernetes extended resources is free.

**Alternatives considered**:
- *A single flat `resources: dict[str, dict[str, str]]` map with no first-class fields*: rejected — loses editor autocompletion and per-field validation for the 95% case.
- *Expand the first-class list to include hugepages*: rejected — hugepages have several named variants (`hugepages-2Mi`, `hugepages-1Gi`, …) that suit the opaque map better.

## 4. Affinity merge semantics (accumulation vs. replacement)

**Decision**: Default merge is accumulative. Required (`requiredDuringSchedulingIgnoredDuringExecution`) terms are concatenated across levels (ANDed by the scheduler). Preferred (`preferredDuringSchedulingIgnoredDuringExecution`) terms are merged into a single weighted list preserving per-level weights. Any level may set `replace: true` on its affinity block to discard shallower-level terms for affected components; the flag is scoped per affinity-kind (`podAffinity`, `podAntiAffinity`, `nodeAffinity`) so replacing one kind does not affect the other kinds.

**Rationale**:
- Clarification session answer (Q1).
- Accumulation matches operator expectations that environment-wide safety rules (e.g., "never co-locate two replicas of a critical service") compose with deployment-specific affinities rather than being silently shadowed.
- `replace: true` at per-kind granularity gives a clean escape hatch without accidentally clobbering unrelated rules when a narrow override is needed.
- Implementation is straightforward: for each kind, walk levels in order; collect terms; if a level has `replace: true` for that kind, reset the accumulator before adding that level's terms; continue accumulating deeper levels unless they also set `replace: true`.

**Alternatives considered**:
- *Deepest-level wins by default*: rejected — makes it impossible to layer environment-wide safety rules without restating them at every deployment.
- *Global replace flag (affecting all kinds)*: rejected — too blunt; operators usually want narrow control.

## 5. Topology-spread constraints merge key

**Decision**: Union across levels keyed by `(topologyKey, whenUnsatisfiable)`. When two levels set a constraint with the same key, the deepest-level entry wins for that key (FR-010b).

**Rationale**:
- `topologyKey` alone is insufficient: an operator might legitimately want `topology.kubernetes.io/zone` with `DoNotSchedule` at one level and the same topology key with `ScheduleAnyway` at a deeper level as a different constraint.
- Including `whenUnsatisfiable` in the key matches how the Kubernetes scheduler itself treats these constraints — each `(topologyKey, whenUnsatisfiable)` pair is an independent rule.
- Deepest-level-wins per key preserves the mental model used for scalar fields.

**Alternatives considered**:
- *Simple concatenation with no dedup*: rejected — two different levels both setting zone-spread would result in duplicate, possibly contradictory rules.
- *Key on `topologyKey` only*: rejected for the reason above.

## 6. Affinity-by-deployment-reference resolution

**Decision**: Add `deployment_id` to the existing `context.labels` mapping in `services/context.py:125` so that the existing `TemplateLabelPatch` pipeline stamps `styrmin/deployment_id: <uuid>` onto every pod-template-bearing resource (alongside the already-present `styrmin/environment_id`). Affinity rules that reference a deployment by platform identifier are expanded at resolve time into a `labelSelector: {matchLabels: {styrmin/deployment_id: <target-uuid>}}`, scoped to the referencing deployment's namespace/environment.

**Rationale**:
- Clarification session answer (Q5) requires no new `styrmin.io/app` label plumbing — the platform's existing identity labels are sufficient.
- The pod-template label is already produced by the post-renderer via `TemplateLabelPatch` (see `agent/service/kubernetes/resources/blocks/patches.py:174–187`). We only need to add the new key to `context.labels`; the patch builder requires no changes.
- Expanding the reference at each reconcile (FR-001d) matches how the rest of the platform re-renders on every reconciliation — no stale selector risk.
- Raw `labelSelector`-based rules remain supported for targeting pods the platform did not render (escape hatch required by FR-001c).

**Alternatives considered**:
- *Introduce a new `styrmin.io/app` identifier label*: explicitly rejected by the spec.
- *Use the driver's component-identifier label (`infrahub/service`, etc.)*: rejected — those labels are driver-owned, vary between drivers, and cannot be used to target "another deployment's pods" across drivers.
- *Use `podAffinityTerm.namespaceSelector`*: kept as an available field but not required for cross-namespace cases in v1; our affinity-by-deployment rule operates within the environment's namespace by default, matching FR-001d's visibility rule.

## 7. Runtime-class validation

**Decision**: Validate the runtime-class name at two points:
1. **Configuration time (FR-006)**: a syntactic check (non-empty DNS-1123 subdomain). *(Still in effect.)*
2. ~~**Rollout time (FR-018)**: existence verification against the target cluster's `RuntimeClass` API (`node.k8s.io/v1`). Reuse the existing cluster `capabilities` mechanism (`Cluster.capabilities` JSON column) — the existing cluster-capability discovery worker periodically lists available runtime classes; the resolver consults that cache. A miss causes `RuntimeClassNotFoundError` before the HelmRelease is applied.~~ **Reverted after shipping.** The allow-list (`ClusterConfig.available_runtime_classes`) and the cluster-side existence check were dropped; any DNS-1123-valid name passes. An unknown class surfaces as a Pending pod during reconciliation rather than a pre-apply rejection. Reintroducing validation would require a discovery worker populating `Cluster.capabilities` from the live `node.k8s.io/v1` API.

**Rationale**:
- Clusters routinely roll out new runtime classes out-of-band (e.g., a new sandboxed runtime); blocking configuration on existence would require live cluster reads from the API path. The capability cache is the standard pattern in the codebase and is already designed to back similar checks.
- Two-stage validation matches SC-005 (≥95% rejected pre-rollout; remaining cases surface clear messages within one reconciliation cycle).

**Alternatives considered**:
- *Configuration-time live cluster check*: rejected — adds a synchronous dependency on cluster reachability to the GraphQL mutation path.
- *No configuration-time check*: rejected — syntactic errors should be rejected early per FR-006.

## 8. Post-renderer opt-out wiring

**Decision**: Represent opt-outs as a boolean-valued `inject: PostRenderInjection | None = None` sub-object on `SchedulingConfig`. The sub-object carries six independent booleans (defaulting to `true`): `pod_affinity`, `node_affinity`, `topology_spread`, `resources`, `tolerations`, `runtime_class`. A `false` value means the post-renderer leaves that feature untouched for the applicable scope. Opt-out is expressible at both deployment and component scopes; component-level flag takes precedence over deployment-level for that component (FR-016).

**Rationale**:
- Clarification session answer (Q4) pinned granularity at per-feature and scope at deployment + component. Environment-scope opt-out was rejected in that clarification to keep the surface narrow.
- Booleans keep the schema closed and easy to validate; an enum like `"inject" | "skip" | "merge"` was considered but rejected as overdesign.
- Component-level override pattern already matches how other component-level fields override deployment-level defaults in the existing config hierarchy.

**Alternatives considered**:
- *All-or-nothing `post_render_inject: bool`*: rejected by clarification (Q4).
- *Per-resource-kind opt-out*: rejected by clarification (Q4) — unnecessary granularity; operators opt out by feature, not by K8s kind.

## 9. Pod-template-bearing resource detection

**Decision**: Apply post-render patches with a `target` selector keyed by Kubernetes `kind` for each of the well-known pod-template-bearing kinds: `Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`. For each kind, build a strategic-merge patch rooted at the correct template path:
- `Deployment`, `StatefulSet`, `DaemonSet`, `ReplicaSet`, `Job`: `spec.template.spec`
- `CronJob`: `spec.jobTemplate.spec.template.spec`

**Rationale**:
- Matches FR-014 (must apply to all pod-template-bearing kinds).
- Kustomize's strategic-merge patch supports multiple targets in one `postRenderers` block; we iterate per kind rather than per resource, keeping the patch list size bounded (O(kinds × components × features) rather than O(resources × components × features)).
- These six kinds cover every core Kubernetes workload. Custom CRDs that embed `spec.template.spec` (e.g., Argo `Workflow`) are not covered in v1; operators that use such CRDs can opt out of the relevant feature at deployment scope and inject values themselves.

**Alternatives considered**:
- *Wildcard `kind` with JSONPath introspection*: rejected — Kustomize does not support "match only resources that contain `spec.template.spec`".
- *Discover kinds at render time by scanning rendered manifests*: rejected — the HelmRelease's Kustomize pipeline is declarative; pre-listing the kinds we target is simpler and more predictable.

## 10. Provenance metadata for Story 5

**Decision**: Produce a `resolved_scheduling.provenance: dict[str, Literal["environment", "deployment", "component"]]` map alongside the resolved `SchedulingConfig` inside each `ComponentContext`. Keys are dotted paths into the resolved structure (e.g., `"resources.limits.cpu"`, `"affinity.pod.required[0]"`). Lists accumulated across levels record provenance per element.

**Rationale**:
- FR-012 requires "enough metadata for a template to determine which level provided each value" — a dotted-path map is the minimum sufficient representation.
- Dotted paths are trivially consumed from Jinja templates; drivers that want granular information can index into the map.
- For accumulated lists, per-element provenance is more useful than a single list-level source ("the tolerations list is from multiple levels").

**Alternatives considered**:
- *A second parallel `SchedulingConfig` shaped with `(value, source)` tuples per field*: rejected — doubles the schema complexity for a rarely-read field.
- *Only record provenance for scalars*: rejected — operators need to know which level added a given toleration when debugging.

## 11. Audit trail integration

**Decision**: Leverage the existing deployment timeline / task history for the MVP. Every `updateEnvironment` / `updateDeployment` / `updateComponentConfig` mutation that touches `scheduling` produces a timeline entry containing the before/after `scheduling` diff. No dedicated audit table in v1.

**Rationale**:
- The spec's FR-021 is satisfied by "actor, timestamp, level, field, before/after" — all of which are recordable on the existing timeline entry (`ContextDiff` + task metadata).
- Adding a separate audit log is a governance-gated change (new DB schema) and would duplicate information already captured.
- Expanding the timeline/diff surface is purely additive.

**Alternatives considered**:
- *Dedicated `AuditLog` table*: deferred — can be adopted later without breaking this feature if a broader platform-wide audit requirement emerges.

## 12. Frontend scope

**Decision**: Read-only display only in this feature's implementation:
- `EnvironmentDetailPage`: show environment-level `scheduling` section under the existing overview/config surface.
- `DeploymentDetailPage`: show the resolved per-component `scheduling` configuration and, for each field, a chip indicating its source level (Story 5 / SC-004).

Write-side UI (forms to edit scheduling config per level) is out of scope for v1; operators edit via GraphQL mutations or the existing config editor pattern. A follow-up ticket can add structured forms.

**Rationale**:
- Matches SC-004 ("operators identify the resolved effective value and its source level… in under 30 seconds via the deployment status view") — the read-only view is the primary acceptance target.
- Form UX for affinity is non-trivial; staging it avoids blocking the backend-core value that Stories 1–6 deliver.
- Minimises scope creep and keeps the PR reviewable.

**Alternatives considered**:
- *Full write-side UI in v1*: deferred.

## Summary of Resolved NEEDS CLARIFICATION items

| Item | Resolution |
|---|---|
| Where in the config model? | Extend `BaseConfigSection` with optional `scheduling`. |
| Cluster-level defaults? | No — Environment is the shallowest level. |
| Resource types? | CPU/memory/ephemeral-storage first-class + opaque `extended` map. |
| Affinity merge? | Accumulate by default; `replace: true` per affinity-kind. |
| Topology-spread key? | `(topologyKey, whenUnsatisfiable)`. |
| Deployment-reference affinity? | Existing `styrmin/environment_id` + add `styrmin/deployment_id` to `context.labels`. |
| Runtime-class validation? | Syntactic at config-time; existence via cluster capabilities at rollout-time. |
| Opt-out granularity? | Per-feature booleans at deployment + component scope. |
| Pod-template kinds? | Static list (Deployment, StatefulSet, DaemonSet, Job, CronJob, ReplicaSet). |
| Provenance surface? | Dotted-path `provenance` map alongside resolved config. |
| Audit? | Reuse deployment timeline. |
| Frontend scope? | Read-only in v1; write-side UI deferred. |
