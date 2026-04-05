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
