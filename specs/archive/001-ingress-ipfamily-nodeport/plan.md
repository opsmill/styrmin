# Implementation Plan: IP Family & Fixed NodePort Knobs for Dedicated Ingress Service

**Branch**: `001-ingress-ipfamily-nodeport` | **Date**: 2026-04-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-ingress-ipfamily-nodeport/spec.md`

## Summary

Extend the existing `IngressServiceConfig` Pydantic model (in `backend/styrmin_backend/context/models/config.py`) with three optional fields — `ip_families`, `ip_family_policy`, `node_port` — and render each conditionally in the dedicated Traefik chart-values Jinja template. Validate field shapes and the `node_port`-vs-`type` interaction at config load. Default behavior MUST remain byte-identical when no new fields are set. Test coverage: unit/snapshot for every validator and rendering branch, plus an E2E scenario for the fixed-NodePort flow added by **extending** `backend/tests/e2e/test_ingress_controller.py` (no new E2E module). The IPv6/dual-stack flow is covered by unit/snapshot tests plus a manual-validation runbook published in `dev/guides/`; automated dual-stack E2E is tracked as a follow-up.

## Technical Context

**Language/Version**: Python 3.13 (project standard)
**Primary Dependencies**: Pydantic v2 (already used by `IngressServiceConfig`), Jinja2 (chart values template), pytest (unit + e2e)
**Storage**: N/A — `IngressServiceConfig` is part of the cluster/environment `config` JSON blob; no new columns or migrations
**Testing**: pytest unit + snapshot tests in `backend/tests/unit/services/test_ingress_controller.py`; pytest e2e in `backend/tests/e2e/test_ingress_controller.py` against the existing single-family vcluster fixture (`vcluster` / `styrmin_resources`)
**Target Platform**: Linux server (control plane)
**Project Type**: Web application (backend Python + frontend React); this feature is **backend-only** — no GraphQL schema, SDK, or frontend changes (verified: existing `IngressServiceConfig` fields like `load_balancer_ip` and `external_traffic_policy` appear only in the Pydantic model, the chart template, and the unit tests — there is no per-field GraphQL exposure)
**Performance Goals**: N/A — config-load + template-render are not hot paths
**Constraints**: byte-identical chart-values output when no new fields are set (FR-011); validation failures MUST surface at config load before any cluster API call (FR-004 / FR-005 / FR-006)
**Scale/Scope**: 2 production source files modified (`config.py`, `chart_values.j2.yaml`), 1 unit test file extended, 1 E2E test file extended, 1 new manual-validation guide in `dev/guides/`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | ✅ Pass | New fields flow through the existing desired-state pipeline; chart re-render is idempotent. |
| II. Driver-Based Deployment | ✅ Pass | Modifies the dedicated-ingress internal driver's chart-values template; no deployment logic added outside the driver. |
| III. Layered Architecture | ✅ Pass | Change is confined to the config-model layer (`context.models.config`) and the template-rendering layer (`services.ingress_controller.templates`). No cross-layer shortcuts. |
| IV. Type Safety and Typed Errors | ✅ Pass | Field types use `Literal` for IP families and policy, `int | None` with `Field(ge=1, le=65535)` for `node_port`. Validation surfaces as Pydantic `ValidationError` at config load — the standard pattern at this boundary. No new `ServiceError` subclass needed because the failure is pre-service. |
| V. Test-First Development | ✅ Pass (narrowed §V deviation) | Automated E2E ships for **both** the NodePort flow AND the IP family rendering pass-through — T012/T016 deploys with `node_port`, `ip_families`, and `ip_family_policy` all set on the existing single-family vcluster and asserts each on the resulting Service object. The remaining §V gap is narrow: cluster-side IPv6 *traffic* validation (AAAA publication, v6 routing) requires dual-stack infrastructure not present in CI, so it stays in a manual runbook with an automated follow-up tracked by T023. The narrowed deviation was raised in `/speckit.analyze`, refines the original `/speckit.clarify` Option D disposition, and is recorded in `spec.md` § Clarifications. |
| VI. Format and Lint Before Commit | ✅ Pass | Standard `uv run invoke format lint` gate applies; no special handling. |

**Governance Gates**: None triggered.

- DB schema / migrations — N/A (config-blob field, no DB shape change).
- GraphQL schema — N/A (no per-field GraphQL exposure for `IngressServiceConfig`).
- New dependencies — N/A.
- CI/CD workflow — N/A.
- AuthN/Z — N/A.

## Project Structure

### Documentation (this feature)

```text
specs/001-ingress-ipfamily-nodeport/
├── plan.md                                        # This file
├── spec.md                                        # /speckit.specify output (with /speckit.clarify additions)
├── research.md                                    # Phase 0 — Traefik chart key shapes, Pydantic validator patterns
├── data-model.md                                  # Phase 1 — extended IngressServiceConfig shape & validators
├── quickstart.md                                  # Phase 1 — operator how-to + IPv6 manual-validation runbook outline
├── contracts/
│   └── README.md                                  # Phase 1 — explicit "no API contract changes" note
└── checklists/
    └── requirements.md                            # /speckit.specify quality checklist (already created)
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── context/models/config.py                          # MODIFIED: 3 new fields + 2 validators on IngressServiceConfig
│   └── services/ingress_controller/
│       └── templates/chart_values.j2.yaml                # MODIFIED: render 3 new keys conditionally; remove commented-out ports: scaffold
└── tests/
    ├── unit/services/test_ingress_controller.py         # EXTENDED: validator unit tests + snapshot tests for each rendering branch
    └── e2e/test_ingress_controller.py                    # EXTENDED: NodePort scenario (no new module)

dev/guides/
└── ingress-ipv6-dual-stack-validation.md                 # NEW: manual-validation runbook for IPv6/dual-stack pinning
```

**Structure Decision**: Web-application layout. The change is backend-only and lives entirely under `backend/` plus one new doc under `dev/guides/`. No frontend, SDK, or GraphQL files are touched.

## Phase 0 Output

[research.md](./research.md) — Traefik chart 28.2.0 key shapes for `service.ipFamilies` / `service.ipFamilyPolicy` / `ports.{web,websecure}.nodePort`, Jinja conditional pattern matching the existing `load_balancer_ip` / `external_traffic_policy` rendering, Pydantic v2 validator patterns for the two cross-field constraints, and a confirmation that no GraphQL/SDK regen is required.

## Phase 1 Output

- [data-model.md](./data-model.md) — extended `IngressServiceConfig` shape with the three new fields, validator semantics, and merge-precedence behavior inherited from the existing pattern.
- [contracts/README.md](./contracts/) — explicit "no API contract changes" note (the feature is internal to the Pydantic config model and the Helm-values template).
- [quickstart.md](./quickstart.md) — operator how-to for the two canonical scenarios, plus the outline of the IPv6/dual-stack manual-validation runbook that lands in `dev/guides/`.
- Agent context update — **skipped** per Constitution §"Never": `update-agent-context.sh` MUST NOT be executed.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| §V narrowed deviation: cluster-side IPv6 *traffic* validation (AAAA publication, v6 routing) deferred to a follow-up; the rendering layer IS automated end-to-end this iteration | The existing single-family vcluster cannot route IPv6 traffic, so any test asserting "v6 traffic actually flows" needs dual-stack infrastructure not present in CI. However, the rendering layer (Styrmin → Helm → Service object) CAN be tested end-to-end on existing infra by deploying with `ip_families: ["IPv4"]` (cluster default but explicit) and asserting the resulting `spec.ipFamilies` / `spec.ipFamilyPolicy` reflect the requested values — the path T012/T016 take. | Option C (full automated dual-stack *traffic* E2E in this iteration) was rejected because it couples a config-surface change to new test-cluster infrastructure. Option A (unit-only, waive all E2E) was rejected because it leaves both P1 flows without end-to-end verification. The original Option D (NodePort E2E + manual IPv6 runbook only) was tightened post-`/speckit.analyze` to also include the IP family rendering pass-through E2E — closing the §V "net-new functionality must ship with E2E" gate for the rendering layer. Only the cluster-side IPv6 *traffic* behavior remains in the manual runbook; automated coverage of that is tracked by T023. |
