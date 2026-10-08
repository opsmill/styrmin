# Contract: `styrminctl backups list` and `styrminctl backups restore --last`

**Feature**: [../spec.md](../spec.md) | **Requirements**: FR-002, FR-004

## `styrminctl backups list`

Selectors (unchanged; exactly one is required):

- `[DEPLOYMENT]` positional name, optionally with `--environment`
- `--id <deployment-id>`
- `--instance-id <instance-id>`

| Selector | Lists |
|----------|-------|
| name or `--id` | The deployment's backup history: backups of every instance it has had, newest first. Works when the deployment has no active instance. |
| `--instance-id` | The backups of that one instance, as today |

`--status` filters either list, as today.

Table columns (one added, after `status`):

```text
id | name | status | application_version | started_at | completed_at | size_bytes | expires_at
```

`application_version` is the application version of the instance the backup was taken of.

Help text, replacing "List backups for a deployment's active application instance.":

```text
List a deployment's backup history: the backups of every instance it has had,
newest first, with the application version each one was taken at.

Target the deployment by name (optionally with --environment) or by --id.
--instance-id lists the backups of one instance only.
```

Empty result prints `No backups found.`, as today.

## `styrminctl backups restore --last`

| Target selector | Backup chosen |
|-----------------|---------------|
| `--target-deployment <name>` or `--target-deployment-id <id>` | Newest completed backup in the deployment's history, whichever instance it was taken of |
| `--target-instance-id <id>` | Newest completed backup of that instance, as today |

When the history has no completed backup, the command fails with a message that names the deployment, for example `No completed backups found for deployment 'my-app'`. With `--target-instance-id`, the message stays `No completed backups found for instance <id>`.

The restore itself is unchanged: same target namespace derivation, same mutation, no version check (FR-008).

Help text for `--last` states that it chooses from the deployment's backup history.
