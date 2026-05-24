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

### Why Prefect?

Actions are workflows: long-running, sometimes flaky, with steps that
need to be retried independently. [Prefect](https://www.prefect.io/)
gives Styrmin retries, observability, and a UI for inspecting a flow
that's currently running or failed — for free.

When a deployment workflow is running, you can open the Prefect UI
(`kubectl port-forward svc/prefect-server 4200:4200 -n styrmin`) and
watch the actions execute, including any that fail.

### What you do vs what the driver author does

| You (the operator) | The driver author |
|--------------------|-------------------|
| Deploy and upgrade. | Wrote the actions once so deploys and upgrades are repeatable. |
| Watch the Prefect UI if something looks off. | Picked which primitives to use and which modes they run in. |

### Next

- [**Reconciliation**](./reconciliation.md) — the loop that decides
  _when_ to run a hook.
- [**Backups and restores**](./backups-and-restores.md) — another
  workflow that uses driver-defined actions for per-application logic.
