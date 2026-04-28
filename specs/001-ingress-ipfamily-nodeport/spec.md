# Feature Specification: IP Family & Fixed NodePort Knobs for Dedicated Ingress Service

**Feature Branch**: `001-ingress-ipfamily-nodeport`
**Created**: 2026-04-28
**Status**: Draft
**Input**: User description: GitHub issue [opsmill/styrmin#130](https://github.com/opsmill/styrmin/issues/130) — extend the per-environment dedicated Traefik Service with three optional knobs: `ip_families`, `ip_family_policy`, and `node_port`, so operators can pin the Service to IPv6/dual-stack on multi-family clusters and give Cloudflare a stable NodePort origin.

## Clarifications

### Session 2026-04-28

- Q: Required end-to-end test coverage scope for this feature? → A: Option D — automate E2E for the fixed-NodePort path on the existing single-family test cluster, document a manual-validation runbook for the IPv6 dual-stack *traffic* flow, and track automated dual-stack *traffic* E2E as a follow-up. Constraint: extend the existing `backend/tests/e2e/test_ingress_controller.py` rather than introducing a new E2E module. **Refinement (post-`/speckit.analyze`)**: the same E2E test ALSO deploys with `ip_families: ["IPv4"]` + `ip_family_policy: "SingleStack"` set and asserts the Traefik Service object's `spec.ipFamilies` / `spec.ipFamilyPolicy` reflect the requested values — proving Styrmin's rendering reaches the cluster end-to-end. This closes the §V "net-new functionality must ship with E2E" gate for the rendering layer; only cluster-side IPv6 *traffic* verification remains in the manual runbook.

## User Scenarios & Testing

### User Story 1 — Pin a dedicated ingress Service to IPv6 on a dual-stack cluster (Priority: P1)

A platform operator is deploying an application (e.g. Infrahub) behind Cloudflare. The target Kubernetes cluster is dual-stack (IPv4 + IPv6 nodes), but the operator's recipe requires the Service to advertise an IPv6 address only, so that DNS publishes a stable AAAA record and Cloudflare's origin lookup hits the v6 path. Today, the operator has no Styrmin-supported way to force the Service onto a specific IP family — they must rely on an unspecified cluster default and accept whatever the controller picks. The operator wants to set the Service's IP family list and policy declaratively in their environment config and have the dedicated ingress Service come up pinned to that family on the next reconcile.

**Why this priority**: This is one of two blocking gaps for the IPv6/Cloudflare-fronted Infrahub recipe on a real dual-stack cluster. Without a way to pin the family, the Service may bind v4-only on some clusters, breaking AAAA publication and Cloudflare's origin lookup with no fallback inside Styrmin.

**Independent Test**: Set `ip_families` and/or `ip_family_policy` on `dedicated_ingress.service` in an environment config, redeploy on a dual-stack-capable cluster, and confirm the rendered Service object carries the requested `ipFamilies` / `ipFamilyPolicy` and routes traffic on the chosen family. Each field can be set independently — setting only the policy or only the family list both produce a well-formed config.

**Acceptance Scenarios**:

1. **Given** an environment config that sets `ip_families: ["IPv6"]` and `ip_family_policy: "SingleStack"`, **when** the dedicated ingress is deployed, **then** the rendered chart values pin the Service's `ipFamilies` to `[IPv6]` and `ipFamilyPolicy` to `SingleStack`, and the resulting Service in-cluster reports the same values.
2. **Given** an environment config that sets `ip_families: ["IPv4", "IPv6"]` and `ip_family_policy: "RequireDualStack"`, **when** the dedicated ingress is deployed, **then** the rendered chart values request both families and the dual-stack policy.
3. **Given** an environment config where neither `ip_families` nor `ip_family_policy` is set, **when** the dedicated ingress is deployed, **then** the rendered chart values omit both keys entirely and Kubernetes / the cluster's default policy applies, exactly as today.
4. **Given** an environment config with `ip_families: []` (empty list), `ip_families: ["IPv6", "IPv6"]` (duplicates), or `ip_families: ["foo"]` (unknown family), **when** the configuration is loaded, **then** validation fails immediately with a clear error message and no deployment is attempted.

---

### User Story 2 — Pin a fixed NodePort for a Cloudflare origin (Priority: P1)

The same operator runs the dedicated Traefik Service as `type: NodePort` so Cloudflare can target a node IP directly on a known port. Cloudflare's origin configuration requires a port that does not change. Today, when no NodePort is set, Kubernetes assigns a random port in the `30000–32767` range, and that port can change across cluster restarts or Service recreations — forcing the operator to chase port drift in Cloudflare. The operator wants to set a single port value on the Service config and have both the HTTP (`web`) and HTTPS (`websecure`) Traefik entrypoints come up on that port, so Cloudflare can be configured once and stay correct.

**Why this priority**: This is the second blocking gap for the Cloudflare-fronted recipe. Without it, every cluster lifecycle event risks breaking Cloudflare's origin configuration. There is no current workaround inside Styrmin — the chart-values template has the relevant block commented out.

**Independent Test**: Set `node_port: <30000–32767>` on `dedicated_ingress.service` (with `type: "NodePort"`) and redeploy. Confirm that both the `web` and `websecure` Traefik entrypoints expose the chosen NodePort, and that the value survives a controller restart. Independent of User Story 1 — the fixed NodePort works on a single-family cluster too.

**Acceptance Scenarios**:

1. **Given** a service config with `type: "NodePort"` and `node_port: 30443`, **when** the dedicated ingress is deployed, **then** both Traefik's `web` and `websecure` entrypoints expose NodePort `30443` and the value persists across reconciles.
2. **Given** a service config with `type: "NodePort"` and `node_port` unset, **when** the dedicated ingress is deployed, **then** the rendered chart values omit any explicit NodePort and Kubernetes assigns one at random — preserving today's behavior.
3. **Given** a service config with `type: "LoadBalancer"` and `node_port: 30443`, **when** the configuration is loaded, **then** validation fails immediately with an error message that names the conflicting fields and explains that `node_port` is only valid with `type: "NodePort"`.
4. **Given** a service config with `node_port: 0`, `node_port: 65536`, or a negative value, **when** the configuration is loaded, **then** validation fails with a port-range error before any deployment is attempted.

---

### User Story 3 — Pre-existing deployments redeploy unchanged (Priority: P2)

Operators with existing dedicated-ingress configurations that do **not** set any of the three new fields must see no behavioral change. Their rendered chart values must be byte-identical to today's output, their Services must come up with the same shape, and no validation errors must be surfaced for configs that were valid before this feature shipped.

**Why this priority**: Keeping existing operators on a stable contract is a hard requirement for shipping this change without coordinating an upgrade with every consumer. Lower than P1 only because it is a non-regression guarantee, not a new capability.

**Independent Test**: Run the existing dedicated-ingress unit and snapshot test suites unchanged against the new code path. They must all pass without modification. Operators with stored configs that omit the new fields must be able to redeploy without error and observe the same rendered Service.

**Acceptance Scenarios**:

1. **Given** an existing environment config that does not set `ip_families`, `ip_family_policy`, or `node_port`, **when** the dedicated ingress is rendered to chart values, **then** the output is byte-identical to the pre-feature output for the same input.
2. **Given** the existing dedicated-ingress test suite, **when** the new feature is shipped, **then** every existing assertion passes without modification.

---

### Edge Cases

- An IP family list that contains entries other than `IPv4` / `IPv6` (typo, future family) must be rejected at config load — not silently passed through to Kubernetes.
- A duplicate-entry IP family list (e.g., `["IPv6", "IPv6"]`) must be rejected at config load even though the cluster API would also reject it; failing fast keeps a misconfigured deployment from reaching the cluster.
- A `node_port` set together with a non-NodePort Service type is a definitively invalid combination and must be rejected with a message that names both fields, not silently dropped.
- A `node_port` outside the TCP/UDP port range `[1, 65535]` (including `0` and negative numbers) must be rejected at config load.
- The cluster may reject a `node_port` value that is outside the cluster's configured NodePort range (commonly `30000–32767`). This feature does not attempt to police that range at config load — Kubernetes' own error from the apply step is the source of truth, since the range is cluster-configurable.
- Setting `ip_family_policy: "RequireDualStack"` on a single-family cluster will fail at the cluster level. This feature does not pre-validate cluster topology; the operator is responsible for matching the policy to the cluster.

## Requirements

### Functional Requirements

- **FR-001**: The dedicated ingress Service configuration MUST accept an optional list of IP families restricted to the values `IPv4` and `IPv6`, expressing which IP families the Service should publish.
- **FR-002**: The dedicated ingress Service configuration MUST accept an optional IP family policy restricted to the values `SingleStack`, `PreferDualStack`, and `RequireDualStack`, expressing how Kubernetes should treat the family list.
- **FR-003**: The dedicated ingress Service configuration MUST accept an optional fixed NodePort, expressing the port both Traefik entrypoints should expose when the Service type is `NodePort`.
- **FR-004**: When the IP family list is set, validation MUST reject empty lists and lists containing duplicate entries, with a clear error message identifying the offending field, before any cluster mutation occurs.
- **FR-005**: When the fixed NodePort is set, validation MUST reject values outside the inclusive range `[1, 65535]` (including `0` and negative numbers), with a clear port-range error, before any cluster mutation occurs.
- **FR-006**: When the fixed NodePort is set together with a Service type other than `NodePort`, validation MUST reject the combination with an error that names the conflicting fields and states the constraint, before any cluster mutation occurs. The reverse combination (Service type `NodePort` with no fixed NodePort) MUST remain valid and continue to delegate port selection to Kubernetes.
- **FR-007**: Each of the three new fields MUST be optional and default to "unset". When a field is unset, the rendered ingress controller chart values MUST NOT emit the corresponding key, mirroring today's conditional rendering pattern for existing fields like `load_balancer_ip` and `external_traffic_policy`.
- **FR-008**: When the IP family list is set, the rendered chart values MUST emit it under the Service block at the standard Traefik chart key for IP families.
- **FR-009**: When the IP family policy is set, the rendered chart values MUST emit it under the Service block at the standard Traefik chart key for IP family policy.
- **FR-010**: When the fixed NodePort is set, the rendered chart values MUST emit it as the NodePort for both the `web` and `websecure` Traefik entrypoints, applying the same value to both. Splitting the value per entrypoint is explicitly out of scope for this iteration.
- **FR-011**: When none of the three new fields are set, the rendered chart values MUST be byte-identical to the pre-feature output for the same input config. Existing snapshot tests MUST continue to pass without modification.
- **FR-012**: Documentation on the configuration model MUST describe how to combine the three fields for the two canonical scenarios: pinning to IPv6 on dual-stack clusters (`ip_families: ["IPv6"]` + `ip_family_policy: "SingleStack"`), and requesting full dual-stack (`ip_family_policy: "RequireDualStack"`) only on clusters that have both families configured.
- **FR-013**: Test coverage for this feature MUST be delivered as: (a) unit and snapshot coverage in `backend/tests/unit/services/test_ingress_controller.py` covering every new validator and the "byte-identical default" guarantee; (b) automated E2E coverage in `backend/tests/e2e/test_ingress_controller.py` (no new E2E file) that deploys with `node_port`, `ip_families`, and `ip_family_policy` all set, and asserts on the resulting Traefik Service object: (i) `type == "NodePort"` with both `web` / `websecure` entrypoints exposing the chosen port and surviving a reconcile, AND (ii) `spec.ipFamilies` / `spec.ipFamilyPolicy` reflect the requested values — proving Styrmin's rendering reaches the cluster end-to-end on the existing single-family vcluster (using `["IPv4"]` to keep the test in-bounds); and (c) a documented manual-validation runbook at `dev/guides/ingress-ipv6-dual-stack-validation.md` that walks an operator through verifying the IPv6/dual-stack *traffic* pinning on a dual-stack cluster. Automated dual-stack *traffic* validation is explicitly **out of scope** for this iteration and tracked as a follow-up that introduces dual-stack-capable test infrastructure.

### Key Entities

- **Dedicated Ingress Service Configuration**: The block of an environment's (or cluster's) configuration that controls the Kubernetes Service fronting the per-environment dedicated ingress controller. Already exposes the Service type, annotations, load-balancer IP, and external traffic policy. This feature adds three fields: an IP family list, an IP family policy, and a fixed NodePort. All three are optional and default to "unset" (cluster default applies).

## Success Criteria

### Measurable Outcomes

- **SC-001**: An operator deploying the Cloudflare-fronted dual-stack Infrahub recipe can express IPv6 pinning **and** a stable NodePort for the dedicated ingress Service in a single configuration change to one environment config — no out-of-band patches, no post-deploy manual edits.
- **SC-002**: After redeploying with `ip_families: ["IPv6"]` + `ip_family_policy: "SingleStack"` on a dual-stack cluster, the resulting Service exposes only the requested family — verifiable from the in-cluster Service object — and stays pinned across a controller restart.
- **SC-003**: After redeploying with `node_port: <chosen-port>` and Service type `NodePort`, both Traefik entrypoints (`web` and `websecure`) expose the chosen port, and the port survives a Service deletion/recreation cycle (no cluster-assigned drift).
- **SC-004**: Every invalid configuration listed in the Edge Cases section (empty IP family list, duplicate families, unknown family, out-of-range NodePort, NodePort with non-NodePort Service type) is rejected at config load with a single, clear error message naming the offending field(s), before any cluster API call is made.
- **SC-005**: All existing dedicated-ingress unit and snapshot tests continue to pass without modification, and any environment config that does not set the three new fields renders byte-identical chart values to today's output.
- **SC-006**: Both the fixed-NodePort flow AND the IP family rendering pass-through are verified end-to-end by an extension of `backend/tests/e2e/test_ingress_controller.py` (no new E2E file) — the test deploys with `node_port`, `ip_families`, and `ip_family_policy` all set and asserts each makes it onto the resulting Traefik Service object on the existing single-family vcluster. Cluster-side IPv6 *traffic* validation is covered by unit/snapshot tests plus a published manual-validation runbook at `dev/guides/ingress-ipv6-dual-stack-validation.md`; automated dual-stack *traffic* E2E is recorded as a follow-up.

## Assumptions

- The "default-preserved" guarantee is scoped to the per-environment dedicated Traefik Service. Other Service types in the platform are out of scope; this feature touches only the dedicated ingress controller's chart values.
- Both Traefik entrypoints (`web` and `websecure`) get the same fixed NodePort value. The user's recipe does not need them to diverge, and a single-port surface keeps the config minimal. Splitting into per-entrypoint NodePorts is a follow-up iteration — not a breaking change to this one.
- Kubernetes (and the Traefik chart) remain the source of truth for cluster-side policy enforcement. This feature pre-validates only the field shapes and the `node_port`-vs-Service-type interaction; mismatches that depend on cluster topology (e.g., `RequireDualStack` on a single-family cluster, or a NodePort outside the cluster's configured port range) are surfaced by Kubernetes at apply time.
- The chart used by the dedicated ingress controller continues to expose Service-level `ipFamilies` / `ipFamilyPolicy` and per-entrypoint NodePort overrides. If a future chart upgrade changes the schema, the rendering logic will need to follow.
- Existing operators have not relied on the previously commented-out `ports:` scaffold in the chart values template — removing it as part of wiring up the real rendering does not break anyone, because nothing was emitting it.
