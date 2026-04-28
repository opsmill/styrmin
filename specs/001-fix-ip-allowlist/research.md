# Phase 0 Research: Activate Per-Deployment IP Allowlist Enforcement

**Branch**: `001-fix-ip-allowlist`
**Date**: 2026-04-28

The spec has no `[NEEDS CLARIFICATION]` markers; Q1 from `/speckit.clarify` resolved the only material ambiguity (gating when `ip_whitelist` is unset/empty). This document captures the design decisions that pin the implementation.

---

## Decision 1: Namespace derivation strategy

**Decision**: Derive the namespace inside `IngressUtility.build_app_post_rendering_patches` from `context.instance.deployment_id`, using the existing helper `get_kubernetes_reference()` at `backend/styrmin_backend/agent/service/kubernetes/utils.py:7`.

**Rationale**:

- The helper already encodes the canonical convention `f"styrmin-{resource_id}"` and is used throughout the codebase (see `mutation.py:495`, `reporter.py:277`, `service_aliases.py`). Using it keeps the convention in one place.
- `context.instance.deployment_id` is available on `GlobalContext` (`context/models/contexts.py:91`), so no signature change is needed.
- This matches Option 1 from the originating issue's "Threading the namespace" discussion and has the smallest blast radius. It does not change the abstract `Utility` base class, so other utilities are unaffected.

**Alternatives considered**:

- **Option 2 — thread `namespace` as a parameter through `Utility.build_app_post_rendering_patches`**. Symmetric with `build_resources(namespace=...)`, but invasive: requires changes to the abstract base class and the only other implementation, plus the caller in `builders/application.py`. Deferred — can be revisited later if a second utility needs the namespace too.
- **Hard-coding the prefix inline**. Rejected: duplicates a convention already centralised in `get_kubernetes_reference()` and would drift if the convention ever changes.

---

## Decision 2: Gating both the Middleware and the annotation on `ip_whitelist`

**Decision**: When `context.instance.config.ip_whitelist` is `None` or an empty list, neither the `acl` Middleware nor the `router.middlewares` annotation is rendered. Both gates check the same condition and live in the two render paths:

- The Jinja template `ingress-controller-chart-values.j2.yaml` wraps the `acl` middleware entry in `{% if context.instance.config.ip_whitelist %}…{% endif %}`.
- `IngressUtility.build_app_post_rendering_patches` only adds the `traefik.ingress.kubernetes.io/router.middlewares` key when the same condition is true.

**Rationale**:

- Spec clarification Q1 (Session 2026-04-28) selected the "skip both" semantics: network filtering is opt-in; absence of config means no enforcement and no dangling reference.
- Gating in lockstep is the only way to guarantee the spec's FR-003 invariant (the ingress never references a non-existent Middleware). One-sided gating creates a window where the annotation points at a Middleware that wasn't rendered.
- Python's truthiness for `list[str] | None` makes a single `if context.instance.config.ip_whitelist:` check correctly cover both `None` and `[]` without explicit length checks.

**Alternatives considered**:

- **Always render the Middleware with a default allow-all `sourceRange` when `ip_whitelist` is unset**. Rejected: changes the operator's intent (they did not opt into filtering), creates spurious resources, and the e2e suite would lose its "no-filtering" path.
- **Validate at config submission time and reject deployments with an enabled ingress utility but no `ip_whitelist`**. Rejected: turns an optional field into a required one, breaking existing deployments. Also adds a GraphQL/validation surface that is out of scope.

---

## Decision 3: Fixture migration target value

**Decision**: Update fixtures listed in the issue to `ip_whitelist: ["0.0.0.0/0"]`, matching the issue's stated target. Do not unset the field.

**Rationale**:

- Setting an allow-all CIDR keeps the new code path exercised across the entire e2e suite. Every deployment fixture continues to render a Middleware and an annotation; any future regression in either the gating logic or the namespace prefix is caught by existing tests.
- Unsetting `ip_whitelist` would silently route most fixtures down the "skip" branch, leaving the new wiring untested except in the dedicated allow/deny scenario.
- The issue explicitly directs `["0.0.0.0/0"]`. Matching it avoids surprising the issue author and keeps the change reviewable.

**Alternatives considered**:

- **Unset `ip_whitelist` in fixtures**. Rejected for the coverage reason above.
- **Use a per-test-cluster pod CIDR allow-list (e.g., `10.0.0.0/8`)**. Rejected: pod CIDRs differ across vcluster setups and CI runners; `0.0.0.0/0` is the only universally-portable allow-all value.

---

## Decision 4: E2E source-IP strategy for the allow/deny scenario

**Decision**: The new e2e scenario in `test_ingress_controller.py` exercises both directions by configuring `ip_whitelist` such that the test client's effective source IP (as observed by Traefik after `ipStrategy: depth: 1` X-Forwarded-For resolution) is in or out of the range, and asserting:

- In-range source → request reaches the application and a normal application response is returned.
- Out-of-range source → request is rejected at the ingress (HTTP 403 Forbidden, Traefik's default for `IPAllowList`).

The existing template's `ipStrategy: depth: 1` already determines the source-IP semantics; the e2e test does not need to reconfigure it. The test reads the apparent source IP from a permissive baseline run (allow-all) and then re-deploys with a narrow CIDR derived from that observation, plus a definitively-outside CIDR (e.g., a TEST-NET range from RFC 5737) to exercise the deny path.

**Rationale**:

- Source-IP semantics inside vcluster + Traefik are non-trivial (NAT, kube-proxy, X-Forwarded-For depth). Anchoring the test on an observed value rather than an assumed CIDR makes it portable across CI environments.
- HTTP 403 is the documented Traefik default for `IPAllowList` rejection. Asserting on this status (and falling back to "any non-2xx if the deployment is unreachable") gives a stable target without overspecifying Traefik's internals.

**Alternatives considered**:

- **Hard-code `127.0.0.1/32` and a non-loopback CIDR**. Rejected: in-cluster traffic doesn't originate from `127.0.0.1`; this is precisely the bug the fixture migration fixes.
- **Mock Traefik's behavior in a unit test instead of e2e**. Rejected: the spec (FR-006) and the constitution (V. Test-First Development) both require real-cluster e2e for new user-visible behavior.

---

## Decision 5: Unit-test placement for `build_app_post_rendering_patches`

**Decision**: Add unit-level coverage in the existing `backend/tests/unit/` tree, co-located with other `IngressUtility` tests if any exist (search `backend/tests/unit/` for `IngressUtility` first; if none, create a new module under `backend/tests/unit/agent/service/kubernetes/utilities/test_ingress.py` mirroring the source path).

**Rationale**:

- Mirrors the existing convention of mirroring `backend/styrmin_backend/...` paths under `backend/tests/unit/...`.
- Unit-level coverage validates the annotation construction in isolation (no Kubernetes cluster required), which is faster than rediscovering the bug via e2e and is sufficient for the namespace-derivation and gating assertions called for in spec FR-006.

**Alternatives considered**:

- **Add only e2e coverage**. Rejected: unit tests for the patch-construction path are cheap, repeat-runnable in seconds, and prevent regressions of the very bug that motivated this feature (a typo or wrong format string would not be caught e2e until the cluster reconcile fails).
