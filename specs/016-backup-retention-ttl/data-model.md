# Data Model: Configurable Backup Retention TTL

**Feature**: 016-backup-retention-ttl | **Date**: 2026-08-03

No database schema change. All persistence rides existing JSON columns.

## Entities

### BaseConfigSection (extended — context model, not a table)

`backend/styrmin_backend/context/models/config.py`

| Field | Type | Default | Validation | Notes |
|---|---|---|---|---|
| `backup_ttl` | `str \| None` | `None` | Strictly positive Go-duration string, `h`/`m`/`s` units only; regex `^(\d+(\.\d+)?(h|m|s))+$` + strict-positivity (reject all-zero). Error names the field and hints `"720h"`-style syntax. | Inherited by `ClusterConfig`, `EnvironmentConfig`, `DeploymentConfig` (and therefore `ResolvedConfig`). `None` = "no policy at this scope". `extra="forbid"` already rejects misspellings. |

**Accepted examples**: `720h`, `2160h`, `8760h`, `1h`, `90m`, `3600s`, `1h30m`, `1.5h`
**Rejected examples**: `30d`, `0h`, `-24h`, `720`, `""`, `0h0m0s`, `24H`

Stored where each scope's config is already stored: `Cluster.config`, `Environment.config`, `Deployment.config` (JSON columns) — no new columns, no Alembic revision.

### Backup (extended — existing table, JSON metadata only)

`backend/styrmin_backend/db/models.py:504` — column `metadata` (attr `metadata_`), currently `{"timeout": <int>}`.

New keys (all optional; absent on pre-existing backups):

| Key | Type (JSON) | Written when | Written by | Semantics |
|---|---|---|---|---|
| `ttl` | string | At TTL resolution, before the Velero object is built | `execute_backup_workflow` via `update_backup_status(metadata_updates=...)` | The applied retention (audit record, FR-006). Immutable once written. |
| `ttl_source` | string | Same moment as `ttl` | Same | Provenance: `"deployment"` \| `"environment"` \| `"cluster"` \| `"default"`. |
| `expires_at` | string (ISO 8601) | On workflow completion, from Velero `status.expiration` | Same | Absent for Failed/PartiallyFailed backups (Velero reports no expiration) and for pre-existing backups. |

Merge semantics: `metadata_updates` merges into the existing dict (preserves `timeout`); never replaces the column value.

### TTL resolution (pure function, not an entity)

`backend/styrmin_backend/services/backup/ttl.py` (new module — single home for the rule):

```
DEFAULT_BACKUP_TTL = "720h"

resolve_backup_ttl(
    deployment_config: dict | None,
    environment_config: dict | None,
    cluster_config: dict | None,
) -> tuple[str, str]   # (ttl, source_scope)
```

Precedence (deepest wins): deployment → environment → cluster → `DEFAULT_BACKUP_TTL` (`source_scope="default"`). A scope contributes only when its config contains a non-null `backup_ttl`. The workflow logs `resolved backup TTL <ttl> from <source_scope> scope`.

### Unchanged entities (explicit)

- **Instance / ApplicationInstance**: unchanged shape; a `backup_ttl` config change propagates through the standard config-update flow (new instance version) like every other config field.
- **BackupSchedule**: untouched — `retention_count` is a count-based, currently unenforced concept, semantically distinct from the TTL.
- **Cluster / Environment capabilities JSON**: untouched — derived and recomputed (ADR-025/026/027); a policy stored there would be overwritten.
- **Velero Backup CRD**: `spec.ttl` already rendered unconditionally by `VeleroBackup.render()`; only the *source* of the value changes (explicit required input instead of a builder default).

## State transitions

None new. The backup lifecycle (Pending → InProgress → Completed/Failed/PartiallyFailed) is unchanged; the feature only attaches metadata at two existing transition points:

1. **Pre-build** (workflow start): `ttl` + `ttl_source` recorded.
2. **Completion**: `expires_at` recorded iff Velero reported `status.expiration`.

## Validation rules (FR-004)

| Surface | Path | Mechanism |
|---|---|---|
| Cluster create (`config: JSON`) | `services/clusters.py` → `validate_cluster_config` | Pydantic validator on `BaseConfigSection` → `InvalidClusterContextError` |
| Environment create (`config: JSON`) | `services/environments.py` → `validate_environment_config` | → `InvalidEnvironmentContextError` |
| Environment update (`UpdateEnvironmentInput.backup_ttl`) | converter → `validate_environment_config` | same |
| Deploy (`DeploymentConfigInput.backup_ttl`) | converter → `validate_deployment_config` | → `InvalidDeploymentContextError` |
| Deployment update (`UpdateDeploymentInput` inherits `DeploymentConfigInput`) | converter → `validate_deployment_config` | same |

All five surfaces reject before any write (SC-003: nothing malformed reaches the backup system asynchronously; stored config unchanged on rejection).
