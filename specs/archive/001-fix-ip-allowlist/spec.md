# Feature Specification: Activate Per-Deployment IP Allowlist Enforcement

**Feature Branch**: `001-fix-ip-allowlist`
**Created**: 2026-04-28
**Status**: Extracted
**Input**: User description: "Fix Traefik IP allowlist enforcement: uncomment and correct the router.middlewares annotation on the application Ingress so that the per-deployment Traefik 'acl' Middleware is actually referenced. Origin: opsmill/styrmin issue #128."

## Clarifications

### Session 2026-04-28

- Q: When the dedicated ingress utility is enabled but `ip_whitelist` is unset (`None`) or empty (`[]`), what should happen? → A: Skip both the annotation and the allowlist Middleware. Network filtering is opt-in; absence of `ip_whitelist` means no enforcement and no dangling reference.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator-configured IP allowlist actually blocks unauthorized traffic (Priority: P1)

An operator deploys an application through Styrmin and configures `ip_whitelist` on the deployment to restrict network access to a known set of source ranges (e.g., the corporate VPN CIDR). They expect that traffic from sources outside the allowlist is rejected at the ingress layer, while traffic from allowed sources continues to reach the application.

**Why this priority**: This is the entire point of the feature. Today, the configuration is silently ignored — operators believe they have a network restriction in place when they do not. Activating real enforcement closes a security gap that affects every deployment using `ip_whitelist`.

**Independent Test**: Deploy an application with `ip_whitelist` set to a narrow CIDR. From a source inside the CIDR, the request succeeds. From a source outside the CIDR, the request is rejected by the ingress before reaching the application. This can be observed with no other features in play.

**Acceptance Scenarios**:

1. **Given** a deployment is configured with an `ip_whitelist` containing a single source CIDR and the dedicated ingress utility is enabled, **When** a client whose source address falls within the CIDR sends a request to the deployment's hostname, **Then** the request reaches the application and a normal application response is returned.
2. **Given** the same deployment, **When** a client whose source address falls outside the CIDR sends a request to the deployment's hostname, **Then** the request is rejected at the ingress layer before reaching the application.
3. **Given** a deployment whose `ip_whitelist` is updated from a narrow CIDR to a broader CIDR, **When** the deployment is reconciled, **Then** the new allowlist takes effect for subsequent traffic without requiring application restart.

---

### User Story 2 - Deployments without an ingress utility do not gain dangling allowlist references (Priority: P2)

An operator deploys an application that does not use Styrmin's dedicated ingress utility (for example, a deployment that is internal-only or uses a different exposure model). They expect Styrmin to neither create the `acl` Middleware nor reference one from the application's Ingress.

**Why this priority**: A dangling reference to a non-existent Middleware would either break the Ingress reconciliation in Traefik or silently cause unpredictable routing. Avoiding this regression is a precondition for shipping the P1 enforcement.

**Independent Test**: Deploy an application without enabling the dedicated ingress utility. Inspect the resulting Ingress object: it must not carry a `traefik.ingress.kubernetes.io/router.middlewares` annotation that points at an `acl` Middleware.

**Acceptance Scenarios**:

1. **Given** a deployment whose configuration does not enable the dedicated ingress utility, **When** Styrmin renders the deployment's Kubernetes resources, **Then** the application Ingress carries no `router.middlewares` annotation referencing the `acl` Middleware.

---

### User Story 3 - Existing development and test workflows are unaffected by activation (Priority: P2)

A developer running the local dev environment or running the existing end-to-end test suite expects all existing deployment flows to continue working after the IP allowlist becomes a real network restriction. Pre-existing fixtures that previously set `ip_whitelist` for documentation purposes (without expecting it to be enforced) must not start failing because the allowlist now actually restricts traffic.

**Why this priority**: Activating enforcement without addressing pre-existing fixtures would turn a previously-inert configuration value into a breaking change for every developer and CI run. The fix and the fixture migration must ship together.

**Independent Test**: Run the existing dev and end-to-end suites against the change. Every flow that previously passed continues to pass; no flow newly fails because of allowlist enforcement.

**Acceptance Scenarios**:

1. **Given** a fixture or dev configuration that previously set `ip_whitelist` to a placeholder value that was never actually enforced, **When** the activation lands, **Then** the corresponding fixture is updated to a value that does not change observable behavior in dev/test (e.g., an allow-all range), and all pre-existing tests pass without regression.

---

### Edge Cases

- **Allowlist allows all addresses**: When `ip_whitelist` is configured with an allow-all range, the Ingress carries the Middleware reference and the Middleware admits every source — equivalent to no restriction. This is the migration target for fixtures whose previous values were inert.
- **Multiple source CIDRs**: When `ip_whitelist` contains multiple ranges, traffic from any one of them is permitted; traffic outside all of them is rejected.
- **Allowlist is empty or unset**: When `ip_whitelist` is unset (`None`) or empty (`[]`), no allowlist enforcement is applied: the allowlist Middleware is not rendered, and the application's ingress carries no reference to it. The deployment behaves exactly as a deployment without IP filtering would.
- **Reconfiguration after deploy**: Changing `ip_whitelist` after initial deployment takes effect on subsequent traffic without requiring the application pods to restart.
- **Reference correctness across namespace renames**: The Middleware reference on the Ingress always points at the namespace where the `acl` Middleware actually lives, not at a release-derived prefix that may not match the namespace.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When a deployment has the dedicated ingress utility enabled and a non-empty `ip_whitelist` configured, the system MUST cause the application's ingress to enforce the allowlist so that requests from sources outside the allowlist are rejected before they reach the application.
- **FR-002**: When a deployment has the dedicated ingress utility enabled and a non-empty `ip_whitelist` configured, the system MUST permit requests from sources inside the allowlist to reach the application normally.
- **FR-003**: When a deployment does NOT have the dedicated ingress utility enabled, OR has the utility enabled but `ip_whitelist` is unset or empty, the system MUST NOT add any reference to the allowlist Middleware on the application's ingress, and MUST NOT render the allowlist Middleware itself. Both the Middleware resource and the ingress annotation are gated together so a reference to a non-existent resource can never occur.
- **FR-004**: The reference that wires the application's ingress to the allowlist Middleware MUST resolve to the actual location where the Middleware is created (the deployment's own namespace), not to an unrelated identifier.
- **FR-005**: Existing project fixtures and dev configurations that previously set `ip_whitelist` purely as a placeholder MUST be updated, as part of this change, to values that do not alter observable behavior once enforcement becomes real (i.e., allow-all ranges) so that activation is non-breaking for the existing development and test suites.
- **FR-006**: The change MUST be covered by automated tests at two levels: a unit-level test that asserts the application's ingress carries the correct Middleware reference (and only when the ingress utility is enabled), and an end-to-end test that asserts traffic from outside an allowlist is rejected and traffic from inside the allowlist is permitted against a real cluster.
- **FR-007**: All pre-existing automated tests MUST continue to pass after the change lands; no test may be removed, skipped, or weakened to accommodate enforcement.

### Key Entities

- **Deployment**: A managed application instance with its own namespace, configuration (including `ip_whitelist`), and set of Kubernetes resources rendered by Styrmin.
- **IP Allowlist (`ip_whitelist`)**: A list of source address ranges that the operator declares as permitted; absence or emptiness implies no restriction.
- **Allowlist Middleware (`acl`)**: A Traefik resource created in the deployment's namespace whenever the dedicated ingress utility is enabled; it encodes the allowlist rules and is the enforcement point.
- **Application Ingress**: The Kubernetes Ingress object that exposes the deployment's application; it must reference the allowlist Middleware so that Traefik applies allowlist filtering on the request path.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For deployments with `ip_whitelist` configured and the dedicated ingress utility enabled, 100% of requests originating from outside the configured allowlist are rejected at the ingress layer (verified by an end-to-end test that exercises both an in-range and an out-of-range source).
- **SC-002**: For the same deployments, 100% of requests originating from inside the configured allowlist reach the application and receive a normal response (verified by the same end-to-end test).
- **SC-003**: Across all deployments produced by Styrmin, 0% have a `router.middlewares` annotation pointing at an allowlist Middleware that does not exist (i.e., no dangling references either when the ingress utility is disabled or when `ip_whitelist` is unset/empty).
- **SC-004**: After activation, the existing development environment and the existing end-to-end test suite continue to run to completion with zero new failures attributable to allowlist enforcement.
- **SC-005**: An operator can change a deployment's `ip_whitelist` and observe the new allowlist enforced on subsequent requests without restarting the application.

## Assumptions

- Styrmin deployments each occupy their own namespace, and the convention for that namespace name is derived from the deployment identifier. The allowlist Middleware lives in this same namespace, so the application's ingress reference must use the namespace as its prefix to identify the Middleware.
- "Dedicated ingress utility" is a per-deployment concept: a deployment either has Styrmin manage its ingress (in which case the `acl` Middleware is rendered alongside) or it does not. The allowlist annotation must follow the same gating, so the two are always in sync.
- Pre-existing fixtures that set `ip_whitelist` to a single literal address (e.g., the loopback address) were placeholders authored when the configuration was inert; those fixtures are not exercising allowlist behavior and do not require IP-filtering coverage. Replacing them with an allow-all range preserves their original intent.
- Out-of-range traffic being "rejected at the ingress layer" is sufficient to satisfy enforcement; the exact rejection mechanism (HTTP status code, connection reset, etc.) is left to the ingress controller's standard behavior and does not need to be specified here.
- The change is a security-correctness fix, not a feature introduction. Operators who have configured `ip_whitelist` explicitly expect it to be enforced; activating real enforcement is the intended behavior, even though it changes what happens to traffic that was previously (silently) admitted.
