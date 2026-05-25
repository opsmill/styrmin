# Data Model: Driver Reload Identity — Provenance Fingerprint

**Phase**: 1 (Design & Contracts)

## Modified entity: `ApplicationDriverVersion`

Location: `backend/styrmin_backend/db/models.py:243-275`

### New columns

| Column | Type | Nullability | Populated when | Notes |
|---|---|---|---|---|
| `content_hash` | `str` (64 hex chars) | nullable | `source_type = "local"` | SHA-256 hex over the canonical three-file byte concatenation (see Hash Input). |
| `source_commit_sha` | `str` (40 hex chars) | nullable | `source_type = "git"` | Resolved git commit SHA at the loaded ref. |

**Invariant**: exactly one of `content_hash` and `source_commit_sha` is non-null on any newly created row. Enforced at the service layer at load time (D-001 in research.md). A future DB-level CHECK constraint is acceptable but not required for v1.

### Modified relationships

| Relationship | Change | Why |
|---|---|---|
| `actions: list[Action]` | add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` | Fixes the IntegrityError documented in issue #262 and enables future prune. |
| `component_configs: list[ComponentConfig]` | add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` | Same bug class; latent because `Action` autoflush trips first today. |
| `deployments: list[Deployment]` | **unchanged — intentionally NOT cascaded** | Deployments outlive their driver version; their FK preserves provenance across instance regeneration. |

### Unchanged identity columns

`source_type`, `source_repository`, `source_branch`, `source_path`, `version` retain their current types and semantics. Identity widens *via the addition* of the fingerprint, not by replacement.

## New identity tuple

Effective identity for upsert lookup:

```
(application_driver_id,
 source_type,
 source_repository,
 source_branch,
 source_path,
 version,
 content_hash | source_commit_sha)        # whichever is populated for source_type
```

- Same tuple → row exists, load is idempotent.
- Tuple differs only in fingerprint → new row created alongside existing rows.
- Tuple differs in non-fingerprint columns → new row created (this is also the case today; the change only adds fingerprint to the join key).

## Hash input (canonical bytes for `content_hash`)

```python
SHA-256(
  b"driver.styrmin.yml\x00" + len_be8(driver_spec_bytes)   + driver_spec_bytes
+ b"values_template\x00"    + len_be8(values_template_bytes) + values_template_bytes
+ (b"actions.py\x00"        + len_be8(actions_py_bytes)     + actions_py_bytes
   if spec.actions else b"")
)
```

where `len_be8(x)` is `len(x).to_bytes(8, "big")`.

- `driver_spec_bytes`: raw bytes of `driver.styrmin.yml` as read from disk.
- `values_template_bytes`: raw bytes of the values template file declared in the directory map.
- `actions_py_bytes`: raw bytes of `actions.py` IF `driver_spec.spec.actions` is non-empty; otherwise the actions block is omitted from the hash entirely.

Files in the driver directory not listed above MUST NOT contribute. The hash is **purely a function of bytes** — no parsing, normalisation, or canonicalisation.

## State transitions

`ApplicationDriverVersion` rows have no state machine. The only mutations possible on any row are:

- **Create** (at load time, only when no row matches the identity tuple).
- **Delete** (only via a future admin prune; out of scope for this feature). The cascade kwargs ensure children are deleted atomically when this happens.

No `UPDATE` of identity columns is permitted after creation.

## Foreign-key references that hold the row alive

A row is unsafe to delete while any of these reference it:

- `Deployment.application_driver_version_id` (`db/models.py:369-374`)
- `ApplicationInstance.application_driver_version_id` (`db/models.py:441-443`)

Both references are preserved unchanged by this feature. The cascade kwargs added to `actions` and `component_configs` do NOT propagate up these FKs.

## Why no migration

Styrmin is not yet deployed in production (spec Assumption §1). New columns reach existing development databases via `metadata.create_all()` on backend restart. Legacy rows in dev DBs are NOT backfilled; developers either drop-and-recreate or accept one-time duplicate-row creation on their next reload.
