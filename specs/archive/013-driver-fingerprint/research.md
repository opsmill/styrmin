# Research: Driver Reload Identity — Provenance Fingerprint

**Phase**: 0 (Outline & Research)
**Status**: All `NEEDS CLARIFICATION` resolved during idea grilling. Below documents the decisions and the alternatives weighed.

## Decisions

### D-001 — Schema shape: two explicit columns

**Decision**: Add two nullable columns to `ApplicationDriverVersion` — `content_hash: str | None` (intended SHA-256 hex, 64 chars) and `source_commit_sha: str | None` (intended 40-char git SHA). Exactly one is non-null per row; the discriminator is `source_type`.

**Rationale**:
- `source_commit_sha` slots naturally next to the other `source_*` columns and matches the conceptual model (commit SHA is a property of the source, not a hash of the loaded bytes).
- `content_hash` accurately names what it is for `source_type = "local"`: a hash of the resolved driver bytes.
- Distinct names produce distinct GraphQL fields, letting the frontend render a "git link" affordance only when `source_commit_sha` is populated and a copy-hex affordance for `content_hash`.

**Alternatives considered**:
- Single polymorphic `content_fingerprint` column — rejected. Loses the type-of-fingerprint signal at every query site; misleads on the git side ("`content_hash` of a git commit?").
- Column + discriminator (`content_fingerprint`, `content_fingerprint_kind`) — rejected. Two columns either way, and the discriminator duplicates information already on `source_type`.

### D-002 — Local content hash canonical input

**Decision**: Hash the raw bytes of exactly three files in fixed order with length-framed concatenation:

```python
def canonical_bytes(driver_spec: bytes, values_template: bytes, actions_py: bytes | None) -> bytes:
    parts = [(b"driver.styrmin.yml", driver_spec),
             (b"values_template",    values_template)]
    if actions_py is not None:
        parts.append((b"actions.py", actions_py))
    out = bytearray()
    for name, body in parts:
        out += name + b"\x00"
        out += len(body).to_bytes(8, "big")
        out += body
    return bytes(out)

content_hash = hashlib.sha256(canonical_bytes(...)).hexdigest()
```

**Rationale**:
- Mirrors exactly what the loader (`services/driver/loaders.py:54-94`) actually reads. Any file the loader doesn't read (`README.md`, screenshots) MUST NOT contribute to identity — otherwise editing the README creates a new row, surprising the user.
- Length-prefix framing prevents the "boundary collision" class of bugs (concatenating raw bytes lets two distinct triples hash the same).
- Hashing raw bytes (no YAML canonicalisation) makes whitespace and comment edits visible, which the issue's acceptance criteria explicitly require.
- `actions.py` is included **iff** `spec.actions` is non-empty, matching loader behaviour. Drivers without actions don't need or contain `actions.py`.

**Alternatives considered**:
- Hash the parsed `ApplicationDriver` Pydantic model JSON — rejected. Canonicalises away whitespace and comments; would say "no change" when the YAML's comment header is edited. Violates the spec's testability requirement.
- Hash a tar of the directory — rejected. Includes irrelevant files; non-deterministic across filesystems (mtime, ownership).
- Future multi-file action support (`actions/*.py`) — out of scope; revisit when the loader is extended.

### D-003 — Git provenance fingerprint = resolved commit SHA

**Decision**: For `source_type = "git"`, record the SHA reported by the git provider for the loaded ref. No additional cryptographic hash is computed for git-sourced rows.

**Rationale**:
- Git commits are already content-addressable. Re-hashing would add cost without value.
- A single canonical fingerprint type per source aligns with the dual-column schema (D-001).

**Implementation gap discovered during research**: the current `GitDriverProvider` (`services/driver/provider.py:35-59`) uses `dulwich.porcelain.clone()` and yields the temp directory, but does NOT today expose the resolved commit SHA back to the caller. The plan adds: after cloning, read `HEAD` from the cloned `.git/` (via `dulwich.repo.Repo(temp).head().decode()`) and surface it on `LocalSource`/`GitSource` (or a new field on `ApplicationDriver`). This is a small, local addition; no new dependency.

### D-004 — Upsert lookup key widens; no delete

**Decision**: The local-load upsert (`services/applications.py:309-316`) is rewritten as:

```python
existing = await uow.application_driver_versions.get_by_identity(
    application_driver_id=...,
    source_type="local",
    source_path=path,
    version=...,
    content_hash=computed_hash,
)
if existing is not None:
    return existing  # idempotent no-op
# else: fall through to load_application_driver_from_object → create new row
```

The git path gets the analogous code (`get_by_identity(..., source_type="git", source_repository=..., source_branch=..., version=..., source_commit_sha=resolved_sha)`).

The existing `if existing is not None: await uow.application_driver_versions.delete(existing)` branch is **removed entirely**. After this change no load operation deletes any application driver version row.

**Rationale**:
- Removing the delete branch is what makes the feature non-destructive — old deployments keep pointing at their original row.
- A single repository method (`get_by_identity`) parameterised by `source_type` is cleaner than two parallel methods.
- The lookup uses all identity columns plus the fingerprint; the database's existing transactional guarantees plus this exact-match query make the upsert race-safe enough for v1. A unique index covering `(application_driver_id, source_type, source_repository, source_branch, source_path, version, content_hash, source_commit_sha)` may be added if the planner deems it necessary; deferred to implementation discretion.

**Alternatives considered**:
- Keep two methods (`get_by_local_identity`, `get_by_git_identity`) — rejected. Same logic, just split.
- Hash-as-primary-key — rejected. UUID PK is unchanged; fingerprint is a content-addressable secondary identity.

### D-005 — Cascade-delete-orphan on `actions` and `component_configs`

**Decision**: Add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` to `ApplicationDriverVersion.actions` (`db/models.py:271`) and `ApplicationDriverVersion.component_configs` (`db/models.py:264`).

**Rationale**:
- Fixes the documented IntegrityError on local reload pre-content-hash and on any future delete operation.
- Mirrors the working pattern on `Deployment.components` at `db/models.py:360` (referenced by the issue).
- The `deployments` relationship at `db/models.py:273` is **intentionally NOT cascaded** — deployments outlive their driver version (the deployment's lifetime is the application's lifetime, not the driver's). This is confirmed by the existing `ApplicationInstance.application_driver_version_id` FK that preserves provenance across instance regeneration.

**Alternatives considered**:
- Switch the `Action.application_driver_version_id` FK to nullable — rejected. The action only makes sense inside a driver version; nullable FK would model a state that should never exist.
- Move delete logic to the service layer — rejected. ORM cascade is the standard pattern in this codebase (already used by `Deployment.components`).

### D-006 — Display rule: always show `<version>@<short>`

**Decision**: Every user-visible surface that names a driver version renders the label as `<version>@<short>` where `<short>` is the first 7 chars of the populated fingerprint. Shown unconditionally — including when only one row exists for the version. Detail views show the full fingerprint with a copy affordance on web.

**Rationale**:
- Stable labels: showing the suffix only "when ambiguous" creates UI flicker (`1.2.3` → `1.2.3@a1b2c3d`) when a second row appears.
- 7 chars matches git's convention (`git log --oneline`) and is recognisable to developers.
- The full hex is exposed for users who need to copy/paste the exact value (e.g. into a chat message or audit log).

**Alternatives considered**:
- Sequence numbering (`1.2.3 #2`) — rejected. Recomputed dynamically across siblings; changes if rows are later pruned; not stable.
- Show suffix only when ambiguous — rejected (above).
- Truncate longer (e.g. 12 chars) — rejected. 7 chars is the cross-tool norm; longer wastes horizontal space in tables.

### D-007 — No automatic GC; cascade enables future prune

**Decision**: v1 ships without any automatic garbage collection of unreferenced `ApplicationDriverVersion` rows. The cascade-delete-orphan from D-005 ensures a future admin-driven `styrminctl driver prune` can delete unreferenced rows cleanly. The prune command is filed as a follow-up issue, out of scope here.

**Rationale**:
- Rows are small (a few KB); accumulating thousands is operationally negligible.
- A correct "safe to delete" rule requires checking both `Deployment` and `ApplicationInstance` FKs and accounting for tombstoned deployments. Getting this wrong corrupts the timeline; the right place for that logic is an explicit admin operation, not a background job.

### D-008 — No backfill, no migration script

**Decision**: Styrmin is not yet deployed. Existing development databases that already have `ApplicationDriverVersion` rows will get the new columns via `metadata.create_all()` on backend restart, leaving legacy rows with NULL fingerprints. Developers can drop and recreate, or accept a one-time duplicate row on their first reload. No backfill code path; no NULL-fingerprint display fallback.

**Rationale**:
- Project status (idea brief decision, owner-confirmed during grilling): no production deployments exist. Adding backfill machinery for a non-existent scenario is over-engineering per project guidelines.
- New columns are nullable, so adding them is non-breaking even on dev DBs.

## Open questions

None. All clarifications resolved during grilling and confirmed before this phase began.
