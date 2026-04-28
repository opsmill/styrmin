# Feature Specification: external-dns endpoints-type opt-in for application Ingress

**Feature Branch**: `001-external-dns-endpoints-type`
**Created**: 2026-04-28
**Status**: Draft
**Input**: GitHub issue [opsmill/styrmin#129](https://github.com/opsmill/styrmin/issues/129) — operator-facing knob to emit `external-dns.alpha.kubernetes.io/endpoints-type` on the application Ingress so external-dns can publish AAAA records that point at the workload node's external IPv6 instead of the Service `ClusterIP`.

## Clarifications

### Session 2026-04-28

- Q: E2E test coverage scope — dedicated new scenario, unit tests only, or extend existing? → A: Extend an existing dedicated-Traefik ingress E2E scenario to set `external_dns_endpoints_type` and assert the rendered annotation; do **not** create a new dedicated E2E scenario.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - IPv6/Cloudflare operator opts in to NodeExternalIP records (Priority: P1)

A platform operator running an IPv6/Cloudflare-fronted topology (Cloudflare → workload node IPv6 → Traefik) needs external-dns to publish the **node's** external IPv6 as the AAAA record for each application hostname. Today the rendered Ingress carries no `endpoints-type` annotation, so external-dns falls back to its default behaviour and uses the Service `ClusterIP` (typically v4-only on a v4-primary cluster), producing AAAA records that point Cloudflare at an unreachable address.

The operator wants to set a single configuration value on their Cluster, Environment, or Deployment so that every application Ingress emitted by Styrmin's dedicated-Traefik path carries `external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP`. They expect the value to inherit through the existing Cluster → Environment → Deployment merge in the same way as `fqdn_suffix`, `external_url_scheme`, `external_url_port`, and `ingress_class`.

**Why this priority**: This is the entire feature. Without this annotation, the IPv6/Cloudflare deployment recipe is broken in production — the workload is unreachable through Cloudflare. There is no deployment-time workaround inside Styrmin today; operators would have to hand-patch every rendered Ingress.

**Independent Test**: Configure a deployment with `external_dns_endpoints_type: "NodeExternalIP"` at any layer (cluster, environment, or deployment), reconcile the deployment, and inspect the rendered Ingress object. The annotation `external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP` must be present alongside the existing `hostname` and `cloudflare-proxied` annotations.

**Acceptance Scenarios**:

1. **Given** a cluster config with `external_dns_endpoints_type: "NodeExternalIP"`, **When** Styrmin renders the application Ingress for any deployment in that cluster, **Then** the resulting annotations include `external-dns.alpha.kubernetes.io/endpoints-type: NodeExternalIP` alongside the existing `external-dns.alpha.kubernetes.io/hostname` and `external-dns.alpha.kubernetes.io/cloudflare-proxied` annotations.
2. **Given** a cluster config without `external_dns_endpoints_type` set (or explicitly `None`), **When** Styrmin renders the application Ingress, **Then** no `external-dns.alpha.kubernetes.io/endpoints-type` annotation is emitted, and every other annotation in the existing set renders identically to the pre-change output.
3. **Given** a deployment-level override of `external_dns_endpoints_type: "ClusterIP"` on top of a cluster-level `"NodeExternalIP"`, **When** the resolved config is computed, **Then** the rendered Ingress carries `endpoints-type: ClusterIP` (deployment overrides cluster, matching the existing merge precedence used for `fqdn_suffix` and `ingress_class`).

---

### User Story 2 - Reject invalid values at config load time (Priority: P2)

An operator who misspells the value (e.g. `"nodeexternalip"`, `"node-external-ip"`, `"PodIP"`) should learn about the mistake immediately when the config is loaded, not silently render an invalid annotation that external-dns rejects at runtime.

**Why this priority**: Cheap to enforce and prevents a silent-failure mode where a typo produces a deployment that "works" until external-dns logs a warning that nobody reads. Without it, the cost of getting the value wrong is a broken AAAA record in production.

**Independent Test**: Attempt to load a config (cluster, environment, or deployment level) where `external_dns_endpoints_type` is set to any string other than `"NodeExternalIP"` or `"ClusterIP"`. The load must fail with a validation error that names the offending field and lists the accepted values.

**Acceptance Scenarios**:

1. **Given** a config containing `external_dns_endpoints_type: "PodIP"`, **When** Styrmin loads the config, **Then** validation fails and the error message identifies `external_dns_endpoints_type` and the accepted values (`"NodeExternalIP"`, `"ClusterIP"`).
2. **Given** a config containing `external_dns_endpoints_type: null` (explicit `None`), **When** Styrmin loads the config, **Then** validation succeeds and the field is treated as unset (no annotation emitted).

---

### Edge Cases

- **Field unset at every layer**: No `endpoints-type` annotation is emitted. The rendered annotation set is byte-identical to the pre-change output for any existing deployment.
- **Field set only at the cluster layer**: Every deployment in that cluster (across all environments and applications using the dedicated-Traefik ingress path) inherits the value and emits the annotation.
- **Field set at multiple layers**: The deepest layer wins. Deployment overrides Environment which overrides Cluster, matching the merge precedence already used for `fqdn_suffix` / `ingress_class`.
- **Dedicated-Traefik path not in use**: This issue scopes the change to the dedicated-Traefik application-Ingress rendering path. Other ingress emission paths (if any) are explicitly out of scope.
- **External-dns not installed in the cluster**: The annotation is inert noise — Kubernetes accepts arbitrary annotations and the rendered Ingress remains valid. Installing/configuring external-dns is an operator prerequisite tracked separately.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The resolved deployment configuration MUST expose an optional setting named `external_dns_endpoints_type` whose accepted values are exactly `"NodeExternalIP"`, `"ClusterIP"`, or unset (treated as "do not emit").
- **FR-002**: The setting MUST be accepted at the Cluster, Environment, and Deployment configuration layers, and MUST inherit through the same Cluster → Environment → Deployment merge already used for `fqdn_suffix`, `external_url_scheme`, `external_url_port`, and `ingress_class`.
- **FR-003**: When the resolved value is `"NodeExternalIP"` or `"ClusterIP"`, the dedicated-Traefik application Ingress emitted by Styrmin MUST carry an `external-dns.alpha.kubernetes.io/endpoints-type` annotation whose value is the resolved string. The annotation MUST sit in the same annotation dictionary as the existing `external-dns.alpha.kubernetes.io/hostname` and `external-dns.alpha.kubernetes.io/cloudflare-proxied` annotations.
- **FR-004**: When the resolved value is unset (`None` at every layer), the rendered Ingress MUST NOT include an `external-dns.alpha.kubernetes.io/endpoints-type` annotation. Styrmin MUST NOT inject a runtime default. The rest of the annotation set MUST be unchanged from the pre-feature behaviour.
- **FR-005**: Configuration loading MUST reject any value other than `"NodeExternalIP"`, `"ClusterIP"`, or unset, and the rejection MUST surface at config-parse time (not at reconcile time), with an error message that names the offending field and lists accepted values.
- **FR-006**: The setting MUST carry operator-facing documentation that explains when to set it — specifically, that `"NodeExternalIP"` is required for IPv6 / dual-stack clusters where the published AAAA record must resolve to the node's external IP rather than the Service `ClusterIP`.
- **FR-007**: Existing deployments that do not set `external_dns_endpoints_type` MUST render an Ingress whose annotation set is byte-identical to the pre-feature output. Existing automated checks that capture the current annotation set MUST continue to pass without modification (or be updated only to assert the new annotation's absence).
- **FR-008**: End-to-end coverage MUST be achieved by extending an existing dedicated-Traefik ingress E2E scenario to set `external_dns_endpoints_type` on the resolved config and assert the resulting Ingress carries the expected annotation. A new standalone E2E scenario MUST NOT be added — the inheritance/render path is already exercised by the existing scenario, and bolting the assertion onto it avoids duplicate fixture cost.

### Key Entities

- **Resolved deployment configuration**: The merged view of Cluster + Environment + Deployment configuration that the agent consults when rendering an application's Kubernetes resources. Already carries `fqdn_suffix`, `external_url_scheme`, `external_url_port`, and `ingress_class`. This feature adds one more sibling field, `external_dns_endpoints_type`, with the same inheritance behaviour.
- **Application Ingress (dedicated-Traefik path)**: The Kubernetes Ingress object emitted by Styrmin for an application when the dedicated-Traefik ingress utility is in use. Today carries the `traefik.ingress.kubernetes.io/router.entrypoints`, `external-dns.alpha.kubernetes.io/hostname`, `external-dns.alpha.kubernetes.io/cloudflare-proxied`, and (conditionally) `kubernetes.io/ingress.class` annotations. This feature adds one conditional sibling annotation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator on an IPv6/Cloudflare topology can switch a cluster from broken (Cloudflare proxying to an unreachable v4 ClusterIP) to working (Cloudflare proxying to the node's external IPv6) by editing exactly one configuration field and re-reconciling — no hand-patching of rendered manifests, no out-of-band tooling.
- **SC-002**: Zero existing deployments change behaviour when this feature ships. Every deployment whose configuration does not set the new field renders an Ingress whose annotation set is byte-identical to the pre-feature output, verified by existing annotation-set checks continuing to pass without modification.
- **SC-003**: Misconfiguration is caught at config-load time, not at reconcile time. An operator who sets the field to an invalid value sees a clear validation error before any Kubernetes resource is rendered, surfaced at the same point in the workflow as existing validation of sibling ingress fields.
- **SC-004**: All three observable behaviours — annotation present with `"NodeExternalIP"`, annotation present with `"ClusterIP"`, annotation absent when unset — are exercised by unit-level automated checks on the rendering path, so the contract is regression-protected at the unit tier.
- **SC-005**: At least one existing dedicated-Traefik ingress E2E scenario asserts the rendered annotation when `external_dns_endpoints_type` is set on the resolved config, so the full Cluster → Environment → Deployment merge path is exercised end-to-end without adding a parallel E2E fixture.

## Assumptions

- The dedicated-Traefik application-Ingress emission path is the only Ingress rendering path in scope. Other rendering paths (if introduced later) are responsible for honouring the same field.
- Installing and configuring external-dns on the target cluster is an operator prerequisite, tracked in a sibling issue. Styrmin's responsibility ends at emitting the correct annotation; it does not deploy or manage external-dns itself.
- The set of accepted values is exactly `"NodeExternalIP"` and `"ClusterIP"` — the two values the existing IPv6/Cloudflare recipe needs. Other external-dns endpoint types (e.g. `PodIP`, `HostIP`) are out of scope and may be added in a follow-up if a concrete deployment recipe requires them.
- The merge precedence for the new field follows the same rules already in use for `fqdn_suffix` and `ingress_class`: deeper layers (Deployment) override shallower layers (Environment, then Cluster); an unset value at a layer means "inherit", not "clear".
- "InstanceConfig" in the original issue text is shorthand for the resolved configuration the agent reads at render time. The field lives on the shared base used by the Cluster, Environment, and Deployment layers so it inherits uniformly — no per-layer-only restriction.
