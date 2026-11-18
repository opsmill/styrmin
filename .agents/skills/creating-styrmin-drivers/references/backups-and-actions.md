# Backups and actions

## Backup strategies

Each stateful component declares how Styrmin backs it up. Velero stores the result in the
environment's backup storage location.

| `kind` | What Styrmin does | What the driver must provide |
|---|---|---|
| `disk` | snapshots the named pod volumes | `volume: <pod-template volume name>` or `volumes: [...]` (the name under `volumes:` in the pod spec, not the PVC name). Without it the backup is empty and nothing reports it |
| `postgres` | runs `pg_dump` in the database container into `/backup`, then snapshots that volume | an `emptyDir` volume named `backup`, mounted at `/backup` in the database container; env `POSTGRES_USER`, `POSTGRES_DATABASE` and `POSTGRES_PASSWORD` (or `POSTGRES_PASSWORD_FILE`) in that container (Bitnami PostgreSQL sets them) |
| `mariadb` | `mariadb-dump` into `/backup` | the same `backup` volume at `/backup` |
| `mongodb` | `mongodump` into `/backup` | the same `backup` volume at `/backup` |
| `neo4j` | `neo4j-admin dump` into `/backup` | the same `backup` volume at `/backup` |
| `action` | runs a driver action | an action that does the backup |

Bitnami PostgreSQL subchart:

```yaml
postgresql:
  primary:
    extraVolumes:
      - name: backup
        emptyDir: {}
    extraVolumeMounts:
      - name: backup
        mountPath: /backup
```

Leave out `backup` for stateless components. A cache that the application can rebuild (Redis,
Valkey used as a cache) needs no backup. Mark single-primary data stores `singleton: true`.

## Lifecycle actions

Most drivers need none: the chart installs, upgrades and uninstalls the application, and many
applications migrate their database on start. Add an action only when Helm cannot express a step.

| Hook | Mode | Runs |
|---|---|---|
| `setup` | `pre` / `post` | before / after the first install |
| `upgrade` | `pre` / `post` | before / after the upgrade |
| `upgrade` | `core` | **instead of** Styrmin's upgrade: must call `upgrade_deployment_version` |

```yaml
spec:
  actions:
    - name: upgrade
      hook: upgrade
      mode: core
      description: Stop the workers, upgrade, start the workers
      location: "actions.py::upgrade"
```

```python
# actions.py: each action is a Prefect flow that receives the context
from prefect import flow, get_run_logger
from styrmin_backend.actions import (
    GlobalContext,
    execute_commands,
    get_component_images,
    start_components,
    stop_components,
    upgrade_deployment_version,
)


@flow
async def upgrade(context: GlobalContext, target_version: str) -> None:
    logger = get_run_logger()
    await stop_components(components=["worker"], context=context)
    await upgrade_deployment_version(target_version=target_version, context=context)
    await start_components(components=["worker"], context=context)
    logger.info("Upgrade to %s complete", target_version)
```

Primitives (all `await`ed, all take `context=context`):

| Primitive | Effect |
|---|---|
| `stop_components(components=[...])` | sets the replicas of the components' Deployments and StatefulSets to 0 |
| `start_components(components=[...])` | restores their replica counts |
| `upgrade_deployment_version(target_version=...)` | runs the Helm upgrade to the new version |
| `get_component_images(component=...)` | images of the component's pod, the component container first |
| `get_component_labels(component=...)` | labels of the component |
| `execute_commands(commands, image=..., env_from_component=..., labels_from_component=...)` | runs a Job in the namespace (the namespace's network policies apply to it) |

Rules:

- Component names in the primitives must be declared in `spec.components`.
- Import only `prefect`, `styrmin_backend.actions`, the standard library and modules in the driver
  directory: the agent runs the action in its own image.
- Keep every action in `actions.py`; a driver loaded from a local directory refuses other files.
- Do not log secrets: the first ERROR line of a crashed action is shown to every user.
- Never change chart resources with `kubectl patch` in an action: the next Helm upgrade reverts it.
