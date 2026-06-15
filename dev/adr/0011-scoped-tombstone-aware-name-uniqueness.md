# ADR-011: Per-environment tombstone-aware name uniqueness via partial unique index

**Status**: Accepted
**Date**: 2026-05-02
**Source**: specs/archive/008-deployment-deletion/spec.md (FR-034, FR-035) + follow-on commit f14dcaa

## Context

The original schema declared `Deployment.name` as globally unique (`Field(unique=True)`). Two regressions surfaced after spec 008 introduced soft-delete tombstoning:

1. **Cross-environment collision**: An operator who created `ansible` in environment A could not create another `ansible` in environment B — the name was held globally, even though the two deployments would never coexist on the same cluster namespace prefix.
2. **Tombstone-blocks-reuse**: An operator who deleted `ansible` (soft-delete leaves the row in the table with `deleted_at` set) could not recreate `ansible` in the same environment — the tombstoned row was still occupying the name slot in the global unique index.

Both behaviours violate the user-visible contract operators expect: name uniqueness should be scoped to the environment the deployment lives in, and a retired deployment should free its name for reuse.

A pure service-layer check ("query for an existing row, raise if found") is not sufficient on its own — concurrent `deploy` calls would race past the check. The DB needs to be the authoritative gate.

## Decision

Replace the global unique constraint with a **partial unique index** on `(environment_id, name) WHERE deleted_at IS NULL`. Name `uq_deployment_env_name_active`. Both Postgres and SQLite support partial indexes, so the same index works in production and in the unit-test in-memory DB.

Index expressed in SQLModel:

```python
__table_args__ = (
    Index(
        "uq_deployment_env_name_active",
        "environment_id",
        "name",
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
        sqlite_where=text("deleted_at IS NULL"),
    ),
)
```

Service-layer name-conflict checks (`uow.deployments.get_by_name(name, environment_id)`) become best-effort pre-flights: they exclude tombstoned rows by default and produce a typed `DeploymentNameConflictError` with a friendly "in this environment" message when they find a collision. The DB-level partial index is the authoritative race-free guard — service-layer code wraps the eventual commit and maps `IntegrityError` to the same typed error.

The migration that replaces the constraint includes a defensive pre-flight check: it refuses to run if any pair of currently-active deployments already collide on `(env, name)`. Under the prior global constraint this should be impossible, but the check guarantees a corrupt input cannot silently produce a corrupt index.

## Consequences

- **Easier**: operators can reuse names freely across environments and after deletion. The system behaves the way operators expect.
- **Easier**: same name in different environments stops being a foot-gun — for example, every environment can have its own `internal-ingress-controller-N` without collisions.
- **Easier**: race-free uniqueness even under concurrent calls. Two clients trying to deploy `ansible` simultaneously in the same env both pass the service-layer check; only one survives the DB commit. The IntegrityError → typed-error mapping ensures both callers see consistent error semantics.
- **Convention to replicate**: any future soft-deleted resource that needs uniqueness should follow this pattern (partial unique index predicated on the tombstone column, not a plain `UniqueConstraint`). Captured in `dev/guidelines/backend/python.md` § "Soft-delete and partial unique indexes".
- **Harder**: every repository method that resolves a name needs an `environment_id` parameter and a tombstone filter. Existing callers (`update_deployment` rename, `deploy_application` create, internal-ingress controller, scheduling/validator affinity references) had to be updated. The new repository signature is mandatory rather than optional, so future call sites cannot accidentally fall back to global lookup.

## Alternatives Considered

- **Drop the constraint entirely, rely solely on service-layer checks**: Loses the race-free guarantee. Two concurrent `deploy(driver=..., name="ansible")` calls would both pass their pre-flight check and both succeed. Rejected.
- **Add a CHECK constraint** that compares `(env_id, name)` only when `deleted_at IS NULL`: Postgres CHECK constraints can't reference other rows in the table. Wrong tool.
- **Rename tombstoned rows on delete** (e.g., append `-deleted-{timestamp}`): Mutates the audit trail — the deployment's name is part of its identity in the timeline and any external system that scraped it. Rejected.
- **Separate "deleted_deployments" archive table**: Forces every read query to UNION across two tables, or duplicates the relationship graph (Tasks, Backups, etc.). Adds complexity for no observable benefit over the partial-index approach.
- **Hard-delete on `deleteDeployment`**: Would moot the problem but contradicts ADR-008 (soft-delete preserves audit + backups).
