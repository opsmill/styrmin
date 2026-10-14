# Implementation Plan: Container `command` and `args` Overrides Applied by Post-Render

**Branch**: `fac/check-container-cmd-arg-post-render-2yje1` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/022-post-render-container-overrides/spec.md` (PRD: [#457 comment](https://github.com/opsmill/styrmin/issues/457#issuecomment-6166451728))

## Summary

A user's `command` and `args` override for one component reaches the pod today only when the driver's `values.j2.yml` passes it to a chart value. This change applies it the way env vars and image overrides are applied: a post-render strategic merge into the component container that the driver declares, followed by the existing guard that fails the render when the container is missing.

Technical approach (details in [research.md](research.md)):

- Add `command` and `args` to the strategic-merge container patch (renamed `ContainerMergePatch`), and build the merge patch and the guard whenever any of env vars, image, `command` or `args` applies (D-001, D-003).
- Put the "applies when the component declares a component container and is not orphaned" rule in one function used by the patch builder, the action primitives and the three `isApplicable` read fields (D-002).
- Turn `component_command` and `component_args` into stubs that raise `RETIRED_TEMPLATE_FILTER` with a new migration guide URL (D-004).
- Extend the `COMPONENT_CONTAINER_NOT_DECLARED` write check to `command` and `args` (D-005).
- Remove `spec.container_overrides` from the driver format, the database (one Alembic revision) and the API; add `ComponentContainerOverrides.isApplicable` (D-006 to D-008).
- Migrate the three example drivers and bump their versions (D-009); gate the frontend Command and Args editors on the component container (D-010).
- Extend the existing container override E2E and add kustomize, parity and propagation tests (D-011).

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK); TypeScript 5.9.3 with React 19 (frontend, Node 22)

**Primary Dependencies**: Strawberry GraphQL, SQLModel/SQLAlchemy (async), Pydantic v2, Jinja2, Alembic, PyYAML; FluxCD helm-controller post-renderers (kustomize); TanStack Form and Zod (frontend). No new dependency.

**Storage**: PostgreSQL. One Alembic revision drops `applicationdriverversion.container_overrides`. `Deployment.config` JSON is unchanged.

**Testing**: pytest (unit, functional GraphQL propagation, integration with real `kubectl kustomize` and `helm template`, E2E on vCluster, `shard_configuration`); Vitest and React Testing Library (frontend).

**Target Platform**: Styrmin backend and agent on Kubernetes; workloads patched by helm-controller post-renderers.

**Project Type**: Web service (backend + agent + frontend) with a Python SDK and example drivers.

**Performance Goals**: No new goal. At most two extra patches per component per workload kind, as for env vars and images today.

**Constraints**:

- The patch output must be the same for the same stored config (Constitution §I).
- No new error code (FR-011).
- The env var migration URL in the existing `RETIRED_TEMPLATE_FILTER` message must not change.
- Every in-repo component that accepted an override keeps a component container, so stored values keep applying (SC-005).

**Scale/Scope**: Three example drivers; one E2E file extended; about 25 backend files, 1 frontend component, 6 documentation pages and 1 new ADR.

All items are resolved; [research.md](research.md) has no open "NEEDS CLARIFICATION".

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How the design meets it |
|-----------|--------|-------------------------|
| I. Declarative state reconciliation | Pass | Patches are rebuilt from the stored config on every render; a clear produces no patch, so the chart's values come back with no marker (D-001, D-012) |
| II. Driver-based deployment | Pass | The driver still declares where an override goes (`components.<name>.container`); no deployment logic leaves the driver model |
| III. Layered architecture | Pass | The write check stays in the deployment service; GraphQL resolvers call service helpers; the agent consumes context only |
| IV. Type safety and typed errors | Pass | Reuses `RETIRED_TEMPLATE_FILTER`, `COMPONENT_CONTAINER_NOT_DECLARED`, `COMPONENT_CONTAINER_NOT_FOUND`; `ApplicableOverrides` is a typed frozen dataclass |
| V. Test-first development | Pass | Extends the existing `shard_configuration` E2E instead of booting a new stack; propagation test for `isApplicable`; kustomize and parity tests (D-011). Local PASS evidence is required at implementation |
| VI. Format and lint | Pass | `uv run invoke format lint` and frontend lint in the tasks |
| VII. Documentation accuracy | Pass | Migration guide, `creating-a-driver.md`, `context.md`, glossary, changelog page, ADR-069, CONTEXT.md, `dev/knowledge` pages and deletion of the old guide are tasks in the same change |
| Governance gates | Pass | Database and GraphQL changes approved in the PRD review session on 2026-10-14; no new dependency, CI or auth change |

**Post-design re-check**: Pass. Phase 1 added no dependency, no new error code and no layer shortcut.

## Project Structure

### Documentation (this feature)

```text
specs/022-post-render-container-overrides/
├── spec.md
├── plan.md               # This file
├── research.md           # D-001 to D-012, dependency evaluation
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── graphql.md
│   ├── errors.md
│   ├── post-render-patch.md
│   └── driver-format.md
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks output
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── agent/service/kubernetes/resources/
│   ├── blocks/patches.py                     # ContainerEnvPatch → ContainerMergePatch (+command, +args)
│   └── builders/application.py               # retire component_command / component_args
├── services/
│   ├── component_container/
│   │   ├── overrides.py                      # override_applies, ApplicableOverrides, applicable_overrides
│   │   └── patch_builder.py                  # build when any override applies
│   ├── container_overrides/
│   │   ├── __init__.py, resolver.py          # docstrings: no template consumption
│   │   └── exceptions.py                     # remove DriverContainerOverrideDocComponentMismatchError
│   ├── deployment.py                         # COMPONENT_CONTAINER_NOT_DECLARED for command/args
│   ├── env_vars/exceptions.py                # ComponentContainerNotDeclaredError.override += command, args
│   ├── exceptions.py                         # RetiredTemplateFilterError per filter + new URL
│   ├── applications.py                       # stop persisting the block
│   └── driver/
│       ├── loaders.py, validators.py         # remove block validation
│       └── models/resources/
│           ├── driver.py                     # remove Specification.container_overrides
│           └── container_overrides.py        # deleted
├── actions/primitives.py                     # use applicable_overrides
├── api/definitions/
│   ├── application_driver/model.py           # remove containerOverrides, DriverContainerOverrideDoc
│   └── deployment/model.py                   # ComponentContainerOverrides.isApplicable; shared rule
└── db/
    ├── models.py                             # remove ApplicationDriverVersion.container_overrides
    └── migrations/versions/<rev>_drop_driver_version_container_overrides.py

backend/tests/
├── unit/services/component_container/        # overrides + patch builder
├── unit/agent/                               # patch text, retired filters (rename container_overrides test)
├── unit/services/driver/                     # loader rejects the block (replace doc validator test)
├── unit/services/                            # write check, resolver, context
├── unit/db/test_drop_container_overrides_migration.py
├── unit/test_drivers_have_no_override_wiring.py   # SC-002
├── unit/services/component_container/test_example_driver_overrides.py   # SC-001 over every example driver
├── integration/test_component_container_kustomize.py   # command/args cases
├── integration/test_container_override_migration_parity.py   # SC-005 (+ fixtures/legacy_drivers/)
├── functional/graphql/test_container_overrides_propagation.py
└── e2e/test_deployment_container_overrides.py

python_sdk/src/styrmin_sdk/graphql/            # delete get_driver_container_override_docs.graphql; regenerate
frontend/src/components/deployment/configuration/sections/edit/
└── ComponentOverridesSection.tsx (+ .test.tsx)

driver/examples/{simple-app,infrahub,infrahub-enterprise}/   # values.j2.yml, driver.styrmin.yml, version bump

docs/docs/drivers/{migrating-container-overrides.md (new), creating-a-driver.md, context.md}
docs/docs/concepts-and-architecture/glossary.md (Component overrides, Component container), docs/docs/changelog.md
docs/docs/reference/styrminctl.md (apply note on component override checks)
dev/adr/0069-container-command-args-by-post-render.md (new), dev/adr/0045-…md (status note), dev/adr/0058-…md (link)
dev/guides/driver-container-override-consumption.md (deleted) and its links
dev/knowledge/backend/{services,data-models,api,hooks-and-actions}.md, dev/knowledge/frontend/deployment-configuration.md
CONTEXT.md, changelog/457.removed.md, changelog/457.changed.md
```

**Structure Decision**: Existing web-service layout. The feature changes existing modules on the post-render path that ADR-057 and ADR-058 created; no new package.

## Implementation Order

The user stories ship together (spec Context), but the work has a natural order:

1. **Foundation**: `override_applies`, `ApplicableOverrides`, `ContainerMergePatch` with `command`/`args` serialised by `yaml.dump` only, patch builder condition (log booleans, never values), primitives switch-over. Unit tests, including a value with a newline and `- op:`.
2. **User Story 1 (P1)**: integration tests on kustomize; SC-001 test over every example driver; migrate the three example drivers and bump versions; E2E extension inside the existing `test_us2` and `test_us3` nodes. Without step 3 the old filters still work, so this step can land first in the branch.
3. **User Story 2 (P2)**: retire the filters with the new message and URL; remove `spec.container_overrides` from model, loader, validators, persistence, database (revision + migration test), GraphQL and SDK; parity test; SC-002 test.
4. **User Story 3 (P3)**: write check for `command`/`args`; `isApplicable` read field and propagation test; frontend editor gating and test.
5. **Documentation and changelog**: migration guide (including that pods on an unmigrated driver version keep running while the render fails), driver docs, glossary, `styrminctl` reference, changelog page and fragments, ADR-069 and status notes on ADR-045/058, CONTEXT.md, `dev/knowledge`, delete the old guide.
6. **Verification**: regenerate schema and SDK, `format lint`, unit/functional/integration suites, frontend tests, E2E with recorded PASS evidence (Constitution §V).

## Risks

| Risk | Mitigation |
|------|------------|
| helm-controller's embedded kustomize treats `command`/`args` differently from kustomize v5.7.1 (A-001) | The E2E reads the pod's container spec after set, change and clear |
| A clear does not roll the workload (D-012) | `test_us3` compares the pod spec with the captured chart spec; fix the operator's change detection in the same change if it fails |
| Users with stored overrides that never applied (for example `command` on infrahub `server`) see them apply after the move | Migration guide and changelog tell users to review stored overrides first (spec edge case) |
| Tests or fixtures pin the old example driver versions | Search for the version strings during the driver migration task |
| Removing `get_driver_container_override_docs` breaks SDK callers | Listed in the `removed` changelog fragment; Styrmin is before 1.0 (A-003) |

## Complexity Tracking

No constitution violation to justify.
