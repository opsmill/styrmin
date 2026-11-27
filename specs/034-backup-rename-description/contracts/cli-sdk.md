# Contract: SDK and CLI

## Python SDK (`styrmin_sdk.resources.backups.BackupResource`)

```python
async def create_backup(
    self, instance_id: UUID | str, name: str | None = None, description: str | None = None
) -> CreateBackupCreateBackup: ...

async def update_backup(
    self, backup_id: UUID | str, name: str | None = None, description: str | None = None
) -> UpdateBackupUpdateBackup: ...
```

- The SDK sends only the arguments that are set.
- `description=""` clears the description.
- The `Backup` results of `create_backup`, `get_backup` and `list_backups` include `description`.

## CLI (`styrminctl backups`)

```text
styrminctl backups create <deployment> [--id ...] [--environment ...] [--instance-id ...]
                          [--name NAME] [--description TEXT] [--wait ...]
styrminctl backups update <backup-id> [--name NAME] [--description TEXT]
```

- `update` with neither `--name` nor `--description` exits with a usage error and sends no request.
- `--description ""` clears the description.
- `get` prints the description. `list` adds a Description column, cut short to fit the table width.
- Errors from the server (`ALREADY_EXISTS`, `VALIDATION_ERROR`, `NOT_FOUND`) are printed as they are for the other `backups` commands.
