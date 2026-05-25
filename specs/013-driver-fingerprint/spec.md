# Feature Specification: Driver Reload Identity — Provenance Fingerprint

**Feature Branch**: `013-driver-fingerprint`
**Created**: 2026-05-25
**Status**: Draft
**Source**: [`/.specify/idea-brief.md`](../../.specify/idea-brief.md), [opsmill/styrmin#262](https://github.com/opsmill/styrmin/issues/262)
**Input**: User description: "Driver reload identity via content hash and git commit provenance fingerprint per issue #262"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Local driver iteration without `version` bumps (Priority: P1)

A driver author edits files on their local working copy of an application driver (`driver.styrmin.yml`, the values template, or `actions.py`) and re-runs the driver-load command without bumping the `version` string. Each load that produces different content becomes a distinct application driver version row, identified by its provenance fingerprint. Reloads with no changes are a no-op.

**Why this priority**: this is the headline value of the feature — it directly removes the iteration friction that drove the bug report. Without it, the rest of the feature has no observable user value.

**Independent Test**: load a local fixture driver, edit the values template (e.g. add a `commonLabels` entry) without changing `version`, reload via the SDK, and observe two application driver version rows for the same `version` with different `content_hash` values. Reload again with no changes and observe the row count stays at two. Fully exercisable end-to-end via the SDK; no UI flow required.

**Acceptance Scenarios**:

1. **Given** a local driver at `version: "1"` loaded once with content state A, **When** the author edits the values template to add a `commonLabels` entry (no `version` change) and re-runs `driver load`, **Then** a new application driver version row exists with the same `version` and a different `content_hash`; the previous row is intact and any prior deployment that referenced it still references it.
2. **Given** an application driver version row exists with content hash H, **When** the same local directory is loaded again with no file changes, **Then** no new row is created and the operation completes successfully.
3. **Given** two local copies of the same driver at different on-disk paths with identical content, **When** both are loaded, **Then** two distinct application driver version rows exist (one per `source_path`), each with the same `content_hash` value.

---

### User Story 2 — Git driver reload distinguishes commits (Priority: P1)

A driver author or CI pipeline loads an application driver from a git repository. Each load resolves a commit identifier from the repository at the loaded ref. Two loads of the same `version` string at different commits become two distinct application driver version rows, identified by their commit identifier.

**Why this priority**: same observable value as Story 1 for users who source drivers from git rather than local disk. Git is a primary distribution channel for drivers; without this story the provenance feature is half-shipped.

**Independent Test**: load a driver from a git repository at a known commit, then load again after a new commit lands on the same branch under the same `version` string, and observe two application driver version rows with the same `version` and different commit identifiers. Verifiable by inspecting the GraphQL surface — no UI flow required for the core observation.

**Acceptance Scenarios**:

1. **Given** an application driver loaded from `repo@branch` at commit `abc123…` with `version: "1.2.3"`, **When** the same load is repeated after a new commit `def456…` is pushed to that branch, **Then** a new application driver version row exists with the same `version` and `source_commit_sha = def456…`; the `abc123…` row is intact.
2. **Given** an application driver loaded from a git repository at commit C, **When** the same `repo@branch@C` load is repeated, **Then** no new row is created (idempotent).

---

### User Story 3 — Cascade crash on local reload is gone (Priority: P1)

The original `IntegrityError` on local reload is the symptom that prompted the issue. Even though the new content-hash semantics mean reload never deletes a row anymore, the underlying ORM cascade misconfiguration is fixed independently so that any future operation that deletes an application driver version row (manual cleanup, future prune command) succeeds cleanly.

**Why this priority**: this is the bug-fix portion of the work and shares a code path with the new feature. Shipping the feature without the cascade fix would leave a known latent bug in a code path the feature relies on indirectly.

**Independent Test**: in a unit test, create an application driver version row with child `Action` and `ComponentConfig` rows, delete the parent via the repository, and observe that the delete completes without `IntegrityError`, that the children are deleted by ORM cascade, and that no orphan rows remain in the database.

**Acceptance Scenarios**:

1. **Given** an application driver version row with one or more `Action` rows and one or more `ComponentConfig` rows referencing it, **When** the application driver version row is deleted, **Then** the operation completes without error and the `Action` and `ComponentConfig` rows are deleted as part of the cascade.

---

### User Story 4 — UI/CLI users can distinguish multiple rows with the same `version` (Priority: P2)

When two or more application driver version rows share the same `version` string, the user-visible identifier on lists and deployment-detail surfaces shows the short fingerprint suffix so users can tell them apart visually. Detail pages expose the full fingerprint with a copy affordance.

**Why this priority**: without this story the feature's data model is correct but its surfaces are ambiguous. Users would see "two rows labelled `1.2.3`" with no way to distinguish them at a glance. Strictly speaking this could be deferred a release, hence P2 rather than P1, but shipping the data model without surface support is awkward.

**Independent Test**: with two application driver version rows of the same `version` and different fingerprints present in the database, open the driver list in the frontend (or run `styrminctl driver list`) and observe each row labelled `<version>@<short>` where `<short>` is the first 7 chars of its `content_hash` or `source_commit_sha`. Open a driver detail page and observe the full fingerprint value rendered with a copy button.

**Acceptance Scenarios**:

1. **Given** two application driver version rows for the same driver with `version: "1.2.3"` and distinct fingerprints, **When** the user opens the driver list in the frontend, **Then** each row is labelled `1.2.3@<short>` where `<short>` is the first 7 chars of the populated fingerprint.
2. **Given** a deployment that references a specific application driver version row, **When** the user opens the deployment detail page, **Then** the driver-version reference is rendered as `<version>@<short>`.
3. **Given** the CLI `driver list` command is run against a workspace containing multiple rows with the same `version`, **Then** the rendered output includes the short fingerprint suffix for every row.
4. **Given** a user opens an application driver version detail surface, **Then** the full `content_hash` (64 chars) or `source_commit_sha` (40 chars) is visible verbatim with a copy affordance on web; the CLI exposes the full value via a `--full` flag or in default detail output.

---

### Edge Cases

- **Identical content at different `source_path`s (local)**: two distinct on-disk locations produce identical hashes. The system MUST treat them as distinct rows because `source_path` is part of identity. (Covered by Story 1 Scenario 3.)
- **Identical commit reachable from two branches (git)**: same commit on two branches MUST produce distinct rows because `source_branch` is part of identity.
- **`actions.py` exists on disk but `spec.actions` is empty**: the file is not consumed by the loader, so it MUST NOT contribute to the content hash. Editing this orphan file MUST NOT produce a new application driver version row.
- **`actions.py` is required (because `spec.actions` is non-empty) but missing**: the existing loader-level validation raises a driver-loading error before any hash is computed. The hash computation MUST NOT be reached in this failure mode.
- **Concurrent loads of the same content**: two parallel load operations resolving the same fingerprint MUST converge on a single row — either both observe the existing row, or one inserts and the other observes the inserted row via the upsert path. The system MUST NOT produce duplicate rows for the same identity.
- **Whitespace-only or comment-only edits to a hashed file**: MUST produce a different content hash and therefore a new row, because hashing operates on raw bytes (no YAML/Python canonicalisation).
- **Adding or editing files in the driver directory that the loader does not consume (`README.md`, screenshots, IDE config)**: MUST NOT produce a new row, because they do not contribute to the hash.
- **Source type other than `local` or `git`**: not present today. If a new source type is introduced later, it MUST define its own fingerprint column or extend the discriminator rule explicitly; the system MUST NOT silently fall back to NULL.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST add ORM cascade-delete-orphan behaviour to the application driver version's parent relationship with its `Action` rows and its `ComponentConfig` rows, so that deleting an application driver version row deletes its action and component-config children atomically without integrity-constraint errors.
- **FR-002**: The system MUST add two nullable provenance columns to the application driver version record — `content_hash` (intended to hold a SHA-256 hex string) and `source_commit_sha` (intended to hold a git commit SHA). Exactly one of the two MUST be non-null on any newly created row; the discriminator MUST be the row's existing `source_type` value (`"local"` populates `content_hash`, `"git"` populates `source_commit_sha`).
- **FR-003**: For drivers loaded from a local directory (`source_type = "local"`), the system MUST compute the row's `content_hash` at load time as a SHA-256 hex string over a deterministic, length-framed concatenation of exactly three files, in fixed order: (1) the driver specification file (`driver.styrmin.yml`), (2) the values template file, (3) the action source file (`actions.py`), included only when the driver's `spec.actions` block is non-empty. The hash MUST operate on raw byte content; the system MUST NOT canonicalise YAML or otherwise normalise the bytes before hashing. No other file in the driver directory MUST contribute to the hash.
- **FR-004**: For drivers loaded from a git repository (`source_type = "git"`), the system MUST record the resolved git commit SHA returned by the git driver provider on the row's `source_commit_sha` field at load time. No additional cryptographic hash MUST be computed for git-sourced rows in v1.
- **FR-005**: The system MUST use the tuple `(application_driver_id, source_type, source_repository, source_branch, source_path, version, <provenance fingerprint>)` as the load-time upsert lookup key, where `<provenance fingerprint>` is `content_hash` when `source_type = "local"` and `source_commit_sha` when `source_type = "git"`. When a row with the exact key exists, the load MUST be a no-op (no new row, no error, no mutation of the existing row). When no exact match exists, the load MUST create a new application driver version row alongside any existing rows that share the prefix of the key — the system MUST NOT delete any existing row as part of the load.
- **FR-006**: The system MUST remove the existing in-place delete-and-replace behaviour from the local-directory load path so that a same-`version` reload no longer destroys provenance for any prior deployment.
- **FR-007**: The system MUST expose `content_hash` and `source_commit_sha` as read-only fields on the GraphQL surface for the application driver version type, so that frontend, SDK, and CLI clients can read the provenance fingerprint for any row.
- **FR-008**: User-visible surfaces that name an application driver version (the frontend driver list view, the frontend deployment detail view, the CLI `driver list` output, the CLI `deployment` detail output, and any SDK formatter that returns a human-facing label) MUST render the version label as `<version>@<short>` where `<short>` is the first 7 characters of the populated provenance fingerprint. The suffix MUST be shown unconditionally — including when only one row exists for that `version` string — to keep labels stable when a second row appears later. Detail surfaces MUST also expose the full provenance fingerprint verbatim (full SHA-256 hex or full git commit SHA) with a copy affordance on web and accessibly via the CLI default detail output.
- **FR-009**: Users MUST be able to reload a local application driver repeatedly — with no content changes, or with arbitrary content changes — without encountering an `IntegrityError` or any other system error originating from the load path itself. Validation errors raised by the driver loader for malformed drivers are out of scope of this requirement.

### Key Entities

- **Application driver version** (existing, modified): the per-load record of an application driver. After this feature, its identity widens from `(application_driver_id, source_path, version)` to include a provenance fingerprint. Gains two new attributes: `content_hash` (for `source_type = "local"`) and `source_commit_sha` (for `source_type = "git"`). Exactly one is populated per row.
- **Provenance fingerprint** (new concept, no new entity): the content-addressable identifier that distinguishes two application driver version rows that share the same `version` string but were produced from different content (local files) or different commits (git). Stored in one of two columns on the application driver version record; surfaced as a single value at the GraphQL and display layers.
- **Action**, **Component config** (existing, modified relationship): the ORM relationship from the application driver version to these child rows MUST cascade delete-orphan so the parent row can be deleted cleanly by future operations.
- No new entities are introduced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A driver author can perform a sequence of 100 mixed reloads of the same local application driver — combining no-op reloads with arbitrary content edits — without observing any system error originating from the load path. The resulting application driver version row count for that driver equals the number of distinct content snapshots that were loaded across the sequence.
- **SC-002**: For any application driver version row referenced by any deployment or instance at any point in time, the same row UUID continues to be referenced by that deployment or instance for the lifetime of those records. No reload operation MUST mutate, replace, or delete an application driver version row that is referenced by an existing deployment or instance.
- **SC-003**: When a user reloads a local application driver with no file changes, the operation completes and no new application driver version row is created for that load (idempotency at the platform level, observable by counting rows before and after).
- **SC-004**: When a user reloads a local application driver after any edit — including a whitespace-only or comment-only edit — to any of the three files that contribute to the content hash, a new application driver version row is created (drift detection observable by counting rows). When the user edits any file in the driver directory that does not contribute to the hash, no new row is created.
- **SC-005**: Every user-facing surface that names an application driver version — frontend driver list, frontend deployment detail, CLI `driver list` output, CLI deployment detail output — includes the short provenance fingerprint suffix so that two rows with the same `version` are visually distinguishable at a glance, without the user having to open a detail view.
- **SC-006**: For an application driver loaded from a git repository, reloading the same `repo@branch` after a new commit lands creates a new application driver version row with the new commit identifier and leaves the prior row intact, observable by querying the GraphQL surface.

## Assumptions

- Styrmin is not yet deployed in any production environment. There are no pre-existing application driver version rows that lack a provenance fingerprint. Schema additions reach existing development databases via the standard `metadata.create_all()` path on backend restart; no migration script is required for the columns to materialise.
- The existing git driver provider already resolves and exposes the commit SHA of the ref it loaded; this feature consumes that value without altering the provider's contract.
- The frontend driver-detail and driver-list views, the deployment-detail view, and the CLI `driver` and `deployment` command groups are the only user-facing surfaces that today render an application driver version label. Any future surface added before this feature ships will adopt the same `<version>@<short>` rendering convention.
- Application driver version rows accumulate without bound under this feature. The volume is operationally acceptable at the project's current and near-term scale (rows are a few kilobytes each). A future admin-driven prune capability is filed as a follow-up and is out of scope here.
- The driver loader's set of consumed files is fixed at three: the driver specification file, the values template, and the optional `actions.py`. If the loader is extended in the future to read additional driver source files (for example, a multi-file `actions/` directory), the canonical input set for the content hash will need to be extended in lockstep; doing so is out of scope for v1.
- Concurrent reload of the same driver content from two clients at once is rare in practice and the database's existing transactional guarantees (combined with the upsert path's lookup-then-insert pattern) are sufficient to ensure no duplicate rows for the same identity. A dedicated unique constraint covering the fingerprint may be added during implementation if the planner determines one is warranted; this is a planning decision, not a specification requirement.
- The CONTEXT.md glossary entry for **Provenance fingerprint** was added during idea grilling and is treated as authoritative for vocabulary across this spec.
- The follow-up admin-driven `driver prune` command (deleting unreferenced application driver version rows) is explicitly out of scope and is filed separately.
