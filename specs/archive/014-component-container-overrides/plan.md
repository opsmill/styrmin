# Implementation Plan: Component-Scope `command` / `args` Overrides

**Branch**: `014-component-container-overrides` | **Date**: 2026-05-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/014-component-container-overrides/spec.md`

## Summary

Let a deployment operator set a container's `command` and/or `args` on a single **component** of one deployment — scoped to that deployment, with **zero driver-source changes** — instead of forking the application driver. The two fields are independent, optional, and nullable; absence falls through to the chart default.

The feature is a direct port of the deployment **env-vars** precedent (008 / 010, ADR-013). It reuses every layer the env-vars work established: per-component config lives on the existing `DeploymentConfig.components[<name>]` block (`ComponentConfigBlock`, no DB migration per [ADR-029](../../dev/adr/adr-029-config-additions-via-baseconfigsection-no-migration.md)); the typed `UpdateDeploymentInput.components: [ComponentConfigInput!]` list-of-`{name, …}` shape carries the new fields ([ADR-018](../../dev/adr/adr-018-typed-update-deployment-input.md)); write-side validation rejects unknown components and malformed lists at the mutation boundary; the render boundary tolerates orphaned blocks after a driver upgrade and surfaces them on read; drivers consume the resolved values through Jinja template filters ([ADR-013](../../dev/adr/adr-013-driver-env-var-consumption.md)).

**Two deliberate divergences from env-vars**, both flowing from FR-003 (component-scope only) and FR-009:

1. **No layering.** Env-vars merge `environment → deployment → component` per-key (deepest-wins). `command`/`args` have **no** environment- or deployment-wide scope — the resolved value is simply the component block's value or "unset". Resolution is a direct lookup, not a merge.
2. **Omit-marker filter, not empty-list.** The env-vars filter returns `[]` when absent (the chart appends). For `command`/`args`, `[]` is a *meaningful* Kubernetes value distinct from "unset", so the consuming filter returns the list **or `None`/omit**, and the driver template guards with a conditional so the chart default flows through when unset.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 / Node 22 (frontend)
**Primary Dependencies**: Strawberry GraphQL, SQLModel + SQLAlchemy (async, asyncpg), Pydantic v2, Jinja2 (chart value templates), Prefect (reconcile workflows); httpx + ariadne-codegen (SDK); Cyclopts (CLI); React 19, TanStack Query/Router, `@tanstack/react-form`, Zod, Radix/Base UI (frontend). No new dependencies.
**Storage**: PostgreSQL via SQLModel/SQLAlchemy. `command`/`args` ride the existing `Deployment.config` JSON column under `components[<name>]` (no migration — ADR-029). One new JSON column on `ApplicationDriverVersion` for the doc-only declaration, mirroring the existing `env_vars` column; created by `metadata.create_all()` (no Alembic — Styrmin is pre-production).
**Testing**: pytest (backend unit / functional-propagation / E2E on disposable vCluster); Vitest + React Testing Library (frontend); SDK + CLI pytest suites.
**Target Platform**: Linux server (Kubernetes deployment orchestration platform).
**Project Type**: Web (backend GraphQL API + React SPA frontend) + Python SDK + CLI + application drivers.
**Performance Goals**: No new hot path. Resolution is an O(components) dict lookup at render time; negligible vs. the existing reconcile cost.
**Constraints**: Override values are passed through verbatim (no templating/expansion — FR-014). Empty list rejected at write; empty-string elements accepted (FR-006). Clearing is null/omit, distinct from `[]` (FR-007). v1 targets exactly one resolved `command`/`args` per component; the driver chooses the container (no per-container targeting — Out of Scope).
**Scale/Scope**: Single-cluster platform (ADR-039). Touched layers: Pydantic config models, render resolver, Jinja filters, GraphQL input + output + driver-doc surface, SDK regen, CLI (doc only), frontend editor + transform, reference driver, docs, and tests (unit + propagation + E2E).

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.4.0.*

| Principle | Assessment |
|-----------|------------|
| **I. Declarative State Reconciliation** | ✅ Overrides are desired state on `Deployment.config`; reconcile diffs desired vs. current and redeploys. Re-running on a converged deployment is a no-op (FR-008 / US1 Scenario 3 — no spurious restart when the override is unchanged). |
| **II. Driver-Based Deployment** | ✅ The driver declares overridable components (doc-only) and **consumes** the resolved values through its `values.j2.yml` template filters. No ad-hoc deployment logic outside the driver; an unwired driver stores-but-never-applies (FR-009 / US6 silent no-op, identical to ADR-013). |
| **III. Layered Architecture** | ✅ GraphQL resolver → service layer (validation + resolution) → repository → DB. The mutation resolver derives service args from the converted input; no cross-layer shortcuts. |
| **IV. Type Safety and Typed Errors** | ✅ New `ServiceError` subclasses with `error_code`/`default_message` (unknown-component, invalid-`command`, invalid-`args`), surfaced via `StructuredErrorExtension`. Full type hints; no union-typed errors; domain/db/context models stay separate. |
| **V. Test-First Development** | ✅ Ships an E2E test (`test_deployment_container_overrides.py`) covering US1–US5 end-to-end on a real vCluster, executed to a **local PASS** with recorded evidence (node ID, command, timestamp, vcluster id, verbatim `PASSED` line). GraphQL schema changes ship **propagation tests** + the schema-walking field-coverage test. |
| **VI. Format and Lint Before Commit** | ✅ `uv run invoke format lint` + frontend ESLint/Prettier before commit; ≤120 cols. |
| **VII. Documentation Accuracy** | ✅ Same-change updates: `docs/` driver-author + reference content (`docs/docs/drivers/`, `docs/docs/reference/` — there is no `docs/how-it-works/` tree in this repo), a new `dev/guides/driver-container-override-consumption.md`, an ADR recording the omit-marker / no-layering decisions, and a new `CONTEXT.md` term ("container override"). |

### Governance Gates (require explicit acknowledgement — Constitution §Governance Gates)

This feature deliberately trips two gates. Both are **intrinsic to the approved spec** and handled by the established conventions rather than relitigated:

- **GraphQL schema modification** — adding `command`/`args` to `ComponentConfigInput`, a new `ComponentContainerOverrides` output type + `Deployment.componentContainerOverrides` resolver, and a `DriverContainerOverrideDoc` surface on `ApplicationDriverVersion`. **Required follow-through**: regenerate `schema.graphql`, run `uv run invoke generate`, and ship propagation tests (per §V and `dev/guides/graphql-propagation-tests.md`) + extend the schema-walking field-coverage test (ADR-014) to cover `ComponentConfigInput ↔ ComponentConfigBlock`.
- **Database schema change** — one additive JSON column on `ApplicationDriverVersion` for the doc-only declaration (mirrors the existing `env_vars` column). No Alembic migration (`metadata.create_all()`); existing rows deserialize the absent key to `None`. The operator-facing override values themselves require **no** schema change (ADR-029 — they ride the existing `Deployment.config` JSON).

**Not tripped**: no new dependencies; no CI/CD workflow change (the E2E test reuses an existing shard marker, no new shard); no auth/authorization change (reuses the existing `Role.READ_WRITE` gate on `deploy`/`updateDeployment`).

**Verdict: PASS** — proceed to Phase 0. Re-checked post-design (see end of Phase 1): no new violations.

## Project Structure

### Documentation (this feature)

```text
specs/014-component-container-overrides/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities, fields, validation, state
├── quickstart.md        # Phase 1 — operator + driver-author walkthrough
├── contracts/           # Phase 1 — GraphQL deltas, filter & error contracts
│   ├── graphql-deltas.md
│   ├── jinja-filters.md
│   └── errors.md
├── checklists/          # (pre-existing)
└── tasks.md             # Phase 2 — created by /speckit.tasks (NOT here)
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── context/models/
│   ├── config.py                         # EXTEND ComponentConfigBlock: command/args fields + validators
│   └── components.py                     # ADD ResolvedComponentContainerOverride; attach to ComponentContext
├── services/
│   ├── container_overrides/              # NEW module (mirrors services/env_vars/)
│   │   ├── __init__.py
│   │   ├── exceptions.py                 # InvalidContainerCommandError, InvalidContainerArgsError, UnknownComponentContainerOverrideError
│   │   ├── validator.py                  # validate_container_override (list-of-str, non-empty, empty-string OK)
│   │   └── resolver.py                   # ContainerOverridesResolver: per-component resolve + orphan detection (NO layering)
│   ├── deployment.py                     # EXTEND write-side validation to cover command/args (unknown component + shape)
│   ├── context.py                        # Attach resolved container overrides to each ComponentContext
│   ├── applications.py                   # Materialise doc-only declaration onto ApplicationDriverVersion
│   └── driver/models/resources/
│       ├── container_overrides.py        # NEW DriverContainerOverrideDoc (doc-only, mirrors env_vars.py)
│       └── driver.py                     # Specification gains optional doc-only block
├── agent/service/kubernetes/resources/builders/
│   └── application.py                    # ADD component_command / component_args Jinja filters + register
├── api/definitions/
│   ├── deployment/inputs.py              # EXTEND ComponentConfigInput + _flatten_components
│   ├── deployment/model.py               # ADD ComponentContainerOverrides type + resolver
│   └── application_driver/model.py       # Expose DriverContainerOverrideDoc
├── db/models.py                          # ADD ApplicationDriverVersion.container_overrides JSON column
└── tests/
    ├── unit/agent/                       # Jinja filter render tests (omit-marker behaviour)
    ├── unit/services/                    # resolver + validator unit tests
    ├── functional/graphql/               # propagation + introspection field-coverage tests
    └── e2e/test_deployment_container_overrides.py   # NEW E2E (US1–US5), shard_configuration

python_sdk/src/styrmin_sdk/graphql/      # regen input/output types; new read .graphql query
frontend/src/
├── components/deployment/configuration/sections/
│   ├── edit/ComponentOverridesSection.tsx        # EXTEND: command/args editors per component
│   └── read/ComponentOverridesSummary.tsx        # EXTEND: show command/args
├── lib/deployment-input.ts                       # componentsDictToList carries command/args
└── graphql/                                       # selection-set updates; regen generated/graphql.ts

driver/examples/simple-app/
├── driver.styrmin.yml                    # ADD doc-only container-override declaration
└── values.j2.yml                         # WIRE component_command / component_args consumption

docs/                                     # driver-author + reference updates (docs/docs/drivers/, docs/docs/reference/)
dev/guides/driver-container-override-consumption.md   # NEW (mirrors driver-env-var-consumption.md)
dev/adr/adr-045-container-override-no-layering-and-omit-marker.md   # NEW
CONTEXT.md                                # NEW term: "container override"
```

**Structure Decision**: Existing web + SDK + CLI + drivers layout. The dominant pattern is **mirror the env-vars feature**: a new `services/container_overrides/` module parallels `services/env_vars/`; everything else extends the file that already handles the per-component env-vars equivalent. No new top-level projects or directories beyond the parallel service module.

## Complexity Tracking

> No constitution violations require justification. The two governance gates (GraphQL + additive DB column) are intrinsic to the feature and handled by established conventions, not by added architectural complexity.

| Decision | Why it is *not* extra complexity |
|----------|----------------------------------|
| New `services/container_overrides/` module instead of folding into `services/env_vars/` | Keeps env-vars behaviour byte-identical (SC-004 no-regression) and isolates the no-layering resolver; parallels the existing `services/scheduling/` ↔ `services/env_vars/` split. |
| New `ComponentContainerOverrides` GraphQL output type rather than overloading `ComponentEnvVars` | The two carry different shapes (`[String!]` lists vs. `[EnvVar!]`) and orphan semantics are read independently; a shared type would conflate them. |
