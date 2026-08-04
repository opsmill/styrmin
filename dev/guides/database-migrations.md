# Database Migrations with Alembic

Styrmin uses [Alembic](https://alembic.sqlalchemy.org/) for versioned database schema management. Migrations are stored in `backend/styrmin_backend/db/migrations/versions/`.

## CLI Commands

All migration commands accept an optional `--config-file` parameter.

| Command | Description |
|---------|-------------|
| `styrmin db init` | Initialize a new database (applies all migrations) |
| `styrmin db migrate` | Apply all pending migrations |
| `styrmin db downgrade [REVISION]` | Rollback to `REVISION` (default `-1`, one step back; `base` un-applies everything) |
| `styrmin db status` | Show current migration version |
| `styrmin db stamp` | Mark database at latest version without running migrations |

## Creating a New Migration

When you modify models in `backend/styrmin_backend/db/models.py`:

1. Make your model changes (add columns, modify types, add indexes, etc.)

2. Generate a migration. There is **no `alembic.ini`** in this repo and
   `styrmin db` exposes no autogenerate subcommand, so drive Alembic's
   programmatic API with the same `Config` that
   `backend/styrmin_backend/cli/db.py` builds:

   ```bash
   STYRMIN_DB_TYPE=postgres STYRMIN_DB_NAME=styrmin \
   uv run python -c '
   from alembic import command
   from styrmin_backend import config
   from styrmin_backend.cli.db import _get_alembic_config
   config.SETTINGS.initialize()
   command.revision(_get_alembic_config(), message="describe your change", autogenerate=True)
   '
   ```

   Autogenerate diffs `SQLModel.metadata` against a **live database already at
   head**, so point `STYRMIN_DB_*` at one before running it. An empty diff means
   no drift; a non-empty diff is the list of revisions you still owe.

3. Review the generated file in `backend/styrmin_backend/db/migrations/versions/`

4. Apply locally:

   ```bash
   styrmin db migrate
   ```

5. Commit the migration file with your model changes

## Multi-head resolution

If two parallel branches each landed a migration, the chain ends up with two
heads sharing a parent. Adding a third migration that points at one of them
leaves the other dangling. A multi-head chain is not a soft problem: `styrmin db
init` and `styrmin db migrate` both target `head` (singular) and fail outright
with `Multiple head revisions are present for given argument 'head'`.

To check the current state:

```bash
uv run python -c '
from alembic import command
from styrmin_backend.cli.db import _get_alembic_config
command.heads(_get_alembic_config(), verbose=True)
'
```

(Or grep `down_revision` across `backend/styrmin_backend/db/migrations/versions/*.py` to spot two files sharing the same parent — that's the head split.)

When you need to add a migration on top of a multi-head state, write a **merge migration**: a single file whose `down_revision` is a tuple of both heads. Alembic recognises tuples and emits a `merge_revision` linking them. Example pattern:

```python
revision: str = "<your-rev>"
down_revision: Union[str, Sequence[str], None] = ("<head_a>", "<head_b>")
```

`b8c9d0e1f2a3_deployment_deletion.py` and
`a8b9c0d1e2f3_add_driver_fingerprint_and_container_overrides.py` are worked
examples: each merges two heads while also adding new schema.

Do **not** "resolve" by branching from one head and ignoring the other — the
ignored migration's changes will not be applied on a fresh database.

`styrmin db downgrade` defaults to `-1`, which Alembic cannot resolve across a
merge point (`CommandError: Ambiguous walk`) — a merge revision has more than
one predecessor. Pass the target explicitly instead. Naming either parent
un-applies only the merge and restores both heads:

```bash
styrmin db downgrade <one_parent_revision>
```

`styrmin db downgrade base` un-applies the whole chain regardless of merges.

## Writing portable migrations

Every revision must apply on **both** backends: PostgreSQL (`asyncpg`) is
production, SQLite is the default dev backend. SQLite is the more permissive of
the two, so a revision that only ever ran there can still be broken.

- **Order `create_table` calls by dependency.** PostgreSQL rejects a
  `REFERENCES` clause naming a table that does not exist yet; SQLite accepts it.
  Autogenerate emits the correct order only when the foreign keys form a DAG —
  when they contain a cycle SQLAlchemy's topological sort gives up and falls
  back to alphabetical order, which is almost always wrong.
- **Break foreign-key cycles with a deferred `create_foreign_key`.** Create both
  tables first, omitting one side's foreign key, then add it inside
  `op.batch_alter_table` (PostgreSQL gets `ALTER TABLE ... ADD CONSTRAINT`,
  SQLite rebuilds the table). Always **name** the constraint so `downgrade` can
  drop it without relying on a naming convention — and it must drop it, because
  neither table can be dropped while the cycle is closed.
  `4586e6747b1d_initial_schema.py` is the worked example
  (`applicationinstance` ↔ `deployment`).
  `sa.ForeignKeyConstraint(..., use_alter=True)` does *not* help here:
  `use_alter` is honoured by `metadata.create_all()`, not by `op.create_table`.
- **Create each PostgreSQL enum type exactly once.** `op.create_table` emits
  `CREATE TYPE` for every enum column it sees (with `checkfirst=False`), while
  `op.add_column` emits none — so a revision that adds an enum column to one
  table and creates another table using the same enum will try to create the
  type twice and abort with `DuplicateObjectError`. Create the type explicitly
  up front with `sa.Enum(...).create(op.get_bind(), checkfirst=True)`, then give
  the columns a type that will not redeclare it:
  `postgresql.ENUM(..., create_type=False)` on PostgreSQL, plain `sa.Enum` on
  SQLite (which has no enum types — it renders `VARCHAR` plus a per-table CHECK
  constraint). `c0d1e2f3a4b5_add_role_and_groups.py` is the worked example.
- **Never hardcode an auto-generated constraint name.** PostgreSQL derives
  `<table>_<column>_key` for an unnamed `UniqueConstraint`; SQLite emits a bare
  `UNIQUE (col)` and reflects it with `name=None`, so batch mode cannot target
  it. Inspect the live schema
  (`sa.inspect(bind).get_unique_constraints(...)`), skip when the constraint is
  absent, and pass a `naming_convention` to `op.batch_alter_table` to name the
  unnamed reflected constraint.
  `c9d0e1f2a3b4_deployment_name_scoped_uniqueness.py` is the worked example.
- **Drop enum types explicitly in `downgrade`.** `op.create_table` emits
  `CREATE TYPE` for every PostgreSQL enum column, but `op.drop_table` builds a
  bare `Table` with no columns and therefore never emits the matching
  `DROP TYPE`. A downgrade that forgets this leaves the type behind and the next
  upgrade fails with `DuplicateObjectError: type "..." already exists`. Call
  `sa.Enum(..., name="...").drop(op.get_bind(), checkfirst=True)`, which is a
  no-op on SQLite.
- **Renaming a table does not rename its constraints.** `op.rename_table` emits
  `ALTER TABLE ... RENAME TO`, which leaves every constraint carrying the name
  PostgreSQL derived from the *old* table name — so the renamed table
  permanently disagrees with `create_all()`. Fix it in the same revision with
  `ALTER TABLE ... RENAME CONSTRAINT` (there is no `op.rename_constraint`; use
  `op.execute`). That statement also renames the index backing a PRIMARY KEY or
  UNIQUE constraint, so no separate index rename is needed. SQLite emits both
  anonymously and has nothing to rename.
  `b9c0d1e2f3a4_align_status_constraints_with_models.py` is the worked example.
- **Changing a foreign key's `ON DELETE` means dropping and recreating it**, on
  both backends — neither supports altering the referential action in place. On
  SQLite that is a `op.batch_alter_table` table rebuild, which brings two traps.
  First, batch mode **refuses to create an unnamed constraint** ("Constraint
  must have a name"), so the replacement must be named even where the original
  was anonymous — prefer the name PostgreSQL would generate
  (`<table>_<column>_fkey`) so one canonical name identifies the constraint on
  both backends. Second, that makes the constraint's name differ between a
  database built by the original `create_table` (anonymous) and one that has
  been through this revision's own `downgrade` (named), so a re-upgrade must
  **inspect the live schema** for the reflected name rather than assume either
  — `sa.inspect(bind).get_foreign_keys(table)`, falling back to the
  `naming_convention` name when reflection reports `name=None`.

## Transitioning an Existing Database

If you have a database created with the old `create_all()` method:

```bash
styrmin db stamp
```

This records the database as being at the latest migration version without re-running migrations.

## Configuration

Migrations use the same database configuration as the application via `STYRMIN_DB_*` environment variables. There is no `alembic.ini`: `backend/styrmin_backend/cli/db.py` constructs the Alembic `Config` in code and sets only `script_location`, and `migrations/env.py` initializes the app settings and calls `get_database_url()`. Do not add an `alembic.ini` — nothing reads one.

## Architecture

- **env.py**: Configures Alembic for async operation using `asyncio.run()` and `connection.run_sync()` to bridge the async engine with Alembic's synchronous migration API.
- **render_as_batch=True**: Enabled unconditionally to support SQLite's limited `ALTER TABLE` capabilities. Harmless on PostgreSQL.
- **compare_type=True / compare_server_default=True**: Both enabled so autogenerate reports column type and `server_default` drift instead of silently ignoring it. Without them a changed column type or default never shows up in a diff.
- **SQLModel.metadata**: Used as `target_metadata` for autogeneration, ensuring migrations stay in sync with model definitions.

## Testing

Unit tests mock the Alembic command layer. Repository tests continue to use in-memory SQLite with `create_all()`/`drop_all()` for speed and isolation — they do not run through migrations.
