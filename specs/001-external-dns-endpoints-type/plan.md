# Implementation Plan: external-dns endpoints-type opt-in for application Ingress

**Branch**: `001-external-dns-endpoints-type` | **Date**: 2026-04-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-external-dns-endpoints-type/spec.md`

## Summary

Add an optional `external_dns_endpoints_type` field (`Literal["NodeExternalIP", "ClusterIP"] | None`) to `BaseConfigSection` so Cluster, Environment, and Deployment configs can opt into emitting `external-dns.alpha.kubernetes.io/endpoints-type: <value>` on the Ingress object rendered by `IngressUtility.build_app_post_rendering_patches`. Default behaviour (field unset) renders an annotation set byte-identical to today. Coverage: three new unit tests against the existing post-rendering-patch test class, plus one assertion bolted onto the existing dedicated-Traefik E2E scenario (`test_deploy_with_dedicated_ingress`) — no new E2E scenario, no new fixture.

## Technical Context

**Language/Version**: Python 3.12+ (uv-managed; ruff + ty enforce style/types)
**Primary Dependencies**: Pydantic v2 (`Literal`, `BaseModel`, `ConfigDict(extra="forbid")`), Strawberry GraphQL (untouched — `config` already flows through as `JSON | None`), kr8s (E2E only, for asserting the rendered Ingress)
**Storage**: Existing `JSON` columns on `Cluster`, `Environment`, `Deployment` rows store the config blob; **no migration required** — the new optional field round-trips through the existing JSON column unchanged.
**Testing**: `uv run invoke test` (unit + integration); `uv run pytest backend/tests/e2e/test_ingress_controller.py::test_deploy_with_dedicated_ingress -v -s --pdb` for the E2E extension (per AGENTS.md `--pdb` rule).
**Target Platform**: Linux server (Styrmin agent rendering Kubernetes manifests for downstream cluster apply).
**Project Type**: Web service — monorepo with `backend/` and `frontend/`. **Only `backend/` is touched** (config models, ingress utility, unit + E2E tests).
**Performance Goals**: Sub-microsecond impact on rendering — one extra dict-key read per Ingress render; no new I/O.
**Constraints**: Zero behaviour change when the field is unset (FR-004 / SC-002); zero DB schema or GraphQL schema change; existing snapshot-style annotation tests must pass without modification.
**Scale/Scope**: Single field on a shared base model; one conditional annotation emission. ~6 LOC of production code, ~30 LOC of test code.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Compliance | Evidence |
|-----------|-----------|----------|
| I. Declarative State Reconciliation | ✓ | Field is read at render time within the existing reconcile loop. Adding the annotation is idempotent: a second reconcile on a converged Ingress produces no diff. Unset state is byte-identical to pre-feature behaviour, so rerunning on existing deployments is a no-op (FR-004). |
| II. Driver-Based Deployment | ✓ | Change lives in the *utility* layer (`IngressUtility`), not in driver specifications. No driver schema or driver-side logic changes. |
| III. Layered Architecture | ✓ | Domain model change in `context/models/config.py`; rendering change in `agent/service/kubernetes/resources/utilities/ingress.py`. No cross-layer leakage. No new GraphQL fields, no new repository methods, no new service-layer functions. |
| IV. Type Safety and Typed Errors | ✓ | Field typed `Literal["NodeExternalIP", "ClusterIP"] \| None`. Validation errors flow through Pydantic's existing ValidationError path, raised at config-load time before any service-layer call (FR-005). No new exception class needed; no Union-for-errors. |
| V. Test-First Development | ✓ | Unit tests in `TestIngressUtilityPostRenderingPatches` cover the three-state render matrix (FR-001, FR-003, FR-004) plus a fourth merge-precedence test that builds layered configs, calls `_resolve_instance_config`, and asserts the rendered annotation reflects the deployment-level override (FR-002, US1 acceptance scenario 3). A new focused file `backend/tests/unit/context/test_base_config_section.py` covers Pydantic validation (FR-005, US2). E2E coverage achieved by extending `test_deploy_with_dedicated_ingress` per the spec's clarification (FR-008, SC-005) — explicit confirmation already recorded in `## Clarifications`, satisfying the constitution's "ask before skipping new E2E" rule for the no-new-scenario decision. |
| VI. Format and Lint Before Commit | ✓ | Standard `uv run invoke format lint` will run before commit. Line-length 120 honoured in all touched files. |

**Governance Gates** — none triggered:

- DB schema/migration: **not touched** (config is stored as a `JSON` column blob; new optional key round-trips unchanged).
- GraphQL schema: **not touched** (the `create_cluster` / `create_environment` / `create_deployment` mutations all accept `config: JSON | None`; the new field is validated server-side by Pydantic).
- New dependencies: **none**.
- CI/CD: **not touched**.
- AuthN/Z: **not touched**.

**Initial gate verdict**: PASS. No violations to track in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-external-dns-endpoints-type/
├── plan.md              # This file
├── spec.md              # Feature spec (already written)
├── research.md          # Phase 0 output (this command)
├── data-model.md        # Phase 1 output (this command)
├── quickstart.md        # Phase 1 output (this command)
├── contracts/           # Phase 1 output (this command) — config-shape contract only; no new GraphQL ops
├── checklists/
│   └── requirements.md  # Spec quality checklist (already written)
└── tasks.md             # /speckit.tasks output (NOT created here)
```

### Source Code (repository root)

The feature is backend-only and changes a tightly scoped slice of existing files. Nothing new is created in production code; one new file is added under `tests/unit` only if test organisation calls for it (the existing `test_utility_resources.py` already houses the relevant test class — preferred).

```text
backend/
├── styrmin_backend/
│   ├── context/
│   │   └── models/
│   │       └── config.py                                 # MODIFIED: add `external_dns_endpoints_type` to BaseConfigSection
│   └── agent/
│       └── service/
│           └── kubernetes/
│               └── resources/
│                   └── utilities/
│                       └── ingress.py                    # MODIFIED: conditionally append the new annotation
└── tests/
    ├── unit/
    │   ├── agent/
    │   │   └── test_utility_resources.py                 # MODIFIED: add 4 tests to TestIngressUtilityPostRenderingPatches (3 render-state tests + 1 deployment-overrides-cluster merge test)
    │   └── context/
    │       └── test_base_config_section.py               # CREATED: Pydantic validation tests for external_dns_endpoints_type (US2)
    └── e2e/
        ├── conftest.py                                   # MODIFIED: session cluster fixture sets external_dns_endpoints_type
        └── test_ingress_controller.py                    # MODIFIED: extend test_deploy_with_dedicated_ingress with annotation assertion
```

**Structure Decision**: Backend-only changes: two production files and three test files modified, plus one new test file (`backend/tests/unit/context/test_base_config_section.py`) for the US2 Pydantic-validation contract. No new modules, no frontend changes. The session-scoped cluster fixture in `backend/tests/e2e/conftest.py` is the single E2E injection point — setting the field at the cluster layer exercises the same Cluster → Environment → Deployment merge that already governs `fqdn_suffix` and `ingress_class` (mirroring the production opt-in path).

## Complexity Tracking

> **No constitution violations require justification.**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)*  | —          | —                                   |

## Phase Outputs

- **Phase 0 — Research**: [research.md](./research.md) — confirms zero unresolved unknowns; documents the inheritance-via-`BaseConfigSection` decision and the no-new-E2E decision.
- **Phase 1 — Data Model**: [data-model.md](./data-model.md) — documents the new field, its validation rule, its inheritance behaviour, and the "no DB / no GraphQL schema change" boundary.
- **Phase 1 — Contracts**: [contracts/config-shape.md](./contracts/config-shape.md) — operator-facing JSON shape for the cluster/environment/deployment config payload; the produced annotation key/values; the rejected-input contract.
- **Phase 1 — Quickstart**: [quickstart.md](./quickstart.md) — minimal operator walkthrough: set field, reconcile, observe annotation; plus the E2E extension recipe.
- **Phase 1 — Agent context**: SKIPPED. The Styrmin constitution (`Boundaries → Never`) explicitly forbids running `update-agent-context.sh`. Agent context files are maintained manually or through other workflows.

## Re-evaluation After Phase 1 Design

All design artefacts confirm the initial gate verdict:

- No new entities → no Domain → DB → repository plumbing.
- No new GraphQL operations → no schema regeneration, no SDK type regeneration.
- No new dependencies.
- Test plan (3 unit tests + 1 E2E assertion bolt-on) sits inside existing test classes/scenarios.

**Final gate verdict**: PASS. Ready for `/speckit.tasks`.
