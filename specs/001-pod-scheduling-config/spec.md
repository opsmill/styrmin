# Feature Specification: Hierarchical Pod Scheduling & Resource Configuration

**Feature Branch**: `001-pod-scheduling-config`  
**Created**: 2026-04-20  
**Status**: Draft  
**Input**: User description: "I want users to be able to define pod affinity rules per app component and have them hierarchical (environment -> deployment -> component); so we can for example have anti affinity rules at the deployment level (no same app within the same environment must be ran on the same node) or affinity rules like (all components for this deployment must run on the same node); I also want users to be able to define resources requests and limits for pods per component in the same manner; and also the same for pod tolerations; and I also want users to be able to specify a runtimeClass per component (in order to sandbox one or more components); note that all the values must be available in the global context (so driver developers can include them in helm values templates) BUT the configuration must be injected through kustomize post renderers by default"

## Clarifications

### Session 2026-04-20

- Q: Affinity hierarchy — should a component-level affinity rule override or accumulate with shallower levels? → A: Accumulate by default with an explicit `replace: true` opt-out at any level to discard shallower terms for that component.
- Q: Scope of scheduling primitives beyond pod (anti-)affinity — include `nodeSelector`, `nodeAffinity`, and/or `topologySpreadConstraints`? → A: Include `nodeAffinity` and `topologySpreadConstraints` at all three levels; intentionally exclude `nodeSelector` (operators use `nodeAffinity` instead).
- Q: Scope of resource types for requests/limits beyond CPU and memory? → A: CPU + memory + ephemeral-storage as first-class fields, plus an opaque `extended` map (resource-name → quantity) for hugepages and extended/vendor resources (e.g., `nvidia.com/gpu`); each entry validated as a parseable Kubernetes quantity only.
- Q: Post-renderer opt-out granularity (FR-016) — all-or-nothing, per-feature, per-resource-kind? → A: Per-feature opt-out at deployment and component scope; the independent toggles are pod-affinity (covers pod affinity and anti-affinity), node-affinity, topology-spread, resources, tolerations, and runtime-class.
- Q: Identity mechanism for pod affinity/anti-affinity that refers to "another app" on the same node? → A: The rule takes a reference to one or more **existing deployments** (not an abstract "app" concept). The platform resolves the reference at rollout time into a `labelSelector` matching the referenced deployments' existing platform-generated identity label(s); no new `styrmin.io/app` label is introduced and no operator-authored label plumbing is required.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Hierarchical Pod Affinity & Anti-Affinity (Priority: P1)

As a platform operator, I want to declare pod affinity and anti-affinity rules for my applications at the environment, deployment, or component level so that I can control how workloads co-locate on cluster nodes — for example, forcing every component of one deployment to run on the same node for latency, or keeping a new deployment off the same node as one or more specified existing deployments for availability.

**Why this priority**: Placement guarantees are the most operationally differentiating capability of the four. Without them, platform operators must accept the default Kubernetes scheduler behaviour, which can collapse availability (multiple replicas on a failing node) or cripple performance (chatty components spread across the cluster). Requests and limits are already broadly supported by Helm charts, but affinity rarely is — making this the highest-value missing primitive.

**Independent Test**: Define an anti-affinity rule on deployment B that references deployment A (pods of B must not land on a node already running a pod of A), and a within-deployment affinity rule on both deployments that binds all components of each deployment to a single node. Deploy A and then B into the same environment and confirm: (a) each deployment's components land on a single node each, and (b) deployment B does not land on the same node as deployment A.

**Acceptance Scenarios**:

1. **Given** a deployment declares an anti-affinity rule that references one or more existing deployments (by their platform identifier), **When** the referencing deployment is rolled out, **Then** the scheduler places its pods on nodes that are not already running pods from any of the referenced deployments, and never reverses that decision after restarts.
2. **Given** a deployment declares "all components on the same node" affinity, **When** the deployment is rolled out, **Then** every component's pods land on a single node and eviction of that node reschedules all components together.
3. **Given** a component declares its own affinity rule without `replace: true`, **When** the deployment is rolled out, **Then** the component's pods apply the component-level rule AND every required term inherited from the deployment and environment levels (ANDed); siblings continue to apply only the inherited rules.
4. **Given** a component declares an affinity rule with `replace: true`, **When** the deployment is rolled out, **Then** the component's pods apply only the component-level affinity and shallower-level terms are discarded for that component; siblings are unaffected.
5. **Given** an affinity rule cannot be satisfied (e.g., no node matches), **When** the deployment is rolled out, **Then** the affected pods remain pending and the deployment status surfaces the unsatisfied constraint to the operator.

---

### User Story 2 - Hierarchical Resource Requests and Limits (Priority: P2)

As a platform operator, I want to declare CPU and memory requests and limits for each component at the environment, deployment, or component level so that workloads get predictable capacity, cluster quotas are respected, and noisy neighbours cannot starve critical components.

**Why this priority**: Resource sizing is the single most frequent adjustment an operator makes between environments (dev small, prod big). Without hierarchical defaults an operator has to re-state sizes for every deployment, which is error-prone and drifts over time.

**Independent Test**: Set environment-level defaults for CPU/memory requests and limits, override one component at the deployment level, override a second component at the component level, then deploy and verify each pod's final resource spec matches the deepest level that set it.

**Acceptance Scenarios**:

1. **Given** an environment sets a default CPU request of 100m and memory request of 256Mi, **When** a deployment is created without overrides, **Then** every component's pods receive those values.
2. **Given** a deployment overrides the memory limit to 2Gi while inheriting CPU defaults from the environment, **When** the deployment is rolled out, **Then** each component has 100m CPU request and 2Gi memory limit.
3. **Given** a single component overrides CPU request to 2 cores, **When** the deployment is rolled out, **Then** only that component has the 2-core request; siblings retain environment defaults.
4. **Given** configured limits exceed the namespace quota, **When** the deployment is applied, **Then** the system rejects the change with an actionable message before pods are created.

---

### User Story 3 - Hierarchical Pod Tolerations (Priority: P3)

As a platform operator, I want to attach tolerations to my components at the environment, deployment, or component level so that pods can schedule onto tainted nodes that are reserved for specific purposes (e.g., GPU pools, spot instances, PCI-compliance pools) without me having to patch every driver.

**Why this priority**: Tolerations are essential for heterogeneous clusters but less frequently changed than resources or affinity — they are usually set once per environment and rarely overridden at the deployment level. They are the natural third slice because the hierarchical data plumbing built for P1 and P2 can be reused directly.

**Independent Test**: Create a tainted node pool (e.g., `dedicated=batch:NoSchedule`), attach a matching toleration at the environment level, deploy an application, and verify its pods can schedule onto the tainted pool. Remove the environment toleration and override at the component level for a single component; verify only that component can schedule on the tainted pool.

**Acceptance Scenarios**:

1. **Given** an environment declares a toleration for `dedicated=batch:NoSchedule`, **When** a deployment is created in the environment, **Then** all components tolerate that taint and can schedule on matching nodes.
2. **Given** a component declares an additional toleration, **When** the deployment is rolled out, **Then** the component receives both the environment-level and the component-level tolerations.
3. **Given** no level sets a toleration for a given taint, **When** the deployment is rolled out, **Then** its pods do not tolerate that taint and are not scheduled onto matching nodes.

---

### User Story 4 - Per-Component Runtime Class for Sandboxing (Priority: P4)

As a platform operator, I want to assign a runtime class (e.g., a sandboxed or hardened runtime) to individual components so that untrusted or security-sensitive workloads run under stronger isolation while the rest of the application continues to use the default runtime.

**Why this priority**: Runtime class is the narrowest of the four capabilities: it is typically applied to a small subset of components (e.g., a plugin executor, a user-provided workload) rather than set cluster-wide. It has the smallest blast radius if deferred but the highest per-use security value when needed.

**Independent Test**: Install two runtime classes on a cluster (e.g., `runc` default and a sandboxed runtime). Assign the sandboxed runtime class to one component of a multi-component deployment, leave the rest with the default, deploy, and verify only the targeted component's pods run under the sandboxed runtime.

**Acceptance Scenarios**:

1. **Given** a component declares a specific runtime class, **When** the deployment is rolled out, **Then** only that component's pods are launched under the named runtime class.
2. **Given** a deployment declares a runtime class at the deployment level, **When** the deployment is rolled out, **Then** every component inherits that runtime class unless it declares its own override.
3. **Given** a configured runtime class does not exist on the target cluster, **When** the deployment is applied, **Then** the system surfaces a clear validation error before pods enter a crash loop.

---

### User Story 5 - Driver Template Access to Scheduling Values (Priority: P2)

As a driver developer, I want the resolved affinity, resource, toleration, and runtime-class values to be exposed in the global context provided to my Helm values template so that I can optionally include them in chart values (for charts that expect them in specific locations) or branch template logic based on them (e.g., sidecar sizing, probe tuning).

**Why this priority**: Exposure in the global context is what keeps drivers flexible enough to support charts that already model these fields. It is P2 because without it, drivers that require these values inside Helm values templates cannot be written; however, the default injection path (Story 6) still delivers the core user value even when drivers do not opt in.

**Independent Test**: Configure non-default values at each level, run a driver whose template reads from the resolved scheduling/resource context, and verify the rendered Helm values contain the correct values at the paths the template specifies.

**Acceptance Scenarios**:

1. **Given** resolved scheduling/resource values exist at each level, **When** a driver template reads them from the global context, **Then** the template receives the fully merged values (after hierarchy resolution), not the raw per-level inputs.
2. **Given** a driver author wants to inspect which level a value came from, **When** the template reads the context, **Then** the source level (environment, deployment, or component) is available for each field.

---

### User Story 6 - Kustomize Post-Renderer Injection as Default (Priority: P1)

As a platform operator, I want the configured scheduling, resource, toleration, and runtime-class values to be injected into the deployed manifests automatically (without requiring the driver author to wire them into Helm values) so that the capability works uniformly across all drivers, including third-party charts I do not control.

**Why this priority**: This is what makes the feature drop-in and chart-agnostic. Without it, every existing driver would need to be updated before operators could use the feature at all. It shares P1 with Story 1 because one of the two must ship alongside the affinity primitive for it to be usable on day one.

**Independent Test**: Deploy an unmodified upstream Helm chart (one that does not reference the scheduling context in its values template) with affinity, resource, toleration, and runtime-class values configured. Inspect the rendered manifests after deployment and confirm each value appears on the correct pod specs without any driver-side changes.

**Acceptance Scenarios**:

1. **Given** a driver does not consume the scheduling context in its Helm values template, **When** the deployment is rolled out, **Then** the rendered pod specs still contain the configured affinity, resources, tolerations, and runtime class.
2. **Given** a driver both consumes values in its template AND the post-renderer is active, **When** the deployment is rolled out, **Then** the post-renderer's injected values are the final authoritative values on the rendered manifest (last-writer-wins, predictable to the operator).
3. **Given** the post-renderer step fails (e.g., a malformed manifest), **When** the deployment is attempted, **Then** the deployment aborts before any partial state is applied to the cluster and the error identifies the failing resource.

---

### Edge Cases

- **Conflicting values across levels**: Two levels specify the same field with different values. The deepest level (component > deployment > environment) wins for scalar fields and single-valued structs; lists (e.g., tolerations) accumulate across levels; affinity and anti-affinity terms accumulate, with required terms ANDed and preferred terms combined into a single weighted list.
- **Unsatisfiable constraints**: Affinity, tolerations, or runtime-class combinations that no node in the cluster can satisfy. Pods remain pending; deployment status must surface the reason.
- **Resources exceeding namespace quotas or LimitRange bounds**: The system validates against cluster policies before applying and rejects the change with an actionable message.
- **Missing runtime class on cluster**: The system validates the named runtime class exists on the target cluster before deployment and fails fast if it does not.
- **Values set but driver consumes them manually in Helm values**: Post-renderer still applies by default; duplicated values produce the same end state. Operators receive documentation warning against manual duplication to avoid confusion about which level produced a value.
- **Removing a level's configuration**: Clearing a value at one level causes the next shallower level's value (or the system default) to take effect on the next reconcile — not stale values from the previously resolved configuration.
- **Partial component selection**: A configuration set at deployment or environment level targets only components declared by the driver; unknown component names are rejected with a clear error at configuration time.
- **Non-pod workload resources**: Some charts render Jobs, CronJobs, or StatefulSets. Injection must apply to every pod-template-bearing resource, not only Deployments.
- **Concurrent edits**: Two operators simultaneously change the same level's configuration. The system applies updates in a serialized order; the later write wins and an audit trail records both.

## Requirements *(mandatory)*

### Functional Requirements

#### Configuration (Authoring)

- **FR-001**: Operators MUST be able to declare pod affinity and anti-affinity rules at the environment, deployment, and component levels.
- **FR-001a**: Operators MUST be able to declare `nodeAffinity` (both required and preferred variants) at the environment, deployment, and component levels. `nodeSelector` is intentionally out of scope; operators express equivalent semantics via `nodeAffinity`.
- **FR-001c**: Pod affinity and pod anti-affinity rules MUST be expressible by referencing one or more target **deployments** (and, optionally, specific components within them) by their platform identifier. The system MUST resolve such references into a Kubernetes `labelSelector` using the existing platform-generated identity label(s) placed on pods by the platform; operators MUST NOT be required to author labels or selectors manually for this case. Raw `labelSelector`-based rules MUST also remain supported as an escape hatch for targeting pods the platform did not render.
- **FR-001d**: The system MUST reject an affinity rule whose deployment reference cannot be resolved (deployment does not exist in the environment, has been deleted, or is not visible to the referrer) with an actionable error at configuration time, and MUST re-evaluate referenced identities on each reconciliation so that changes to the target deployment's identity propagate to the selector.
- **FR-001b**: Operators MUST be able to declare `topologySpreadConstraints` at the environment, deployment, and component levels.
- **FR-002**: Operators MUST be able to declare CPU, memory, and ephemeral-storage requests and limits at the environment, deployment, and component levels. Operators MUST additionally be able to declare any other Kubernetes resource (hugepages variants, extended/vendor resources such as `nvidia.com/gpu`) as a key/value entry in an opaque `extended` map per component; each entry MUST be validated as a parseable Kubernetes quantity but no first-class per-resource semantics are implied.
- **FR-003**: Operators MUST be able to declare pod tolerations at the environment, deployment, and component levels.
- **FR-004**: Operators MUST be able to declare a runtime class at the environment, deployment, and component levels.
- **FR-005**: The system MUST validate that component-level configuration references a component declared by the deployment's driver, and reject unknown component names with an actionable error.
- **FR-006**: The system MUST validate resource, affinity, toleration, and runtime-class values at configuration time (schema validity, supported field shapes, non-negative quantities) and return errors before the configuration is accepted.

#### Hierarchy Resolution

- **FR-007**: The system MUST resolve effective configuration by merging environment → deployment → component in that order.
- **FR-008**: For scalar fields and single-valued structs (e.g., a single runtime-class name, a single resource quantity), the deepest level that sets the field MUST win.
- **FR-009**: For list-valued fields (e.g., tolerations), the effective list MUST be the union of all levels with stable de-duplication (identical entries deduplicated, conflicting but non-identical entries preserved).
- **FR-010**: For affinity and anti-affinity (pod and node), the default merge MUST be accumulative: required terms from all levels MUST be combined conjunctively (all must hold) and preferred terms MUST be merged into a single weighted list preserving each level's weights.
- **FR-010a**: Any level (environment, deployment, or component) MUST be able to set `replace: true` on its affinity block, which MUST cause the resolver to discard all shallower-level affinity terms for the affected component(s) and use only that level's affinity as the effective value. Levels deeper than the one that set `replace: true` MUST continue to accumulate on top of the replacement unless they also set `replace: true`. The `replace: true` flag scope is per-affinity-kind (pod affinity, pod anti-affinity, node affinity) — setting it on one kind MUST NOT affect the merge behaviour of the other kinds.
- **FR-010b**: For `topologySpreadConstraints`, the effective list MUST be the union across all levels, keyed by `(topologyKey, whenUnsatisfiable)`; when two levels set a constraint with the same key, the deepest level's entry MUST win for that key.
- **FR-011**: The resolved configuration for a given deployment MUST be deterministic given the same inputs (no dependence on evaluation order of sibling components).

#### Exposure and Injection

- **FR-012**: The fully resolved scheduling, resource, toleration, and runtime-class values MUST be available in the global context that driver templates consume, alongside enough metadata for a template to determine which level provided each value.
- **FR-013**: By default, the system MUST inject the resolved values into every pod-template-bearing Kubernetes resource rendered by the driver via a post-render step that runs after chart rendering.
- **FR-014**: Post-renderer injection MUST apply to all pod-template-bearing resource kinds rendered by a deployment (Deployments, StatefulSets, DaemonSets, Jobs, CronJobs, ReplicaSets, and any other kind containing a pod template).
- **FR-015**: When both driver-template usage and post-renderer injection place a value on the same field, the post-renderer's value MUST be the final value on the applied manifest, and this precedence MUST be documented for driver authors.
- **FR-016**: Operators MUST be able to opt out of post-renderer injection at per-feature granularity, independently for each of: pod-affinity (covering both pod affinity and pod anti-affinity), node-affinity, topology-spread, resources, tolerations, and runtime-class. Opt-out MUST be expressible at both the deployment and component scopes, with the component-level flag taking precedence over the deployment-level flag for that component. An opted-out feature MUST leave the corresponding field untouched by the post-renderer, allowing a driver (or a custom CRD controller) to take full control of that field while other features continue to be injected.

#### Operational Visibility & Safety

- **FR-017**: The system MUST surface the resolved per-component configuration (including source level per field) to the operator via the deployment's status and/or UI, so they can confirm what will be applied before rollout.
- **FR-018**: When pods remain pending due to unsatisfied affinity, tolerations, or runtime-class constraints, the deployment status MUST identify the unsatisfied constraint and the level that introduced it.
- **FR-019**: Changes to a hierarchical configuration value MUST trigger a reconciliation of affected deployments so that running pods converge to the new effective configuration within the platform's normal reconciliation SLO.
- **FR-020**: Clearing a value at a level MUST cause the next shallower level's value (or the absence of the field) to take effect on the next reconciliation, with no residual value from the prior resolution.
- **FR-021**: All configuration changes at every level MUST be captured in the platform's audit log with actor, timestamp, level, field, and before/after values.

### Key Entities

- **Environment**: A logical grouping of deployments (e.g., `dev`, `staging`, `prod`). Holds environment-wide defaults for affinity, resources, tolerations, and runtime class that apply to every deployment in the environment unless overridden.
- **Deployment**: An instance of a driver-deployed application within an environment. Holds deployment-specific scheduling configuration and inherits unset fields from its environment.
- **Component**: A named part of a deployment (e.g., `server`, `worker`) declared by the driver. Holds component-specific scheduling configuration and inherits unset fields from its deployment and environment.
- **Scheduling Configuration**: The composite set of pod affinity, pod anti-affinity, node affinity, topology spread constraints, resource requests and limits (CPU, memory, ephemeral-storage, plus an opaque `extended` map for hugepages and vendor/extended resources), tolerations, and runtime class that can be expressed at any level. Each field may be present or absent at each level independently.
- **Resolved Scheduling Configuration**: The per-component effective configuration computed by the hierarchy resolution rules. This is what operators see in status and what templates/post-renderer consume. Carries per-field provenance identifying which level contributed it.
- **Post-Renderer Injection**: The default pipeline step that applies the resolved scheduling configuration to every pod-template-bearing resource in a driver's rendered output.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A platform operator can configure node-anti-affinity across a same-app deployment pair and eliminate correlated outages, demonstrated by both deployments landing on distinct nodes in 100% of rollouts during a 30-day observation window.
- **SC-002**: A platform operator can right-size a component across environments (dev to prod) by changing values at the environment and deployment levels only — without touching driver code or component-level overrides — in under 5 minutes end-to-end.
- **SC-003**: At least 80% of drivers already in use at the platform work with the new feature without driver-side changes (delivered via post-renderer), measured by a rollout audit of existing drivers.
- **SC-004**: Operators correctly identify the resolved effective value and its source level (environment, deployment, or component) for any field in under 30 seconds via the deployment status view.
- **SC-005**: Misconfigurations are rejected before rollout in at least 95% of cases across the validation matrix enumerated in `quickstart.md` §9 (unknown component, invalid resource quantity, nonexistent runtime class, unresolvable affinity reference, unsatisfiable affinity); remaining cases surface clear error messaging within one reconciliation cycle.
- **SC-006**: Adding hierarchical scheduling configuration to an existing deployment does not increase rollout time by more than 10% compared to the same deployment without the feature, measured on the reference deployment defined in `tasks.md` T104 (baseline: rollout time without `scheduling` set at any level vs. full scheduling block set at environment level).
- **SC-007**: No more than 1% of deployments experience pods stuck pending for more than 5 minutes due to scheduling-config issues that lacked a diagnostic message pointing at the offending level.

## Assumptions

- **Authoring interface**: Operators configure scheduling values through the same mechanism they use for other hierarchical deployment settings today (e.g., via the existing configuration model that already supports environment-level ingress class, IP whitelist, and similar fields). This feature extends that model rather than introducing a new authoring surface.
- **Permission model**: The permissions required to edit a level's scheduling configuration match the existing permissions to edit that level's other configuration (environment-admins edit environment defaults, deployment-owners edit deployment configs, etc.). No new permission types are introduced.
- **Merge defaults**: For scalar/single-valued fields the deepest level wins; for lists (tolerations) the effective list is the union; for affinity, the default is accumulation (required terms ANDed across levels; preferred terms merged into a single weighted list). Any level can set `replace: true` on its affinity block to discard shallower-level affinity terms when the accumulated behaviour is not desired.
- **Post-renderer scope**: Post-renderer injection targets all pod-template-bearing Kubernetes resource kinds. Non-pod resources (ConfigMaps, Secrets, Services) are unaffected.
- **Driver opt-in model**: Drivers consume resolved values from the global context only when they need to (e.g., legacy charts). The platform does not require drivers to change to benefit from the feature.
- **Cluster-side prerequisites**: Any runtime classes, node labels, and taints referenced by scheduling configuration must exist on the target clusters. The platform validates at configuration time where possible, and at rollout time otherwise, but does not create node-side resources on behalf of the operator.
- **Quota and LimitRange enforcement**: Namespace quotas and LimitRanges are enforced by the Kubernetes API server; the platform surfaces rejections clearly but relies on Kubernetes for the authoritative check.
- **Backwards compatibility**: Existing deployments without any hierarchical scheduling configuration continue to behave exactly as today, with the scheduler's cluster-default placement and no post-renderer modifications to pod specs.
