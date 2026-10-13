---
title: Lifecycle hooks and actions
sidebar_position: 7
description: How drivers encode "stop the workers, run the migration, restart, verify" as repeatable code.
---

## Lifecycle hooks and actions

Some applications need work done around the install: drop a database
flag before an upgrade, run a migration after the new version is in,
warm a cache, smoke-test the new release. Doing that work by hand is
where most production incidents come from.

Styrmin's answer is **lifecycle hooks**: well-defined slots in the
deployment lifecycle where a driver can plug in a piece of Python code
called an **action**. The driver author writes the action once; Styrmin
runs it the same way every time.

### Hooks and modes

There are two hooks today:

- **`setup`** — runs when a deployment is first created.
- **`upgrade`** — runs when a deployment moves to a new application or
  driver version.

Each hook has three **modes** that determine ordering:

| Mode | When it runs | Typical use |
|------|--------------|-------------|
| `pre` | Before the core work begins. | Stop dependent components, take a pre-flight backup, validate input. |
| `core` | The main event (e.g. the Helm upgrade itself). | The thing the hook is for. |
| `post` | After the core work succeeds. | Run migrations, restart workers, smoke-test the new version. |

Ordering across modes is strict (`pre` finishes before `core` starts;
`core` before `post`). Ordering _within_ a mode is unspecified — if you
care about the order of two pre-hooks, put them in separate modes.

### What an action looks like

A driver declares its actions in `driver.styrmin.yml`:

```yaml
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

And implements them in `actions.py`, alongside the driver spec:

```python
from prefect import flow, get_run_logger
from styrmin_backend.actions import (
    GlobalContext,
    stop_components,
    start_components,
    execute_commands,
)

@flow
async def upgrade(deployment_id: str, target_version: str) -> None:
    logger = get_run_logger()
    await stop_components(deployment_id, ["task-worker"])
    await execute_commands(
        deployment_id,
        component="server",
        commands=[["infrahub", "migrate"]],
    )
    await start_components(deployment_id, ["task-worker"])
    logger.info("Upgrade complete")
```

Three things to notice:

- The action is a regular Python function decorated as a [Prefect](https://www.prefect.io/)
  flow. Styrmin runs it inside the agent's Prefect worker.
- It uses **built-in primitives** (`stop_components`,
  `start_components`, `execute_commands`, …) instead of poking at
  Kubernetes directly. Those primitives are tested, idempotent, and
  consistent across drivers.
- It's _just code_. If your application's upgrade dance needs five
  ordered steps and a sanity check, you express that as Python — no
  shell scripts, no runbooks.

### How actions call the Styrmin API

`stop_components`, `start_components` and `upgrade_deployment_version`
call the Styrmin API. Each time Styrmin reconciles a deployment, it creates
a short-lived token for the built-in user `styrmin-actions` (role
Read/write, no password), gives the token to the actions of that reconcile
in the `STYRMIN_TOKEN` environment variable, and revokes the token when the
reconcile ends. The Python SDK reads the same variable, so an action that
uses the SDK is authenticated as `styrmin-actions` too.

`styrmin-actions` appears in the user list. If an admin deactivates it, or
sets its role to Read-only, the actions' calls to the API fail and the
deployment's task ends as `failed`. No one can log in as `styrmin-actions`:
Styrmin rejects a login with its username and refuses to set or reset its
password, so only Styrmin's own flows and actions can record steps.

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
Read-only users, can read this output, so action commands must not print
secrets.

When an action calls `stop_components`, `start_components` or
`upgrade_deployment_version`, the task that the call creates is linked to
the hook step. The deployment page lists that task, with its result,
under the hook step, and the started task shows "Started by" with the
type of the task that started it. The result of the upgrade includes the
results of the tasks its hook started. `upgrade_deployment_version` to the
version the deployment already has starts no task. Calls that an action
makes through the Python SDK instead of these primitives are not linked:
the tasks they create appear as separate entries.

### Hooks of an earlier change

Each change to a deployment starts its own workflow. When a later
change reaches the cluster first, the workflow of the earlier change
leaves the `StyrminDeployment` unchanged but still runs the hooks of
the earlier change. For an upgrade, the upgrade pre-hook, upgrade hook
and post-hook can then run while the deployment already runs the later
change, and after the deployment page shows `running` for it. An action
that calls `stop_components` or `start_components` in that case starts
a task that uses the deployment's current configuration, which includes
the later change.

Wait for the task of an upgrade to end before you make the next change
to the deployment.

### Reading a component's images

Upgrade actions often run a migration Job with the component's own
image at the target version. The `get_component_images` primitive
returns the image of every regular container in the component's pod
template (init containers are excluded),
with the **component container**'s image first (when the driver
declares one) and the rest in pod order. When a user sets an
[image override](./image-overrides.md) on the component, that first
image is the override, so an action that takes `images[0]` runs the
user's build. Searching the list for an image name would miss it.

An action runs for the new configuration of the deployment, which can
reach the component's workload after the action starts: for example when
one apply sets an image override and changes the version. The first
image is then the override from the new configuration, with
`{{ app.version }}` set to the target version.
`execute_commands(env_from_component=...)` likewise copies the env of the
component container and sets the user's env vars from the new
configuration on top. An env var removed in that configuration is still
copied from the workload.

### Why Prefect?

Actions are workflows: long-running, sometimes flaky, with steps that
need to be retried independently. [Prefect](https://www.prefect.io/)
gives Styrmin retries, observability, and a UI for inspecting a flow
that's currently running or failed — for free.

When a deployment workflow is running, you can open the Prefect UI
(`kubectl port-forward svc/prefect-server 4200:4200 -n styrmin`) and
watch the actions execute, including any that fail. The steps on the
deployment page show the same hooks, their errors and the end of a failed
command's output without access to Prefect.

### What you do vs what the driver author does

| You (the operator) | The driver author |
|--------------------|-------------------|
| Deploy and upgrade. | Wrote the actions once so deploys and upgrades are repeatable. |
| Read the task's steps, or the Prefect UI, if something looks off. | Picked which primitives to use and which modes they run in. |

### Next

- [**Reconciliation**](./reconciliation.md) — the loop that decides
  _when_ to run a hook.
- [**Backups and restores**](./backups-and-restores.md) — another
  workflow that uses driver-defined actions for per-application logic.
