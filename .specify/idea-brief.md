# Idea Brief: Driver Reload Identity — Content Hash + Git Commit Provenance

**Status**: Ready for /speckit-specify
**Source issue**: [opsmill/styrmin#262](https://github.com/opsmill/styrmin/issues/262)
**Seed**: Re-loading a local **application driver** with the same `(source_path, version)` pair raises `IntegrityError` (cascade misconfiguration on `ApplicationDriverVersion.actions` / `.component_configs`). Separately, the upsert key `(source_path, version)` is too coarse: a driver author can edit the YAML, values template, or `actions.py` without bumping `version` and the platform silently replaces the row, destroying provenance for any **deployment** or **instance** that referenced it. The same drift problem exists on the git load path. Fix the cascade bug AND introduce a **provenance fingerprint** — `content_hash` (SHA-256) for local drivers, `source_commit_sha` for git drivers — so that distinct content under the same `version` string coexists as distinct `ApplicationDriverVersion` rows.

## Users and Value

- **Primary user**: driver authors (internal platform team + external integrators) iterating on a driver locally or via git, and platform operators reading deployment provenance.
- **Pain today**:
  - Local reloads of the same `(path, version)` crash with `IntegrityError`. Workaround is bumping `version` manually each iteration.
  - Same `version` string with different content silently replaces the previous row, breaking the link between historical **instances** and the bytes they were deployed from.
  - Git authors hit the analogous trap: amending a tag or pushing new content under the same `version` string silently shifts what "v1.2.3" means.
- **Better looks like**: authors iterate freely (no `version` bumps required); every load that produces different content becomes its own addressable `ApplicationDriverVersion` row; old deployments keep pointing at the exact bytes they were deployed from; the UI/CLI surfaces a `<version>@<short>` form so users can tell two same-`version` rows apart at a glance.

## Scope

Applies to **both** load paths:

- **Local source** (`source_type = "local"`): provenance fingerprint = SHA-256 over canonical local driver bytes (see Decisions).
- **Git source** (`source_type = "git"`): provenance fingerprint = resolved git commit SHA from the provider (already content-addressable, no recompute).

## User Journeys

### P1 — Local driver iteration without `version` bumps

- **Journey**: an author edits `driver.styrmin.yml`, the values template, or `actions.py` on local disk and re-runs `styrminctl driver load <path>`. A new `ApplicationDriverVersion` row is created alongside the old one. A subsequent reload with no changes is a no-op.
- **Given** a driver loaded at `version: "1"` with content state A,
  **When** the author edits the values template (e.g. adds a `commonLabels` entry) and re-runs `driver load`,
  **Then** a new `ApplicationDriverVersion` row exists with the same `version` and a different `content_hash`; the previous row is intact; any deployment that referenced the previous row still references it.

### P2 — Git driver reload distinguishes commits

- **Journey**: a CI pipeline or user loads a driver from git, then loads again after a new commit lands on the same branch/tag. Each load resolves a commit SHA; loads at distinct SHAs create distinct rows.
- **Given** a driver loaded from `repo@branch` at commit `abc123…` with `version: "1.2.3"`,
  **When** the same load is repeated after a new commit `def456…` is pushed,
  **Then** a new `ApplicationDriverVersion` row exists with the same `version` and `source_commit_sha = def456…`; the `abc123…` row is intact.

### P3 — Cascade crash on local reload is gone

- **Journey**: the cascade-misconfiguration bug is fixed independently of the content-hash work, so the "bump version each reload" workaround is no longer required even when a future operation does delete an `ApplicationDriverVersion`.
- **Given** an `ApplicationDriverVersion` row with children (`actions`, `component_configs`),
  **When** the row is deleted via the repository,
  **Then** the children are deleted by ORM cascade, no `IntegrityError` is raised, no orphan rows remain.

## Functional Requirements

- **FR-001**: System MUST add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` to `ApplicationDriverVersion.actions` and `ApplicationDriverVersion.component_configs` in `backend/styrmin_backend/db/models.py`.
- **FR-002**: System MUST add two nullable columns to `ApplicationDriverVersion` — `content_hash: str | None` (SHA-256 hex) and `source_commit_sha: str | None` (git commit SHA). Exactly one of the two is non-null on any new row; the discriminator is `source_type`.
- **FR-003**: System MUST compute `content_hash` at load time for `source_type = "local"` as SHA-256 over the length-prefixed concatenation of three files in fixed order: (1) `driver.styrmin.yml`, (2) the values template, (3) `actions.py` (only when `spec.actions` is non-empty). Raw bytes, no YAML canonicalisation. Other files in the directory MUST NOT contribute.
- **FR-004**: System MUST record `source_commit_sha` at load time for `source_type = "git"` from the resolved commit returned by the git provider.
- **FR-005**: System MUST treat `(application_driver_id, source_type, source_repository, source_branch, source_path, version, content_hash | source_commit_sha)` as the upsert lookup key. Same key → idempotent no-op (no new row, no error). Different fingerprint → new row created, **no delete of any existing row**.
- **FR-006**: System MUST remove the existing `if existing is not None: await uow.application_driver_versions.delete(existing)` branch in `load_application_driver_from_local_directory`.
- **FR-007**: System MUST surface `content_hash` and `source_commit_sha` on the GraphQL `ApplicationDriverVersion` type as read-only fields.
- **FR-008**: Frontend, CLI, and SDK MUST render any driver-version reference as `<version>@<short>` where `<short>` is the first 7 chars of the populated fingerprint, on lists and on deployment detail surfaces. Detail surfaces MUST also show the full fingerprint verbatim with a copy affordance.
- **FR-009**: Users MUST be able to load a local driver repeatedly without `IntegrityError`.

### Verification ideas (testability checks for the above)

- FR-001: deleting an `ApplicationDriverVersion` row with children no longer raises `IntegrityError`; children are gone after the delete.
- FR-002: schema introspection (or a unit test against the model) confirms both columns exist with the expected nullability.
- FR-003: unit test loads two driver directories that differ only in `actions.py`, asserts hashes differ; another test adds/removes `README.md` between loads, asserts hashes equal.
- FR-005: unit test reloads the same content → one row; reloads with edited values template → two rows.
- FR-007: GraphQL propagation test (mandatory per Constitution §V) — write `content_hash` via a service call, read it back via the resolver.
- FR-008: frontend visual test or component test asserts the `<version>@<short>` label appears.

## Key Entities

- **ApplicationDriverVersion** (existing, modified): gains `content_hash` and `source_commit_sha` columns; identity widens from `(source_path, version)` to include the fingerprint.
- **Action**, **ComponentConfig** (existing): the parent relationship on `ApplicationDriverVersion` gains `cascade="all, delete-orphan"`.
- No new entities.

## Edge Cases

- **Identical content, different `source_path` (local)**: two different on-disk locations produce identical hashes. Treated as distinct rows because `source_path` is part of identity.
- **Identical commit SHA, different branch (git)**: same commit reachable from two branches. Treated as distinct rows because `source_branch` is part of identity.
- **`actions.py` exists but `spec.actions` is empty**: file is ignored by the hash, mirroring loader behaviour. Editing the orphan file does not produce a new row.
- **`actions.py` is required but missing**: handled by existing loader validation, not by the hash design. Hash is never computed in this failure case.
- **Concurrent reloads of the same driver**: both compute the same fingerprint and race to insert. Upsert path MUST handle the race (existing repository idempotency or a unique index covering the fingerprint).
- **`source_type` outside `{local, git}`**: not present today; if added later, that source type MUST define its own fingerprint column or extend the discriminator rule explicitly.

## Success Criteria

- **SC-001**: A driver author can reload a local driver 100 times with mixed no-op and content-change patterns and observe zero errors; the resulting `ApplicationDriverVersion` row count equals the number of distinct content snapshots loaded.
- **SC-002**: For any given `Deployment` or `ApplicationInstance` row, the `ApplicationDriverVersion` it references at creation time is the same row it still references at any later read — no in-place mutation, no replacement.
- **SC-003**: When a driver author re-loads a local driver with no file changes, the operation completes without creating a new `ApplicationDriverVersion` row (idempotency).
- **SC-004**: When a driver author re-loads a local driver after any whitespace-only or content edit to the three hashed files, a new `ApplicationDriverVersion` row is created (drift detection).
- **SC-005**: Any user-facing surface that names a driver version (frontend driver list, deployment detail, `styrminctl` driver list output) includes the short fingerprint suffix so two rows with the same `version` are visually distinguishable.

## Constitution Alignment

- **§I Declarative reconciliation**: driver loading is idempotent by construction (same fingerprint → no-op). No impact on the reconciliation loop — `Deployment` and `ApplicationInstance` rows continue to reference specific `ApplicationDriverVersion.id` UUIDs as before.
- **§II Driver-based deployment**: unchanged. Sharpens driver identity without altering driver semantics.
- **§III Layered architecture**: hash computation lives in `services/driver/loaders.py`, called from `services/applications.py`. Repository methods extend their upsert lookup. GraphQL layer exposes the new fields. No cross-layer shortcuts.
- **§IV Typed errors**: no new `ServiceError` subclass needed. Hash computation cannot fail meaningfully; git commit resolution failures continue to surface via existing `DriverLoadingError`.
- **§V E2E coverage**: ship `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change`. Loads a local fixture driver, mutates the values template, reloads via SDK, asserts two `ApplicationDriverVersion` rows with the same `version` and distinct `content_hash` exist and are queryable via GraphQL. Markers: `@pytest.mark.api_only`, `@pytest.mark.ci`, `@pytest.mark.shard_readonly`.
- **§V Git path coverage**: covered by a unit test against a mocked git provider that returns sequential commit SHAs — a real ephemeral git fixture is out of scope for v1.
- **§V GraphQL propagation tests**: required for `ApplicationDriverVersion.content_hash` and `ApplicationDriverVersion.source_commit_sha` (new read fields). Use the schema-walking propagation harness per [`dev/guides/graphql-propagation-tests.md`](dev/guides/graphql-propagation-tests.md).
- **§VII Documentation accuracy**:
  - New entry in [`CONTEXT.md`](../CONTEXT.md) under "Application drivers" — added during this grilling session (term: **Provenance fingerprint**).
  - New `dev/guides/` entry describing the iteration loop ("you do not need to bump `version` while iterating; the platform tracks drift via fingerprint and keeps history") and the row-accumulation behaviour.
  - Update any `docs/` page that documents driver loading or the driver-version surface to reflect the new fingerprint fields and `<version>@<short>` display form.

## Governance Gates Crossed

- [x] Database schema change — two new nullable columns on `ApplicationDriverVersion`; cascade kwargs added to two existing relationships.
- [x] GraphQL schema change — two new read-only fields on the `ApplicationDriverVersion` type.
- [ ] New dependency — none (hashlib stdlib; git commit resolution already in place).
- [ ] CI/CD change — none.
- [ ] Auth change — none.

## Assumptions

- Styrmin is not yet deployed anywhere in production. There are no legacy `ApplicationDriverVersion` rows requiring backfill. New columns are added via `metadata.create_all()` on fresh databases.
- The git driver provider already resolves and exposes the commit SHA of the loaded ref; no provider changes are required beyond surfacing that value to the service layer.
- The frontend driver-detail page and CLI driver list are the only user-facing surfaces that name driver versions today; any other surface added during implementation will adopt the same `<version>@<short>` convention.
- `ApplicationDriverVersion` rows accumulate without bound under v1; this is operationally acceptable given typical row size (a few KB).

## Out of Scope (v1)

- Automatic garbage collection of unreferenced `ApplicationDriverVersion` rows. A future admin-driven `styrminctl driver prune` command (or equivalent admin GraphQL mutation) is filed as a follow-up.
- Backfilling `content_hash` / `source_commit_sha` for any pre-existing rows (no such rows exist).
- Extending the local content hash to cover a multi-file `actions/` directory or additional driver files. Hash input is fixed at the three files the loader currently reads.
- Parsing or accepting `<version>@<short>` as input (e.g. as a CLI argument). Display-only.
- Any change to the git driver provider beyond exposing the commit SHA it already resolves.
- E2E coverage of the git path (covered by unit test against a mocked git provider in v1).

## Open Questions

None — all clarifications resolved during grilling.
