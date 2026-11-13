# Implementation Plan: Service ingress override

**Branch**: `sas-598-service-ingress-spec` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/033-service-ingress-override/spec.md` (issue [#598](https://github.com/opsmill/styrmin/issues/598))

## Summary

Styrmin builds one Ingress for every service that its driver declares `scope: external`, in the existing `ingress` utility, instead of patching the Ingress that a chart renders. An operator can override the ingress class and the FQDN suffix of one such service in the deployment's config (a new `services` block next to `components`), in a manifest, through GraphQL and in the UI. A change to the driver version that would drop an override is refused before any pod changes. The `infrahub` and `infrahub-enterprise` drivers move the task manager to this model, and `generic-app` stops rendering its own Ingress.

The research found one conflict in the PRD (D-003: the application address would be claimed twice in the `infrahub` driver) and one open risk (R-1 in D-012: existing external-declaring deployments get two Ingresses on the next reconcile). The critique ([critique-20261110-1000.md](critiques/critique-20261110-1000.md)) confirmed the first (finding E1), and the spec now carries the changed FR-002. The second (finding P1) is accepted without a guard, by decision of Simon AURA--SCUSSEL on 2026-11-10, and the spec states it as an edge case.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3, React 19, Node 22 (frontend)

**Primary Dependencies**: Strawberry GraphQL, SQLModel/SQLAlchemy (async), Pydantic v2, Prefect, kopf, kubernetes-asyncio, Jinja2; TanStack Query v5, TanStack Form, Zod, Radix UI, Tailwind (frontend). No new dependency.

**Storage**: PostgreSQL through SQLModel. No schema change and no Alembic revision: the override lives in the deployment's existing JSON config (ADR-029; research D-004). To be re-confirmed by the first task, which checks that `db/models.py` is untouched.

**Testing**: pytest (unit, integration, GraphQL propagation), pytest end-to-end on a disposable vCluster (`backend/tests/e2e/`), Vitest and React Testing Library (frontend)

**Target Platform**: Kubernetes clusters managed by Styrmin; web UI

**Project Type**: Web application (backend, agent, operator, frontend, SDK, CLI, drivers, docs)

**Performance Goals**: None specific. FQDN and Ingress computation is string work (ADR-022).

**Constraints**: ADR-071 (class set by post-render for chart Ingresses stays), ADR-073 (name objects after record ids), ADR-022 (one FQDN function for template data and GraphQL), no resource limits in the Helm charts, towncrier fragment for the user-visible change.

**Scale/Scope**: Services per deployment: a handful. Three drivers change (`infrahub`, `infrahub-enterprise`, `generic-app`).

## Constitution Check

*GATE: must pass before research. Re-checked after design.*

| Principle | Status | Note |
|---|---|---|
| I. Declarative reconciliation | Pass | The Ingress is part of the desired utility resources. The operator restores and deletes it (D-002). No change is applied outside reconciliation. |
| II. Driver-based deployment | Pass with a breaking change | `scope: external` gets the meaning the docs already claim. No new driver key. FR-014 needs a migration guide. |
| III. Layered architecture | Pass | Validation in the service layer, resolver reads through it, no cross-layer call. |
| IV. Typed errors | Pass | Three `ServiceError` subclasses with codes (contracts). No union types. |
| V. Test-first | Pass, to do | End-to-end tests for each story, GraphQL propagation test for the new input and output fields, written before the implementation. API and UI variants. |
| VI. Format and lint | Pass, to do | `uv run invoke format lint` before each commit. |
| VII. Documentation accuracy | Pass, to do | Corrections to `scope` statements, the override page, the migration guide, an ADR, `CONTEXT.md`, the driver reference (D-014). |

Governance gates: GraphQL schema change (crossed, discussed in the PRD); database schema (not crossed); new dependency, CI/CD, authentication (not crossed).

**Re-check after design**: no new violation. No entry in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/033-service-ingress-override/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── graphql-and-manifest.md
├── checklists/requirements.md
└── tasks.md              # created by /speckit-tasks
```

### Source code (files to change or add)

```text
backend/styrmin_backend/
├── context/
│   ├── fqdn.py                                  # one function: effective address of a service (D-007)
│   └── models/
│       ├── config.py                            # ServiceConfigBlock, DeploymentConfig.services (D-004)
│       └── services.py                          # ServiceReference: ingress_class, overridden
├── services/
│   ├── context.py                               # services dict and deployed_services use the new function; add scope
│   ├── deployment.py                            # call the new validator beside the replica validator (D-008)
│   └── service_ingress/                         # new: validator.py, exceptions.py (D-008)
├── agent/service/kubernetes/resources/utilities/
│   └── ingress.py                               # build_resources returns Ingress objects; shared annotation helper (D-001, D-006)
├── operator/
│   ├── reconciler.py                            # list, delete Ingress (D-002)
│   └── handlers/                                # helmrelease.py, styrmin_deployment.py loops; utility_resources.py drift handlers
└── api/
    ├── definitions/deployment/inputs.py         # ServiceConfigInput, DeploymentConfigInput.services
    ├── definitions/deployment/model.py          # config output type
    ├── definitions/service/model.py             # DeployedService fields
    └── schema/                                  # resolver wiring

frontend/src/components/deployment/configuration/
├── ConfigEditDrawer.tsx                         # pass services with scope to the section
└── sections/
    ├── edit/ServiceOverridesSection.tsx         # ingress class and suffix fields, external services only
    └── read/NetworkingSummary.tsx               # per-service class and host, overridden or inherited
# plus the deploy form (location to find in the first frontend task)

driver/examples/
├── infrahub/ and infrahub-enterprise/           # task-manager external, prefect-server ingress not enabled (FR-013)
└── generic-app/                                 # remove the chart Ingress (FR-012)

python_sdk/ and cli/                             # regenerated types; manifest block (D-009)
schema.graphql                                   # regenerated
backend/tests/{unit,integration,e2e}/            # tests (below)
docs/docs/                                       # scope corrections, override page, migration guide (D-014)
dev/adr/                                         # one new ADR
dev/knowledge/, CONTEXT.md, changelog/           # updates and a towncrier fragment
```

**Structure decision**: the existing web-application layout. The Ingress builder extends the `ingress` utility, the validator mirrors `services/replicas/`, and the UI extends the existing Service overrides section. Nothing new at the top level.

## Design decisions (details in [research.md](research.md))

1. Build the Ingress in `IngressUtility.build_resources` (D-001); add `Ingress` to the operator's list, delete and reconcile loops (D-002).
2. The application address goes to the first declared service when it is external (D-003). This changes FR-002 of the PRD.
3. Store the override under `services.<driver service name>` with `ingress_class` and `fqdn_suffix` (D-004). No migration.
4. Name the Ingress after the driver service name, `styrmin-svc-<driver service name>` (D-005; the `DeployedService` id is not stable).
5. One shared helper for the annotations and class, used by the existing chart patch and the new Ingress (D-006).
6. One address function for template data and GraphQL (D-007).
7. Validation in `services/service_ingress/`, three typed errors, refuse rather than drop on a version change (D-008).
8. GraphQL input `services: [ServiceConfigInput!]`, output fields on `DeployedService` (D-009).
9. The UI takes services and scope from `deployedServices` (drawer) and from `ApplicationDriverVersion.services` (deploy form), with no new backend field (D-010).

## Test plan

Written before the implementation (Constitution V).

| Level | What | Covers |
|---|---|---|
| Unit | Ingress builder: no override, override, dedicated controller, no suffix, two external services, tcp service, first service internal | FR-001 to FR-004, FR-007, FR-008, D-003 |
| Unit | Address function and `ServiceReference` with and without an override, and for a service of another deployment | FR-006, D-007 |
| Unit | Validator: unknown service, internal service, version change that removes or internalizes a service, clearing a stale override | FR-009, FR-010 |
| Unit | `ServiceConfigBlock` and `DeploymentConfig.services` validation and serializer (a config without the block dumps as before) | D-004 |
| Unit | The chart patch is unchanged for chart Ingresses | ADR-071, SC-003 |
| Propagation | `ServiceConfigInput` on `deploy`, `updateDeployment`, `updateDeploymentVersion`; the output fields on read | Constitution V |
| Operator unit | Ingress listed, restored after drift, deleted when no longer desired | D-002 |
| Frontend unit | Service overrides section (external services only, set, clear, errors), Networking summary (overridden, inherited), deploy form | FR-015, FR-016 |
| End to end (API and UI variants) | User story 1 on `infrahub`: only `task-manager` changes, `infrahub` Ingress identical, clear restores | FR-004, FR-013, SC-002 |
| End to end | `generic-app`: exactly one Ingress, removed with the deployment | FR-001, FR-012, SC-006 |
| End to end | Environment with a dedicated ingress controller and one overridden service | FR-008 |
| End to end (`api_only`) | Override on an internal service, and a refused version change that leaves pods untouched | FR-009, FR-010, SC-004 |
| Manual, recorded | Real Tailscale operator; upgrade of a running `infrahub` deployment (interruption) | SC-005, D-011, D-013 |

Reuse before booting: extend `test_infrahub_services.py`, `test_deploy_generic_app.py` and `test_ingress_controller.py` where the new check is a read of a stack they already deploy (AGENTS.md); add a new node only for the override flow, which changes configuration. Each new end-to-end test carries one shard marker.

## Risks and open items

- **D-003 (PRD conflict)**: the application address rule differs from the PRD wording. Confirmed by Simon AURA--SCUSSEL on 2026-11-10.
- **R-1 (D-012)**: a Styrmin release makes existing external-declaring deployments render two Ingresses on one host on the next reconcile, before any driver upgrade. Accepted without a guard (decision of Simon AURA--SCUSSEL, 2026-11-10); the migration guide and the changelog state it.
- **D-005**: the `DeployedService` id is not stable across version changes (verified in T001), so the Ingress is named after the driver service name.
- **D-002**: operator RBAC for `ingresses`, and deletion with the namespace, are not verified.
- **D-009**: whether the manifest model needs a hand-written change is not verified.
- **Not known** (from the PRD): the Tailscale `tls` question, the number of external drivers outside this repository, the interruption during the Infrahub move, backup and restore of an environment with Styrmin-built Ingresses.

## Complexity Tracking

No constitution violation to justify.
