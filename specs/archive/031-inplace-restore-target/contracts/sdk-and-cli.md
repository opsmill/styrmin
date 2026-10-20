# Contract: Python SDK and `styrminctl backups restore`

**Feature**: [spec.md](../spec.md) | **Research**: [R-009](../research.md#r-009-the-python-sdk-loses-both-parameters), [R-010](../research.md#r-010-styrminctl-backups-restore-refuses-a-backup-id-with-a-target-option-in-the-command-body)

## Python SDK

Before:

```python
async def create_restore(
    self,
    backup_id: str | UUID,
    target_namespace: str,
    target_instance_id: str | UUID | None = None,
) -> CreateRestoreCreateRestore: ...
```

After:

```python
async def create_restore(self, backup_id: str | UUID) -> CreateRestoreCreateRestore: ...
```

- Sends `{"backupId": "<id>"}` and nothing else.
- A caller that passes `target_namespace` or `target_instance_id` gets a Python `TypeError` (FR-003).
- `get_restore`, `list_restores` and `wait_for_restore` are unchanged; the returned models keep `target_namespace` and `target_instance_id`.

## `styrminctl backups restore`

### Options

| Option | Before | After |
|--------|--------|-------|
| `BACKUP-ID` | The backup to restore. | Unchanged. Restored into the deployment it was taken of. |
| `--target-deployment` | Names the target deployment, with a backup id or with `--last`. | Only with `--last`: the deployment whose backup history the newest backup comes from. |
| `--target-deployment-id` | Same, by id. | Only with `--last`, by id. |
| `--target-instance-id` | Names the target instance; with a backup id it needed `--target-namespace`. | Only with `--last`: the instance whose backups the newest backup comes from. |
| `--environment` | Tells `--target-deployment` which environment a name belongs to. | Unchanged. |
| `--target-namespace` | Overrides the namespace. | Removed. Cyclopts rejects it as an unknown option. |
| `--last`, `--yes`, `--wait`, `--max-wait`, `--interval` | | Unchanged. |

Help texts change for `--target-deployment`, `--target-deployment-id` and `--target-instance-id` ([`cli/src/styrminctl/types.py`](../../../cli/src/styrminctl/types.py): `TargetDeploymentName`, `TargetDeploymentId`, `OptionalInstanceId`, all three used only by this command), for `--last`, and in the command's docstring, so that none of them says the option chooses where the backup is restored.

### Combinations

| Invocation | Result |
|------------|--------|
| `restore <backup id>` | Calls `create_restore(backup_id=<id>)`. |
| `restore <backup id> --target-deployment X` (or `--target-deployment-id`, or `--target-instance-id`) | Refused before any call to the server, exit code 1. The error names the three options, says that they work only with `--last`, says that a backup is restored into the deployment it was taken of, and tells the user to run the command again without the option. |
| `restore <backup id> --target-namespace N` | Rejected by Cyclopts as an unknown option. |
| `restore <backup id> --last` | Refused, as today: "Provide either a backup_id or --last, not both". |
| `restore --last --target-deployment X` | Chooses the newest completed, unexpired backup from X's backup history, asks for confirmation for a backup of an earlier instance unless `--yes`, then calls `create_restore(backup_id=<chosen id>)`. |
| `restore --last --target-instance-id I` | Chooses the newest completed, unexpired backup of instance I and calls `create_restore(backup_id=<chosen id>)`. No namespace option is needed. |
| `restore --last` without a target option | Refused, as today. |
| `restore` with neither a backup id nor `--last` | Refused, as today. |
| More than one of the three target options | Refused, as today. |

The refusal for a backup id with a target option is checked before the existing check for more than one target option, so a user who passes a backup id and two target options gets the refusal that names `--last`.

`restore-get` and `restore-list` are unchanged.
