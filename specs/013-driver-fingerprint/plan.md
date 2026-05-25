# Implementation Plan: Driver Reload Identity — Provenance Fingerprint

**Branch**: `013-driver-fingerprint` | **Date**: 2026-05-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/013-driver-fingerprint/spec.md`

## Summary

Fix the ORM cascade misconfiguration on `ApplicationDriverVersion.actions` and `.component_configs` that today raises `IntegrityError` on local reload, and introduce a content-addressable **provenance fingerprint** on every application driver version row so that two loads of the same `version` string with different content become two distinct rows. The fingerprint is `content_hash` (SHA-256 over a fixed three-file canonical input) for `source_type = "local"`, and `source_commit_sha` (the resolved git commit SHA at the loaded ref) for `source_type = "git"`. The upsert lookup widens to include the fingerprint; the existing delete-and-replace branch in the local load path is removed entirely. Read-only GraphQL fields expose both columns, and user-visible surfaces (frontend driver list and deployment detail, CLI driver/deployment listings) render `<version>@<short-fingerprint>` so users can distinguish multiple same-`version` rows at a glance.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 (frontend, Node 22)
**Primary Dependencies**: Strawberry GraphQL, SQLModel + SQLAlchemy (async, asyncpg), Pydantic, Cyclopts (CLI), httpx (SDK), `dulwich` (git driver provider). Frontend: React 19, TanStack Query/Router, Radix UI, Tailwind.
**Storage**: PostgreSQL via SQLModel/SQLAlchemy. Schema managed by `metadata.create_all()` — no Alembic migration required since Styrmin is not yet deployed in production.
**Testing**: pytest (backend unit, integration, E2E with vcluster); Vitest + React Testing Library (frontend); ariadne-codegen verifies SDK type generation
**Target Platform**: Linux server (backend, agent); modern browser (frontend); macOS/Linux developer workstations (CLI, local driver loading)
**Project Type**: Web application (backend + frontend) with auxiliary Python SDK, CLI, and agent processes
**Performance Goals**: SHA-256 hashing on driver load is bounded by file sizes (`driver.styrmin.yml`, values template, `actions.py` — each a few KB); end-to-end load time MUST NOT regress noticeably (<10 ms overhead per load).
**Constraints**: Hashing MUST be deterministic across platforms (raw-byte concatenation, length-framed); no YAML canonicalisation; concurrent reloads MUST converge on a single row.
**Scale/Scope**: Single feature shard touches backend (db model, repository, services, GraphQL definitions), SDK (regenerated types), CLI (rendering), frontend (driver list + deployment detail rendering), docs (CONTEXT already updated; dev guide pending), tests (unit + propagation + E2E + frontend component).

## Constitution Check

Walk against `dev/constitution.md` v1.4.0.

- **§I Declarative state reconciliation**: ✅ Driver loading is idempotent by construction (same fingerprint key → no-op upsert). The reconciliation loop is unaffected — `Deployment` and `ApplicationInstance` rows continue to reference specific `ApplicationDriverVersion.id` UUIDs as before. No imperative side effects introduced.
- **§II Driver-based deployment**: ✅ No change to how applications are deployed. Sharpens driver-version identity; driver semantics unchanged.
- **§III Layered architecture**: ✅ Hash computation lives in `services/driver/loaders.py` (service layer). Repository method gets a new lookup signature. GraphQL definition gets two new fields. No cross-layer shortcuts.
- **§IV Type safety and typed errors**: ✅ Two new columns are `str | None` at the model layer; ty/mypy will enforce. No new `ServiceError` subclass needed (hash computation cannot fail meaningfully; git commit resolution failures surface via the existing `DriverLoadingError` chain). No `Union` for error handling.
- **§V Test-first / E2E required**: ✅ One E2E (`test_driver_reload_identity.py`, `shard_readonly`, `api_only`) covering local reload + content edit + idempotency. Unit tests cover the hash function, the git commit-sha resolution, the upsert behaviour, and the cascade delete. Tests written before implementation, observed to PASS locally, evidence captured per §V.
- **§V GraphQL propagation tests**: ✅ Two new read fields (`content_hash`, `source_commit_sha`) on `ApplicationDriverVersion` → mandatory propagation tests per `dev/guides/graphql-propagation-tests.md`.
- **§VI Format and lint**: ✅ `uv run invoke format lint` will pass before commit (enforced by pre-commit hooks).
- **§VII Documentation accuracy**: ✅ CONTEXT.md "Provenance fingerprint" entry added during grilling. A new `dev/guides/driver-iteration.md` (or extension of an existing guide) documents the iteration loop, the three-file hash input, and the row-accumulation behaviour. `docs/` site pages touching driver loading and the driver-version surface are updated to mention the fingerprint suffix and the `<version>@<short>` display form.

**Governance gates crossed**:
- ✅ Database schema change — two new nullable columns, two cascade kwargs. Documented in this plan.
- ✅ GraphQL schema change — two new read-only fields on `ApplicationDriverVersion`. Propagation tests required.
- ✅ No new dependency.
- ✅ No CI/CD change.
- ✅ No auth change.

**Verdict**: All gates pass. No Complexity Tracking entries required.

### E2E coverage decisions (Constitution §V audit trail)

Per Constitution §V, every new feature MUST ship with an E2E test covering the user-visible flow, and any decision to skip E2E coverage for a portion of the feature MUST be explicitly approved by a reviewer rather than decided unilaterally by the implementer.

| User-visible flow | E2E shipped? | Decision |
|---|---|---|
| **Local-source reload + content drift** (User Stories 1, 3) | ✅ Yes — `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change`. Markers: `@pytest.mark.api_only`, `@pytest.mark.ci`, `@pytest.mark.shard_readonly`. Local PASS evidence to be captured per §V at implementation time (test command, ISO timestamp, vcluster id, PASSED line). | Mandatory; no decision required. |
| **Git-source reload + commit drift** (User Story 2) | ❌ No E2E. Covered by a unit test in `backend/tests/unit/services/driver/test_loaders_fingerprint.py` against a mocked git provider that returns sequential commit SHAs. | **Reviewer-approved skip.** The project owner (issue #262 author) explicitly approved this skip during the `/grill-idea` session on 2026-05-25 — see `.specify/idea-brief.md` constitution-alignment section: "Git path covered by unit test against a mocked git provider — a real ephemeral git fixture is out of scope for v1." Rationale: the git-path behaviour is mechanically simpler (just record the SHA the provider already resolves); building a real ephemeral git server inside the E2E fixture stack adds significant infrastructure cost for marginal incremental coverage. Re-visit if any future regression traces back to the git provider's SHA-resolution path. |
| **Cascade-on-delete fix** (User Story 3) | ❌ No E2E (unit test only). | Internal ORM behaviour; no user-facing flow today exercises the delete path (the load path itself is being changed so it no longer triggers a delete). Covered by `test_applications_upsert_idempotent.py` exercising a programmatic delete against a real database session. **Reviewer-approved**: same grilling session, same approval rationale (no current user flow exercises this branch). |

## Project Structure

### Documentation (this feature)

```text
specs/013-driver-fingerprint/
├── plan.md                    # This file
├── spec.md                    # Feature specification
├── research.md                # Phase 0 — research decisions
├── data-model.md              # Phase 1 — schema & domain model
├── contracts/                 # Phase 1 — GraphQL + SDK contract changes
│   ├── graphql-schema.md      # New ApplicationDriverVersion fields
│   └── sdk-cli-rendering.md   # `<version>@<short>` display rule
├── quickstart.md              # Phase 1 — manual verification walkthrough
├── checklists/
│   └── requirements.md        # Spec quality checklist (Phase 1 of /speckit-specify)
└── tasks.md                   # Phase 2 — generated by /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── styrmin_backend/
│   ├── db/
│   │   └── models.py                                    # MODIFY: ApplicationDriverVersion +2 cols; cascade kwargs
│   ├── repository/
│   │   └── application_driver_version.py                # MODIFY: replace get_by_source_path_and_version with widened lookup
│   ├── services/
│   │   ├── applications.py                              # MODIFY: remove delete-and-replace branch; use new upsert key
│   │   └── driver/
│   │       ├── loaders.py                               # MODIFY: compute content hash; capture commit SHA from provider
│   │       ├── provider.py                              # MODIFY: GitDriverProvider exposes resolved commit SHA
│   │       └── hash.py                                  # NEW: pure hash function over canonical three-file input
│   └── api/
│       └── definitions/application_driver/model.py      # MODIFY: ApplicationDriverVersion gains content_hash, source_commit_sha
└── tests/
    ├── unit/services/driver/
    │   ├── test_hash.py                                 # NEW: canonical hash determinism + framing tests
    │   └── test_loaders_fingerprint.py                  # NEW: loader populates fingerprint per source_type
    ├── unit/api/schema/
    │   └── test_application_driver_version_propagation.py  # NEW: GraphQL propagation tests for both new fields
    ├── unit/services/
    │   └── test_applications_upsert_idempotent.py       # NEW: upsert idempotent + new-fingerprint path
    └── e2e/
        └── test_driver_reload_identity.py               # NEW: P1 E2E (api_only, shard_readonly, ci)

python_sdk/
├── src/styrmin_sdk/graphql/
│   ├── _generated/                                      # REGENERATE: ariadne-codegen picks up new fields
│   └── <relevant queries>.graphql                       # MODIFY if any existing query selects ApplicationDriverVersion
└── tests/                                               # MODIFY: any SDK model snapshot tests

cli/
├── styrminctl/
│   └── commands/
│       ├── driver.py                                    # MODIFY: render <version>@<short> in driver list/detail
│       └── deployment.py                                # MODIFY: render driver-version reference with suffix
└── tests/                                               # MODIFY/ADD: rendering tests

frontend/
├── src/
│   ├── components/
│   │   ├── drivers/
│   │   │   └── VersionList.tsx (or equivalent)          # MODIFY: render <version>@<short>
│   │   └── deployment/
│   │       └── (configuration / detail components)      # MODIFY: render driver-version with suffix
│   ├── pages/drivers/DriverDetailPage.tsx               # MODIFY: detail surface shows full fingerprint + copy button
│   └── lib/driverVersion.ts (NEW or existing helper)    # NEW: helper to format <version>@<short>
└── src/__tests__/                                       # MODIFY/ADD: tests for new rendering behaviour

CONTEXT.md                                                # ALREADY UPDATED in grilling — provenance fingerprint entry
dev/guides/driver-iteration.md                           # NEW: dev loop + row accumulation behaviour
docs/                                                    # MODIFY: any page documenting driver loading or version surface
schema.graphql                                            # REGENERATE: includes new fields
```

**Structure Decision**: Web-application layout (Option 2). Backend changes are concentrated in the driver service + repository + GraphQL definition; SDK regenerates from the schema; CLI and frontend each get formatter changes plus the detail-page exposure of the full fingerprint. No new top-level packages.

## Complexity Tracking

> No constitution violations to track. All gates pass cleanly.
