---
title: Lifecycle hooks and actions
sidebar_position: 7
description: How drivers encode "stop the workers, run the migration, restart, verify" as repeatable code.
---

## Lifecycle hooks and actions

Some applications need steps before or after the install: remove a
database flag before an upgrade, run a migration after the new version
starts, fill a cache, or test the new release.

A **lifecycle hook** is a point in the deployment lifecycle where Styrmin
runs Python code from the driver. This code is called an **action**. The
driver author writes the action once, and Styrmin runs it the same way on
every deployment.

### Hooks and modes

There are two hooks:

- **`setup`**: runs when a deployment is first created.
- **`upgrade`**: runs when a deployment moves to a new application
  version or driver version.

Each hook has three **modes** that set the order:

| Mode | When it runs | Typical use |
|------|--------------|-------------|
| `pre` | Before the main operation starts. | Stop dependent components, take a backup before the upgrade, validate input. |
| `core` | The hook's main operation, such as the Helm upgrade. | The main operation of the hook. |
| `post` | After the main operation succeeds. | Run migrations, restart workers, test the new version. |

The order across modes is fixed: `pre` finishes before `core` starts,
and `core` before `post`. The order within a mode is not defined. To run
two actions in a set order, put them in different modes.

### What an action looks like

A driver declares its actions in `driver.styrmin.yml`:

```yaml
spec:
  actions:
    - name: pre_setup
      hook: setup
      mode: pre
      location: "actions.py::pre_setup"
    - name: upgrade
      hook: upgrade
      mode: core
      location: "actions.py::upgrade"
      description: "Stop workers, run migration, restart, verify"
```

It implements them in `actions.py`, next to the driver specification:

```python
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
    await stop_components(components=["task-worker"], context=context)
    await upgrade_deployment_version(target_version=target_version, context=context)

    images = await get_component_images(component="server", context=context)
    # images[0] is the component container's image; drop any digest, then the tag
    # (a ":" followed by a "/" is a registry port, not a tag).
    name = images[0].split("@", 1)[0]
    repository, separator, tag = name.rpartition(":")
    image_base = repository if separator and "/" not in tag else name

    await execute_commands(
        ["infrahub", "db", "migrate"],
        image=f"{image_base}:{target_version}",
        context=context,
        env_from_component="server",
    )
    await start_components(components=["task-worker"], context=context)
    logger.info("Upgrade complete")
```

Note the following:

- The action is a Python function decorated as a
  [Prefect](https://www.prefect.io/) flow. Styrmin runs it in the agent's
  Prefect worker, and passes it the deployment's context.
- It uses **built-in primitives** (`stop_components`, `start_components`,
  `upgrade_deployment_version`, `get_component_images`,
  `execute_commands`) instead of calling the Kubernetes API. The
  primitives are tested, idempotent, and the same for every driver.
- Each step of the upgrade is a line of Python, in order. A procedure of
  five steps and a check is five calls and a check in the action.

### How actions call the Styrmin API

`stop_components`, `start_components` and `upgrade_deployment_version`
call the Styrmin API. Each time Styrmin reconciles a deployment, it
creates a short-lived token for the built-in user `styrmin-actions` (role
Read/write, no password). It gives the token to the actions of that
reconciliation in the `STYRMIN_TOKEN` environment variable, and revokes
the token when the reconciliation ends. The Python SDK reads the same
variable, so an action that uses the SDK is authenticated as
`styrmin-actions` too.

`styrmin-actions` appears in the user list. If an administrator
deactivates it, or sets its role to Read-only, the actions' calls to the
API fail and the deployment's task ends as `failed`. No one can log in as
`styrmin-actions`: Styrmin rejects a login with its username and refuses
to set or reset its password, so only Styrmin's own flows and actions can
record steps.

### Steps of a hook

Each mode of a hook that runs is one step of the deployment's task, shown
on the deployment page and by `styrminctl tasks get`:

- Create: "Run the setup pre-hook" and "Run the setup post-hook".
- Upgrade: "Run the upgrade pre-hook", "Run the upgrade hook" and "Run
  the upgrade post-hook".

A mode without an action records no step; the `core` mode of the upgrade
hook always runs. When an action fails, its step fails with the action's
error.

When the Job that `execute_commands` starts fails, Styrmin stores the end
of the Job's output on the hook step: the last 200 lines, at most 64 KiB.
The deployment page shows it under "Show output", with "Earlier output
was cut" when Styrmin dropped the start. Every signed-in user, including
Read-only users, can read this output, so do not print secrets in action
commands.

Before `execute_commands` starts its own Job, it deletes the Job that an
earlier action of the same deployment left, after that Job has ended. The
hook step then shows a line that names the deleted Job. When that Job is
still running, for example because another change of the deployment runs
its action, the action fails, and its error says to wait for the Job to
end and request the change again.

When the flow run of an action crashes, the hook step's error contains
the first log line of level `ERROR` of that flow run. Styrmin replaces
the action's API token and common forms of secrets in that line with
`<redacted>`, and the same forms in every line of its logs. Do not write
secrets to the logs of an action either: log ids and names, not the values
of the context (see
[Logging in an action](../drivers/creating-a-driver.md#logging-in-an-action)).

When an action calls `stop_components`, `start_components` or
`upgrade_deployment_version`, Styrmin links the task that the call
creates to the hook step. The deployment page lists that task, with its
result, under the hook step, and the started task shows "Started by" with
the type of the task that started it. The result of the upgrade includes
the results of the tasks its hook started. `upgrade_deployment_version`
to the version the deployment already has starts no task. Calls that an
action makes through the Python SDK, instead of these primitives, are not
linked: the tasks they create appear as separate entries.

### Hooks of an earlier change

Each change to a deployment starts its own workflow. When a later change
reaches the cluster first, the workflow of the earlier change leaves the
`StyrminDeployment` unchanged but still runs the hooks of the earlier
change. For an upgrade, the upgrade pre-hook, upgrade hook and post-hook
can then run while the deployment already runs the later change, and
after the deployment page shows `running` for it. An action that calls
`stop_components` or `start_components` in that case starts a task that
uses the deployment's current configuration, which includes the later
change.

Wait for the task of an upgrade to end before you make the next change
to the deployment.

### Reading a component's images

Upgrade actions often run a migration Job with the component's own image
at the target version. The `get_component_images` primitive returns the
image of every regular container in the component's pod template (not
the init containers), with the **component container**'s image first
when the driver declares one, and the others in pod order. When a user
sets an [image override](./image-overrides.md) on the component, that
first image is the override, so an action that takes `images[0]` runs the
user's build. An action that searches the list for an image name does not
find the override.

An action runs for the new configuration of the deployment, which can
reach the component's workload after the action starts, for example when
one apply sets an image override and changes the version. The first
image is then the override from the new configuration, with
`{{ app.version }}` set to the target version.
`execute_commands(env_from_component=...)` also copies the env of the
component container and sets the user's env vars from the new
configuration on top. An env var that the new configuration removes is
still copied from the workload.

### Why Prefect?

Actions are workflows: they can run for a long time, they can fail, and
each step may need its own retry. [Prefect](https://www.prefect.io/)
provides retries, run history, and a UI to inspect a running or failed
flow.

While a deployment workflow runs, you can open the Prefect UI
(`kubectl port-forward svc/prefect-server 4200:4200 -n styrmin`) and
follow the actions, including the ones that fail. The steps on the
deployment page show the same hooks, their errors, and the end of a
failed command's output, without access to Prefect.

### What you do and what the driver author does

| You (deploying applications) | The driver author |
|------------------------------|-------------------|
| Deploy and upgrade. | Wrote the actions once, so deploys and upgrades run the same way each time. |
| Read the task's steps, or the Prefect UI, when a step fails. | Chose the primitives and the mode of each action. |

### Next steps

- [**Reconciliation**](./reconciliation.md): when a hook runs.
- [**Backups and restores**](./backups-and-restores.md): another workflow
  that uses driver-defined actions for application-specific steps.
