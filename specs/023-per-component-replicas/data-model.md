# Data Model: Per-Component Replica Counts

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

No table, column or Alembic revision changes. Every new value lives in an existing JSON column, and every reader defaults a missing key.

## Stored values

### `ComponentConfigBlock.replicas` (deployment config, new field)

Location: [`context/models/config.py`](../../backend/styrmin_backend/context/models/config.py), stored in `Deployment.config` (JSON) under `components.<name>.replicas`.

| Field | Type | Default | Rule |
|-------|------|---------|------|
| `replicas` | `int \| None` | `None` | An integer from 1 to 2147483647 (Kubernetes `int32`). `bool`, strings, floats and values out of range raise `INVALID_REPLICA_COUNT` before type conversion. `None` means no override. |

Write-time rules against the driver version the deployment is bound to after the write (research D-005, D-006):

- An added or changed override on a component that the driver version does not declare raises `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`. An unchanged stored one is kept (orphaned).
- An override greater than 1 on a component that the driver version marks `singleton: true` raises `SINGLETON_REPLICA_OVERRIDE`, changed or not.

### Driver component declaration (driver specification file, new typed fields)

Location: [`ArbitrarySectionModel`](../../backend/styrmin_backend/services/driver/models/resources/driver.py) (`spec.components.<name>`), stored in `ApplicationDriverVersion.components` (JSON) and `ComponentConfig.config` (JSON).

| Field | Type | Default | Rule |
|-------|------|---------|------|
| `replicas` | `StrictInt \| None` | `None` | 1 to 2147483647. |
| `singleton` | `StrictBool` | `false` | `singleton: true` with `replicas` greater than 1 fails the driver load (`DriverLoadingError`, field path `spec.components.<name>`). |

Driver versions loaded before the change have neither key; they read as `None` and `false`. The model serialises `replicas` only when set and `singleton` only when `true`, so a declaration that uses neither key dumps to the same dict as before the change (research D-002).

### Parameter values (existing, new rule on driver version change)

`Deployment.parameters` (JSON). No shape change. On `updateDeploymentVersion`, a key that the current driver version declares and the target version does not is dropped when its value equals the current version's default (same type and value), and otherwise raises `RETIRED_PARAMETER_VALUE` (research D-007).

### Stopped state (existing, unchanged)

`Component.enabled` (database column). A stopped component gets `spec.replicas: 0` whatever its override is; its override stays stored.

## Context (agent and operator input)

| Model | Change |
|-------|--------|
| `ComponentContext` ([`context/models/components.py`](../../backend/styrmin_backend/context/models/components.py)) | New field `replica_override: int \| None = None`, filled by `resolve_global_context` from `DeploymentConfig.components[<name>].replicas`. `config` (the driver declaration) already carries `replicas` and `singleton` once `ArbitrarySectionModel` types them. |
| `ComponentInput` ([`context/models/input.py`](../../backend/styrmin_backend/context/models/input.py)) | No change: the override is read from the deployment config, like the image override. |

Orphaned overrides are not in `ComponentsContext` (it holds declared components only); they surface on read only, as for image overrides.

## Derived values (not stored)

### `ReplicaSource`

`StrEnum` in [`services/replicas/resolver.py`](../../backend/styrmin_backend/services/replicas/resolver.py): `OVERRIDE`, `DRIVER_DEFAULT`, `CHART`. Exposed in GraphQL as the `ReplicaSource` enum.

### `ResolvedReplicas`

Frozen dataclass returned by `resolve_replicas(...)`.

| Field | Type | Meaning |
|-------|------|---------|
| `count` | `int \| None` | The count Styrmin applies when the component runs. `None` only when `source` is `CHART`. |
| `source` | `ReplicaSource` | Where `count` comes from. |
| `override_applies` | `bool` | True when a stored override is the source. False when there is no override or the stored one does not apply. |

Order of precedence (FR-002, FR-007):

| Stored override | Orphaned | Driver `replicas` | Driver `singleton` | `count` | `source` | `override_applies` |
|-----------------|----------|-------------------|--------------------|---------|----------|--------------------|
| `3` | no | any | `false` | 3 | `OVERRIDE` | true |
| `1` | no | any | `true` | 1 | `OVERRIDE` | true |
| `3` (cannot be written; defensive) | no | `None` or `1` | `true` | 1 | `DRIVER_DEFAULT` | false |
| `3` | yes | — | — | — (row reports the override only) | — | false |
| `None` | — | `2` | `false` | 2 | `DRIVER_DEFAULT` | false |
| `None` | — | `None` | `true` | 1 | `DRIVER_DEFAULT` | false |
| `None` | — | `1` | `true` | 1 | `DRIVER_DEFAULT` | false |
| `None` | — | `None` | `false` | `None` | `CHART` | false |

`replica_patch_count(resolved, enabled=False)` is `0`; with `enabled=True` it is `resolved.count` (`None` means no patch).

### `ComponentReplicas` (GraphQL read row)

One row per declared component plus one per orphaned override; see [contracts/graphql.md](contracts/graphql.md).

| Field | Source |
|-------|--------|
| `component` | Component name |
| `count` | `ResolvedReplicas.count`; `null` for an orphaned row |
| `source` | `ResolvedReplicas.source`; `CHART` for an orphaned row |
| `override` | The stored `ComponentConfigBlock.replicas`, applied or not |
| `singleton` | The bound driver version's `singleton` (false for an orphaned row) |
| `isOrphaned` | The bound driver version does not declare the component |
| `isApplicable` | False only when `override` is set and does not apply |

## State transitions

```text
                 set override N (N ≥ 1, not > 1 on a singleton)
  no override ─────────────────────────────────────────────▶ override N
  (driver default                                            (source OVERRIDE)
   or chart)    ◀───────────────────────────────────────────
                 clear override (null / omit)

  running ── stopComponents ──▶ stopped (patch 0, override kept)
  stopped ── startComponents ─▶ running (patch = resolved count, or none)

  override on component C ── driver version change, target drops C ──▶ orphaned (kept, not applied)
  override N > 1 on C ── driver version change, target marks C singleton ──▶ rejected unless the
                                                                            request lowers N to 1 or clears it
```
