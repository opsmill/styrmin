# Implementation Plan: Ingress Class Set Only After the Chart Renders

**Branch**: `fac/ingress-class-post-render-tb7qv` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/023-ingress-class-post-render/spec.md` (PRD: [#471 comment](https://github.com/opsmill/styrmin/issues/471#issuecomment-6187650614))

## Summary

Driver templates set the Ingress class that Styrmin already sets after the chart renders. In an environment with a dedicated ingress controller, Styrmin hides `ingress_class` from the template data, which does not protect a chart that sets its own class: Kubernetes rejects the Ingress, or the dedicated ingress controller ignores it.

Technical approach (details in [research.md](research.md)):

- In dedicated mode, the ingress utility adds a strategic merge patch that sets `spec.ingressClassName` to `null` on every Ingress (new block `IngressClassNameRemovalPatch`). Kustomize deletes the field when it is present and does nothing when it is absent; a JSON6902 `remove` fails on an absent field (D-001).
- In shared mode, the existing `add` patches for `spec.ingressClassName` and the annotation stay as they are, so the rendered HelmRelease does not change (D-002). With no class resolved, no class patch is emitted, as today (D-003).
- The values template renderer stops removing `ingress_class` from the template data (D-004).
- The three example drivers drop the class line and keep their `spec.version` (D-005).
- Unit tests, one new integration test on real `helm template` and `kubectl kustomize`, and local runs of two existing E2E tests (D-006).
- Documentation, `CONTEXT.md`, ADR-070 and a changelog fragment in the same change (D-007). The fragment tells driver authors they can drop the class line, that a chart's own class is removed with a dedicated ingress controller, and that templates now read `ingress_class` in that mode too.

## Technical Context

**Language/Version**: Python 3.14+ (agent and backend)

**Primary Dependencies**: Pydantic v2, Jinja2, PyYAML; Flux helm-controller `v1.6.5` post-renderers (Kustomize). No new dependency.

**Storage**: None. No database or Alembic change.

**Testing**: pytest unit tests; a pytest integration test that calls `helm template` and `kubectl kustomize` (skipped when either is missing, like [`test_container_override_migration_parity.py`](../../backend/tests/integration/test_container_override_migration_parity.py)); two existing E2E tests on vCluster (`shard_compute`) run locally with evidence.

**Target Platform**: The Styrmin agent, which writes HelmReleases that Flux helm-controller reconciles on Kubernetes.

**Project Type**: Web service (backend, agent, frontend) with example drivers. Only the agent, the example drivers and the documentation change.

**Performance Goals**: No new goal. One extra patch per application HelmRelease in dedicated mode.

**Constraints**:

- The shared-mode HelmRelease must stay byte-identical, so existing deployments in that mode see no Flux upgrade from this change (D-002).
- A dedicated-mode render must not fail when an Ingress has no `spec.ingressClassName` (spec edge case, D-001).
- The patch output stays a function of the stored config only (Constitution §I).
- No change to the GraphQL schema, the SDK, `styrminctl`, the frontend, the driver format or the error codes (FR-009).

**Scale/Scope**: 2 agent source files, 3 example driver templates, 2 unit test files (one new), 1 new integration test, 4 documentation pages, `CONTEXT.md`, 1 new ADR, 1 changelog fragment.

All items are resolved; [research.md](research.md) has no open "NEEDS CLARIFICATION".

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How the design meets it |
|-----------|--------|-------------------------|
| I. Declarative state reconciliation | Pass | The patches are rebuilt from the resolved config on every render; the strategic merge patch is idempotent (removing an absent field is a no-op). |
| II. Driver-based deployment | Pass | Drivers keep less chart-specific template code, as with env vars (ADR-057) and container `command` and `args` (ADR-069). The driver format does not change. |
| III. Layered architecture | Pass | The change stays in the agent's resource builders and utilities, which read the context only. No service, repository or API change. |
| IV. Type safety and typed errors | Pass | The new patch block is a typed dataclass like the other blocks. No new error type; no union-based error handling. |
| V. Test-first development | Pass, with an approved E2E skip | No new E2E test: approved in the idea review of #471 and recorded in the PRD's governance gates, because two existing CI tests in `shard_compute` cover the changed path once `simple-app` drops its class line. Both are run locally with evidence. The integration test covers the case that no E2E test deploys (a chart that sets its own class). |
| VI. Format and lint | Pass | `uv run invoke format lint` is a task before each commit. |
| VII. Documentation accuracy | Pass | `creating-a-driver.md`, `context.md`, `ingress-and-networking.md`, `data-models.md`, `CONTEXT.md`, the renderer docstring, ADR-070 and the changelog fragment are tasks in the same change. |

**Governance gates** (AGENTS.md "Ask First"): no database or migration change, no GraphQL change, no new dependency, no CI/CD change, no authentication change. Skipping new E2E coverage is approved (PRD, "Governance gates"). Documentation ships in the same change.

**Post-design re-check**: Pass. The design adds one patch block and deletes one code block; it adds no service, no API surface and no state.

## Project Structure

### Documentation (this feature)

```text
specs/023-ingress-class-post-render/
├── plan.md              # This file
├── research.md          # Phase 0 output: D-001 to D-007
├── data-model.md        # Phase 1 output: the class rule and the patch blocks per mode
├── quickstart.md        # Phase 1 output: validation commands
├── contracts/
│   ├── post-render-patch.md   # Patches the ingress utility emits per mode
│   └── template-data.md       # ingress_class in the values template data
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/styrmin_backend/agent/service/kubernetes/resources/
├── blocks/patches.py                  # + IngressClassNameRemovalPatch (strategic merge, spec.ingressClassName: null)
├── utilities/ingress.py               # dedicated mode: emit the removal patch
└── builders/application.py            # render_value_template: drop the ingress_class removal, update docstring

backend/tests/
├── unit/agent/test_utility_resources.py                     # update TestDedicatedIngressPatching; patch render test
├── unit/agent/test_render_value_template_ingress_class.py   # new: template reads ingress_class in dedicated mode
└── integration/test_ingress_class_post_render.py            # new: helm template + kubectl kustomize, both modes

driver/examples/
├── simple-app/values.j2.yml           # drop className line
├── semaphore/values.j2.yml            # drop className line
└── slurpit/values.j2.yml              # drop className line

docs/docs/
├── drivers/creating-a-driver.md       # drop className line; "No Ingress class" bullet
├── drivers/context.md                 # drop className line; "No Ingress class" bullet
└── concepts-and-architecture/ingress-and-networking.md   # class per mode

dev/
├── adr/0070-ingress-class-set-by-post-render.md   # new
└── knowledge/backend/data-models.md               # DedicatedIngressConfig section

backend/tests/e2e/fixtures/drivers/{late-container,failing-actions}/values.j2.yml
                                       # unchanged on purpose: still set the class (FR-005 in CI)

CONTEXT.md                             # "Dedicated ingress controller" entry
changelog/471.changed.md               # new towncrier fragment
```

**Structure Decision**: Existing web-service layout. All code changes are in the agent's Kubernetes resource builders under `backend/styrmin_backend/agent/service/kubernetes/resources/`, next to the env var and container override patches that ADR-057 and ADR-069 added.

## Implementation Order

1. Add `IngressClassNameRemovalPatch` and its unit test (D-001).
2. Emit it from the ingress utility in dedicated mode; update `TestDedicatedIngressPatching` (D-001 to D-003).
3. Remove the `ingress_class` removal from `render_value_template`, update its docstring, add the template-data unit test (D-004).
4. Add the integration test; it must pass before the example drivers change, because it renders the chart with the class set (FR-005) and with it empty (FR-004).
5. Drop the class line from the three example drivers (D-005).
6. Documentation, `CONTEXT.md`, ADR-070, changelog fragment (D-007).
7. `uv run invoke format lint`, `uv run invoke test`, then the two E2E tests locally with evidence in `e2e-evidence.md` (D-006).

## Risks

- **A driver outside this repository reads `ingress_class` for something other than the Ingress class** (spec A-001): in dedicated mode its template now gets the resolved value instead of an empty value. Not known; accepted by the PRD.
- **Flux applies the strategic merge patch differently from `kubectl kustomize`**: low. Both use the Kustomize API, strategic merge patches with a target are already in production (`TemplateAnnotationPatch`, `RuntimeClassPatch`), and `test_traffic_routes_through_dedicated_ingress` runs the dedicated-mode path on a real cluster.
- **Rollback**: safe. On the previous Styrmin version, the example drivers without the class line get the same Ingress: the old code sets the class in shared mode and wants no class in dedicated mode.
- **Default IngressClass on clusters that define one**: the `DefaultIngressClass` admission plugin skips an Ingress with the `kubernetes.io/ingress.class` annotation, which Styrmin always sets in dedicated mode, so the removed class is not replaced by the cluster default (research D-001).
- **Dedicated-mode HelmReleases change**: every application in dedicated mode gets one more patch, so Flux upgrades each release on its next render. The resulting Ingress is the same unless the chart sets its own class, which is the case this change fixes.

## Complexity Tracking

No Constitution violation to justify.
