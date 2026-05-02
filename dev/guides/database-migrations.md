# Database Migrations with Alembic

Styrmin uses [Alembic](https://alembic.sqlalchemy.org/) for versioned database schema management. Migrations are stored in `backend/styrmin_backend/db/migrations/versions/`.

## CLI Commands

All migration commands accept an optional `--config-file` parameter.

| Command | Description |
|---------|-------------|
| `styrmin db init` | Initialize a new database (applies all migrations) |
| `styrmin db migrate` | Apply all pending migrations |
| `styrmin db downgrade` | Rollback the most recent migration |
| `styrmin db status` | Show current migration version |
| `styrmin db stamp` | Mark database at latest version without running migrations |

## Creating a New Migration

When you modify models in `backend/styrmin_backend/db/models.py`:

1. Make your model changes (add columns, modify types, add indexes, etc.)

2. Generate a migration from the `backend/` directory:

   ```bash
   cd backend
   PYTHONPATH=. uv run --project /path/to/repo alembic revision --autogenerate -m "describe your change"
   ```

3. Review the generated file in `backend/styrmin_backend/db/migrations/versions/`

4. Apply locally:

   ```bash
   styrmin db migrate
   ```

5. Commit the migration file with your model changes

## Multi-head resolution

If two parallel branches each landed a migration, the chain ends up with two
heads sharing a parent. Adding a third migration that points at one of them
leaves the other dangling — alembic detects this as multiple heads and the
DB will silently apply only one chain.

To check the current state:

```bash
cd backend
uv run --project .. alembic --config styrmin_backend/db/migrations/alembic.ini heads
```

(Or grep `down_revision` across `backend/styrmin_backend/db/migrations/versions/*.py` to spot two files sharing the same parent — that's the head split.)

When you need to add a migration on top of a multi-head state, write a **merge migration**: a single file whose `down_revision` is a tuple of both heads. Alembic recognises tuples and emits a `merge_revision` linking them. Example pattern:

```python
revision: str = "<your-rev>"
down_revision: Union[str, Sequence[str], None] = ("<head_a>", "<head_b>")
```

`b8c9d0e1f2a3_deployment_deletion.py` is a worked example: it merges the
`a7b8c9d0e1f2` (`add_restoring_deploymentstate`) and `a7b8c9d0e1f3`
(`add_component_name_to_pod_status`) heads while also adding new schema.

Do **not** "resolve" by branching from one head and ignoring the other — the
ignored migration's changes will not be applied on a fresh database.

## Transitioning an Existing Database

If you have a database created with the old `create_all()` method:

```bash
styrmin db stamp
```

This records the database as being at the latest migration version without re-running migrations.

## Configuration

Migrations use the same database configuration as the application via `STYRMIN_DB_*` environment variables. The `alembic.ini` file at `backend/` contains logging configuration but the database URL is set programmatically from application config.

## Architecture

- **env.py**: Configures Alembic for async operation using `asyncio.run()` and `connection.run_sync()` to bridge the async engine with Alembic's synchronous migration API.
- **render_as_batch=True**: Enabled unconditionally to support SQLite's limited `ALTER TABLE` capabilities. Harmless on PostgreSQL.
- **SQLModel.metadata**: Used as `target_metadata` for autogeneration, ensuring migrations stay in sync with model definitions.

## Testing

Unit tests mock the Alembic command layer. Repository tests continue to use in-memory SQLite with `create_all()`/`drop_all()` for speed and isolation — they do not run through migrations.
