# Data Model: Migrate styrminctl CLI from Typer to Cyclopts

**Feature**: 001-migrate-cli-cyclopts | **Date**: 2026-03-25

> This feature does not introduce new data entities. This document maps the CLI command surface area — the "model" of the CLI interface that must be preserved through migration.

## Command Surface Area

### Root App

| Property | Current (Typer) | Target (Cyclopts) |
|----------|----------------|-------------------|
| Name | `styrminctl` | `styrminctl` |
| Entry point | `styrminctl.cli:app` | `styrminctl.cli:app` |
| Help | Styrmin client CLI | Styrmin client CLI |
| Version | from package metadata | from package metadata |

### Command Groups (7)

| Group | Commands | Help Text |
|-------|----------|-----------|
| `clusters` | 4 | Manage clusters |
| `environments` | 4 | Manage environments |
| `drivers` | 3 | Manage application drivers |
| `deployments` | 10 | Manage deployments |
| `backups` | 9 | Manage backups and restores |
| `backup-locations` | 6 | Manage backup storage locations |
| `tasks` | 2 | View tasks |

### Command Inventory (35 total)

#### clusters (4 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `create` | `name: str`, `config: str \| None` | Table: created cluster |
| `list` | (none) | Table: all clusters |
| `get` | `id: str` | JSON: cluster details |
| `delete` | `id: str` | Success message |

#### environments (4 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `create` | `name: str`, `cluster_id: str`, `config: str \| None` | Table: created environment |
| `list` | (none) | Table: all environments |
| `get` | `id: str` | JSON: environment details |
| `delete` | `id: str` | Success message |

#### drivers (3 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `create` | `name: str` | Table: created driver |
| `load-version` | `driver_id: str`, `git_url: str`, `ref: str`, `path: str \| None` | Success message |
| `load-local-version` | `driver_id: str`, `directory: str` | Success message |

#### deployments (10 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `create` | `name: str`, `environment_id: str`, `driver_id: str`, `version: str`, `config: str \| None` | Table: created deployment |
| `get` | `id: str` | JSON: deployment details |
| `update` | `id: str`, `config: str \| None` | Success message |
| `update-version` | `id: str`, `version: str` | Success message |
| `start-components` | `id: str`, `components: list[str]` | Success message |
| `stop-components` | `id: str`, `components: list[str]` | Success message |
| `run-job` | `id: str`, `job_name: str`, `config: str \| None` | Success/progress message |
| `context` | `id: str` | JSON: deployment context |

#### backups (9 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `create` | `instance_id: str`, `name: str \| None` | Table: created backup |
| `get` | `id: str` | JSON: backup details |
| `list` | `instance_id: str` | Table: backups for instance |
| `delete` | `id: str` | Success message |
| `restore` | `backup_id: str`, `name: str \| None`, `config: str \| None` | Table: restore operation |
| `restore-get` | `id: str` | JSON: restore details |
| `restore-list` | `backup_id: str` | Table: restores for backup |

#### backup-locations (6 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `create` | `name: str`, `type: str`, `config: str` | Table: created location |
| `list` | (none) | Table: all locations |
| `get` | `id: str` | JSON: location details |
| `delete` | `id: str` | Success message |
| `assign` | `id: str`, `environment_id: str` | Success message |
| `unassign` | `environment_id: str` | Success message |

#### tasks (2 commands)

| Command | Parameters | Return |
|---------|-----------|--------|
| `list` | `status: str \| None` | Table: tasks |
| `get` | `id: str` | JSON: task details |

## Shared Patterns

### Client Initialization

Every command module uses:
```python
def _get_client() -> StyrminClient:
    return StyrminClient(
        server_address=SETTINGS.server_address,
        timeout=SETTINGS.timeout,
        headers=SETTINGS.additional_headers,
    )
```
This pattern is **unchanged** by the migration.

### Error Handling Pattern

```python
# Current (Typer)
except StyrminError as e:
    print_error(str(e))
    raise typer.Exit(code=1) from e

# Target (Cyclopts)
except StyrminError as e:
    print_error(str(e))
    raise SystemExit(1) from e
```

### Output Utilities (unchanged)

- `print_table(rows, columns, title)` — Rich table
- `print_error(message)` — Red error text
- `print_success(message)` — Green success text
- `console.print_json(data=...)` — JSON output
- `parse_json_argument(value)` — Parse inline JSON or `@filepath`

## Breaking Changes

| Change | Impact | Mitigation |
|--------|--------|------------|
| `--no-<flag>` boolean negation removed | Users using `--no-wait` etc. must use `--wait false` or omit the flag | Document in changelog/release notes |
| Help text layout changes | Visual differences in `--help` output | Expected; follows Cyclopts conventions matching backend CLI |
