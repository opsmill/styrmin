# GraphQL Contract Delta: Configurable Backup Retention TTL

**Feature**: 016-backup-retention-ttl | **Date**: 2026-08-03

The only externally visible contract changes. `schema.graphql`, SDK `_generated/`, and `frontend/src/generated/graphql.ts` are regenerated from these (never hand-edited): `uv run styrmin export graphql-schema schema.graphql` + `uv run invoke generate`.

## Output type additions

```graphql
type Backup {
  # ... existing fields unchanged ...
  ttl: String          # NEW, nullable — applied retention TTL (e.g. "2160h"); null for pre-existing backups
  expiresAt: DateTime  # NEW, nullable — Velero-reported expiration; null for pre-existing
                       # backups and for Failed/PartiallyFailed backups (no expiration reported)
}
```

Semantics:
- Read from `Backup.metadata_` JSON (`ttl`, `expires_at` keys) via `@strawberry.field` resolvers — same pattern as the existing `componentStatuses` field.
- Both nullable **forever** (not just transitionally): pre-existing rows never gain the keys (FR-009 — no retro-patching).
- `expiresAt` is authoritative from Velero (`status.expiration`), not computed as `createdOn + ttl` — clock/duration math stays in Velero (SC-005: no calendar math for users either).

## Input type additions

```graphql
input UpdateEnvironmentInput {
  # ... existing fields unchanged ...
  backupTtl: String    # NEW, optional — omitted/null = clear the environment-scope policy
                       # (full-replacement semantics, consistent with every other field on this input)
}

input DeploymentConfigInput {
  # ... existing fields unchanged ...
  backupTtl: String    # NEW, optional — flows to both `deploy` (create) and
                       # `updateDeployment` (UpdateDeploymentInput inherits this input)
}
```

Semantics:
- `UpdateEnvironmentInput` is full-replacement (spec 009-environment-update): an update that omits `backupTtl` clears a stored value, which is why the field MUST exist on the typed input (FR-005) — clients that round-trip the current config preserve it.
- Cluster **create** and environment **create** accept the key through the existing `config: JSON` argument (`{"backup_ttl": "720h"}`) — no schema change on those paths (ADR-029).
- Converters: the generic `_convert_value` handles the scalar; snake_case `backup_ttl` ↔ camelCase `backupTtl` via Strawberry's auto-casing.

## Error contract (no new codes)

Malformed `backupTtl` / `config.backup_ttl` on any surface returns the existing config-validation error shape:

```json
{
  "errors": [{
    "message": "... backup_ttl must be a positive Go duration using h/m/s units, e.g. \"720h\" ...",
    "extensions": { "code": "<existing Invalid*Context error code>" }
  }]
}
```

- The message MUST name `backup_ttl` and include a `720h`-style hint (FR-004).
- Rejected values (contract test matrix): `30d`, `0h`, `-24h`, `720`, `""`.
- No mutation side effects on rejection (stored config unchanged, no backup created).

## Operation document updates (clients)

| Document | Change |
|---|---|
| `python_sdk/src/styrmin_sdk/graphql/list_backups.graphql` | + `ttl expiresAt` |
| `python_sdk/src/styrmin_sdk/graphql/get_backup.graphql` | + `ttl expiresAt` |
| `python_sdk/src/styrmin_sdk/graphql/create_backup.graphql` | + `ttl expiresAt` |
| `frontend/src/graphql/list_backups.graphql` | + `ttl expiresAt` |

SDK resource facade (`resources/backups.py`) and CLI consume the regenerated Pydantic models; no hand-written SDK code.

## Propagation test obligations (Constitution §V — blocking)

1. `UpdateEnvironmentInput.backupTtl` → `Environment.config["backup_ttl"]` round-trip (set, update-with, update-without ⇒ cleared). The schema-walking guard `test_update_environment_input_covers_every_environment_config_field` fails until the field exists.
2. `DeploymentConfigInput.backupTtl` → `Deployment.config["backup_ttl"]` via **both** `deploy` and `updateDeployment`.
3. `Backup.ttl` ← `metadata_["ttl"]` projection (value and absent-key → null).
4. `Backup.expiresAt` ← `metadata_["expires_at"]` projection (ISO string → DateTime; absent → null).
