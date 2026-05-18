# Implementation Plan: Activate Per-Deployment IP Allowlist Enforcement

**Branch**: `001-fix-ip-allowlist` | **Date**: 2026-04-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-fix-ip-allowlist/spec.md`

## Summary

Fix the `acl` Traefik Middleware never being referenced from the application Ingress (issue #128). The fix has three coordinated parts:

1. **Wire the annotation**: in `IngressUtility.build_app_post_rendering_patches`, add `traefik.ingress.kubernetes.io/router.middlewares: <namespace>-acl@kubernetescrd` where `<namespace>` is derived from `context.instance.deployment_id` via the existing `get_kubernetes_reference()` helper.
2. **Gate the Middleware AND the annotation together** on `ip_whitelist` being non-empty (per Q1 clarification). When `ip_whitelist` is `None` or `[]`, neither resource is rendered. This requires a conditional in the Jinja template (`ingress-controller-chart-values.j2.yaml`) and a matching `if` in `build_app_post_rendering_patches`.
3. **Migrate fixtures** that previously set `ip_whitelist: ["127.0.0.1"]` (inert under the bug) to `ip_whitelist: ["0.0.0.0/0"]` so activation does not regress existing tests, exactly as the issue specifies.

Tests: unit-level coverage of `build_app_post_rendering_patches` (annotation present iff utility enabled and `ip_whitelist` non-empty; correct namespace prefix), and an extension to `backend/tests/e2e/test_ingress_controller.py` that asserts allow/deny enforcement against a real cluster.

## Technical Context

**Language/Version**: Python 3.13 (backend), authoritative versioning via `uv`.
**Primary Dependencies**: Strawberry GraphQL, Pydantic, Jinja2, Kopf, Traefik (`traefik.io/v1alpha1` Middleware CRD). No new dependencies.
**Storage**: N/A — change is purely in the K8s resource builder; no DB or schema impact.
**Testing**: pytest (unit and e2e); `--pdb` for e2e per AGENTS.md. The e2e suite runs against a real vcluster with the Styrmin operator + Traefik installed.
**Target Platform**: Linux server (Kubernetes cluster); Styrmin agent reconciles per-deployment resources.
**Project Type**: web-service (single backend project; no frontend changes for this feature).
**Performance Goals**: No measurable impact expected. Traefik's `IPAllowList` middleware is in-process at the proxy and adds sub-millisecond filtering per request.
**Constraints**: 120-char line length; `uv run invoke format lint` MUST pass; Python type hints mandatory (ty enforced).
**Scale/Scope**: Per-deployment (one Middleware per deployment namespace). The change touches one source file, one Jinja template, six fixture/dev files (per issue), and adds tests in two places.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | PASS | Resource generation remains deterministic and idempotent: same `(context, release_reference)` produces the same Middleware + annotation set, including the new gating branch. Reconciler diffs continue to converge. |
| II. Driver-Based Deployment | PASS | No driver changes; the fix is in the agent's resource builder, applied uniformly across all drivers. |
| III. Layered Architecture | PASS | Change is confined to the agent service layer (`agent/service/kubernetes/resources/utilities/ingress.py`). No layer boundaries crossed; no GraphQL or repository changes. |
| IV. Type Safety and Typed Errors | PASS | New conditional branches preserve type hints. No new error classes needed (invalid `ip_whitelist` values fail at apply time via Traefik's existing CRD validation; no new `ServiceError` introduced). |
| V. Test-First Development | PASS | Spec FR-006 mandates unit + e2e. Plan adds a unit test for `build_app_post_rendering_patches` and extends `test_ingress_controller.py` with allow/deny scenarios. The e2e MUST run to a pass before completion. |
| VI. Format and Lint Before Commit | PASS | Standard `uv run invoke format lint` run, no exemptions. |

**Governance Gates** check:

- DB schema / migrations: not touched.
- GraphQL schema: not touched.
- New dependencies: none.
- CI/CD workflows: not touched.
- Authentication/authorization: this change activates an existing IP-filtering control; it does not modify the authn/authz model. Treated as a security-correctness fix, scope already pre-approved via the originating issue.

No violations to justify in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-ip-allowlist/
├── plan.md                  # This file
├── spec.md                  # Feature specification
├── research.md              # Phase 0 — design decisions
├── data-model.md            # Phase 1 — Kubernetes resource shape
├── quickstart.md            # Phase 1 — local verification recipe
├── contracts/
│   └── k8s-ingress-acl.md   # Phase 1 — Ingress↔Middleware wiring contract
└── checklists/
    └── requirements.md      # Spec quality checklist (already created)
```

`tasks.md` is produced later by `/speckit.tasks`.

### Source Code (repository root)

The change touches three categories of files. The full inventory:

```text
backend/styrmin_backend/agent/service/kubernetes/
├── utils.py                                               # existing helper get_kubernetes_reference() — used unchanged
└── resources/
    └── utilities/
        ├── ingress.py                                     # MODIFY: add annotation + namespace derivation + ip_whitelist gating
        └── templates/
            └── ingress-controller-chart-values.j2.yaml    # MODIFY: gate the `acl` Middleware on ip_whitelist being non-empty

backend/tests/
├── unit/                                                  # ADD: unit test for build_app_post_rendering_patches
│   └── (location TBD by /speckit.tasks — co-located with existing IngressUtility tests if they exist, otherwise a new file)
└── e2e/
    ├── conftest.py                                        # MODIFY: fixtures at lines ~685 and ~1062 (ip_whitelist 127.0.0.1 → 0.0.0.0/0)
    ├── test_ingress_controller.py                         # MODIFY: fixtures at lines ~118 and ~343; ADD: allow/deny scenario
    └── test_pod_scheduling.py                             # MODIFY: fixture at line ~166

tasks/
└── dev.py                                                 # MODIFY: line ~85 (ip_whitelist 127.0.0.1 → 0.0.0.0/0)
```

**Structure Decision**: web-service single-project layout. No new directories or modules introduced; the fix is local to the existing `IngressUtility` class and its Jinja template. Test additions fit the existing `backend/tests/{unit,e2e}/` structure.

## Phase 0: Outline & Research

The spec has no `[NEEDS CLARIFICATION]` markers (Q1 from `/speckit.clarify` resolved the only material ambiguity). Phase 0 captures the design decisions that pin the implementation: (a) where to derive the namespace, (b) how to gate the Middleware and annotation in lockstep, (c) how the fixture migration interacts with the new gating semantics, and (d) the e2e source-IP strategy. See [research.md](./research.md).

## Phase 1: Design & Contracts

**Prerequisites:** `research.md` complete (Phase 0 above).

1. **Data model**: no persistent entities. The "data model" for this change is the shape of Kubernetes resources rendered per deployment. Captured in [data-model.md](./data-model.md).
2. **Contracts**: no GraphQL or REST API surface changes. The relevant contract is the Ingress↔Middleware wiring contract (annotation key, value format, presence rules). Captured in [contracts/k8s-ingress-acl.md](./contracts/k8s-ingress-acl.md).
3. **Quickstart**: a developer-facing recipe to verify the fix locally (vcluster + a deployment with a narrow `ip_whitelist`, hitting from inside vs outside). See [quickstart.md](./quickstart.md).
4. **Agent context update**: skipped. The Styrmin Constitution (Boundaries → Never) explicitly forbids executing `update-agent-context.sh`; agent context files are maintained out-of-band.

### Post-design Constitution re-check

All gates re-evaluated after Phase 1: still PASS. The design adds no new classes, dependencies, or persistent state, and the gating logic remains within `IngressUtility`. Type hints, layering, and test-first all hold. No Complexity Tracking entries needed.

## Complexity Tracking

> No Constitution violations. Section intentionally empty.
