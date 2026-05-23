---
title: Creating a Driver
sidebar_position: 4
description: A practical guide — pick a Helm chart, end up with a working Application Driver.
---

## Creating a Driver

This page walks you through writing a new driver from scratch. The
running example is a small two-component application — call it
`my-app` — with a FastAPI server and a PostgreSQL database. It's
deliberately minimal so every concept on this page has a place to
land; substitute your own chart and naming as you read.

Read [What is an Application Driver?](../concepts-and-architecture/what-is-a-driver.md) and
[The Context](./context.md) first if you haven't.

### Before you start

You need:

- **A Helm chart** for the application you want to deploy. The chart
  should already install successfully on its own with `helm install`.
  Styrmin doesn't write Helm charts; it operates them.
- **A running Styrmin instance** to load and test against. The
  [Quickstart](../installation/quickstart.md) or
  [Local laptop](../installation/vcluster-local.md) guide both work.
- **Familiarity with the application's lifecycle** — what it stores,
  what needs to happen during an upgrade, how it expects to be backed
  up. The driver is where you encode this knowledge once so nobody has
  to remember it again.

### The shape of a driver

A driver is a directory with three files:

```text
my-driver/
├── driver.styrmin.yml   # required — the specification
├── values.j2.yml        # optional — Jinja2 template for the Helm values
└── actions.py           # required only if the spec declares actions
```

You'll fill them in roughly in that order: spec first to define the
shape, then values to wire the chart up, then actions only if the
application has lifecycle work that can't be expressed as Helm values.

### Step 1: Analyse the Helm chart

Before you write a single line of driver, install the chart by hand
once and look at what it produces:

```shell
helm install test-run <chart> -n test --dry-run --debug | less
kubectl get all -n test
```

You're looking for two things.

**The workloads** — every `Deployment`, `StatefulSet`, `Job`, or
`CronJob` the chart creates. Each of these is something Styrmin might
need to start, stop, scale, or back up independently. These are your
candidate **components**.

For `my-app`, the chart produces two workloads: the FastAPI server
(a `Deployment`) and a PostgreSQL primary (a `StatefulSet`). That's the
list of candidate components.

**The HA-shaped pieces** — workloads with replicas, persistent volumes,
clustering, leader election, or any "this can't just be restarted in
any order" property. These are the ones that need extra care:

- **Stateful storage** (databases, caches, queues with disk) → almost
  always its own component, almost always needs an
  application-specific backup strategy (not just a disk snapshot).
- **Replicated services** (an API server with N replicas) → usually
  one component, scale-controlled at the chart level.
- **Background workers** (task queues, async processors) → often a
  separate component if you need to stop them during a migration.

For `my-app`: the FastAPI server is a single stateless workload
(one component, no backup), and PostgreSQL is stateful (one component,
needs a `postgres` backup strategy).

**Output of this step:** a short list of components, with notes on what
each one is and how it should be backed up.

### Step 2: Write the driver spec

Create `driver.styrmin.yml`. The minimum a Styrmin install will accept:

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: my-app              # must be unique across the Styrmin install
spec:
  version: "1"              # the driver version (you'll bump this as you iterate)
  supported_versions: ">=0.1,<1.0"   # semver range of the application versions this driver knows how to deploy
  info:
    description: Example FastAPI application with PostgreSQL
    authors: [you]
    license: Apache-2.0
  helm:
    main:
      location: my-app       # OCI URL or local path the server can resolve
      version: 0.1.0         # the chart version
```

A few notes:

- **`metadata.name`** is the user-facing identifier. Once chosen,
  changing it later is awkward — every deployment pinned to the old
  name has to be re-created.
- **`supported_versions`** is a [PEP 440 / semver
  specifier](https://semver.org/) describing which application
  versions this driver knows how to deploy. Loaders refuse to deploy
  an application version outside this range — a useful guard against
  someone selecting a version your driver hasn't been tested with.
- **`helm.main.location`** is whatever the Styrmin server can pass to
  Helm — an OCI URL (`oci://registry.example.com/charts/foo`), an HTTP
  repository URL, or a relative path inside a baked-in chart
  directory.

### Step 3: Declare the components

This is the core of the driver. For each candidate component from Step
1, add an entry under `spec.components`:

```yaml
spec:
  components:
    server:
      identifier:
        label:
          app.kubernetes.io/name: my-app
    database:
      identifier:
        label:
          app.kubernetes.io/name: postgresql
```

The **`identifier.label`** block is the contract between Styrmin and
the chart: it's how the agent finds the pods belonging to each
component. Every pod that matches all the labels in the block is
considered part of that component.

This means each component **must** have pods that carry a label
combination Styrmin can match on. Two paths to make that happen:

- **The chart already labels things distinctly.** Most well-maintained
  charts label pods by `app.kubernetes.io/name` (or similar), and
  different sub-charts use different names. The `my-app` example
  rides on that: the embedded `postgresql` chart labels its pods
  `app.kubernetes.io/name: postgresql` and the main chart labels its
  pods `app.kubernetes.io/name: my-app`. The driver just points at
  the existing labels.
- **You add a label via chart values.** Many charts expose `podLabels`
  or `extraLabels` in their `values.yaml`. The convention Styrmin uses
  internally for its own components is `styrmin/component: <name>` —
  for charts that don't otherwise distinguish their workloads, set
  this in `values.j2.yml`:

  ```yaml
  server:
    podLabels:
      styrmin/component: server
  worker:
    podLabels:
      styrmin/component: worker
  ```

  …and then identify each component by that label.

**Pick the simplest match that uniquely identifies the pods.** A
single, stable label is better than two; matching on values the chart
already sets is better than fighting it.

### Step 4: Configure backups

Per component, decide _how_ it should be backed up. The choices come
from a fixed set of **backup strategies** — full list and explanation
in [Backups and restores](../concepts-and-architecture/backups-and-restores.md).
Stateless components are typically left out entirely (no `backup`
block); stateful components pick the strategy that matches the
storage:

```yaml
spec:
  components:
    server:
      identifier:
        label:
          app.kubernetes.io/name: my-app
      # no backup — stateless

    database:
      identifier:
        label:
          app.kubernetes.io/name: postgresql
      backup:
        enabled: true
        kind: postgres                # use pg_dump + Velero snapshot
        database_name: my_app         # strategy-specific config
```

If none of the built-in strategies fits, set `kind: action` and
implement the backup logic as a driver action (see Step 7).

### Step 5: Template the Helm values

Create `values.j2.yml`. This is a [Jinja2](https://jinja.palletsprojects.com/)
template that produces the values file Helm receives. The
[Context](./context.md) is available to it — the same context that
gets embedded in the `StyrminDeployment` CRD.

A short example for `my-app`:

```yaml
fullnameOverride: styrmin-my-app

image:
  repository: my-app
  tag: "{{ app.version }}"

extraEnv: {{ components | component_env_vars("server") | tojson }}

ingress:
  enabled: true
  className: "{{ instance.config.ingress_class }}"
  hosts:
    - host: "{{ services['my-app'].primary_fqdn }}"
      paths:
        - path: /
          pathType: Prefix

postgresql:
  enabled: true
  fullnameOverride: styrmin-postgresql
  primary:
    extraEnvVars: {{ components | component_env_vars("database") | tojson }}
```

Patterns to know:

- **`{{ app.version }}`** for the application version the user picked.
- **`{{ instance.config.X }}`** for merged cluster/environment/deployment
  configuration. Use this in preference to reading the individual
  layers.
- **`{{ services['<name>'].primary_fqdn }}`** to get the auto-generated
  hostname for a service you declared (see next step).
- **`{{ components | component_env_vars("<name>") | tojson }}`** to
  inject the per-component env vars (declared via `env_vars` —
  optional).

See [The Context](./context.md) for the full set of available fields.

### Step 6: Declare services

If the application exposes anything over the network, declare it under
`spec.services`. This is what makes Styrmin auto-generate hostnames
and tells the ingress controller what to route:

```yaml
spec:
  services:
    - name: my-app
      kind: http             # http | https | tcp
      scope: internal        # internal | external
      port: 8000
      component: server      # which component this service belongs to
```

A few notes:

- **`scope: external`** opts the service into hostname generation —
  the application becomes reachable via the per-environment ingress.
  `internal` means cluster-only.
- **The hostname** for an external service follows the pattern
  `<service-name>-<deployment-id>.<fqdn-suffix>`, and the template can
  reference it via `{{ services['<service-name>'].primary_fqdn }}`.
- See [Ingress and networking](../concepts-and-architecture/ingress-and-networking.md)
  for what actually happens with these declarations.

### Step 7: Lifecycle actions — only when you need them

Most drivers don't need actions. The Helm chart, plus a per-component
backup strategy, is enough to handle install / uninstall / backup /
restore.

You need an action when:

- **The upgrade needs sequencing.** Stop the workers, run a migration,
  start the workers, smoke-test — that's the canonical case.
- **Setup needs custom work** that doesn't fit in the chart (seeding
  initial data, registering a webhook, warming a cache).
- **Backup needs custom logic** because no built-in strategy fits
  (`backup.kind: action`).

Actions are declared in the spec…

```yaml
spec:
  actions:
    - name: upgrade
      hook: upgrade           # setup | upgrade
      mode: core              # pre | core | post
      description: Upgrade my-app
      location: "actions.py::upgrade"
```

…and implemented as Prefect flows in `actions.py`. An example
implementation for `my-app`:

```python
from styrmin_backend.actions import (
    GlobalContext,
    execute_commands,
    get_component_images,
    start_components,
    stop_components,
    upgrade_deployment_version,
)
from prefect import flow, get_run_logger


@flow
async def upgrade(context: GlobalContext, target_version: str):
    logger = get_run_logger()
    await stop_components(components=["server"], context=context)
    await upgrade_deployment_version(target_version=target_version, context=context)

    images = await get_component_images(component="server", context=context)
    image = next(img for img in images if "my-app" in img)
    image_base = image.rsplit(":", 1)[0]

    await execute_commands(
        ["my-app-upgrade"],
        image=f"{image_base}:{target_version}",
        context=context,
        env_from_component="server",
        labels_from_component="server",
    )
    await start_components(components=["server"], context=context)
```

Use the built-in primitives (`stop_components`, `start_components`,
`execute_commands`, `upgrade_deployment_version`, …) rather than
calling Kubernetes directly. They're idempotent, tested, and
consistent across drivers.

See [Lifecycle hooks and actions](../concepts-and-architecture/hooks-and-actions.md)
for the full hook/mode model.

### Step 8: Parameters — only when you need them

Hardcode where you can; expose a parameter when the value genuinely
varies per deployment. Each parameter the driver declares shows up in
the UI when a user creates a deployment.

```yaml
spec:
  parameters:
    - name: storage_size
      label: "Storage size (Gi)"
      kind: integer
      default: 10
```

Values land in `{{ parameters.storage_size }}` in the template.

### Step 9: Load and test

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/my-app
```

(See [Loading a Driver](./loading-drivers.md) for the in-container path
convention and the git-repository alternative.)

Then deploy:

```shell
uv run styrminctl deployments create my-app 0.1.0 <environment-id>
```

Watch the deployment in the UI. Things to check:

- All components report `Running` once the deployment finishes.
- Triggering a backup completes successfully and lands in your BSL.
- Triggering an upgrade (to another `supported_versions` value) runs
  the upgrade action and the new version comes up clean.
- Deleting the deployment cleans up all resources.

Iterate by editing the driver, bumping `spec.version`, and re-running
`load-local-version`. Each load creates a new Application Driver
Version; existing deployments stay on whatever version they pinned
until you explicitly upgrade them.

### Validation checklist

Before you call the driver done:

- [ ] Every workload in the chart maps to a declared component (or you
      made a conscious decision not to expose one).
- [ ] Each component's `identifier.label` matches the pods you expect
      it to — verify with `kubectl get pods -l <label>=<value>`.
- [ ] Every stateful component has a `backup` block with the right
      strategy.
- [ ] Every externally reachable service is declared under
      `spec.services` with `scope: external`.
- [ ] The values template uses `{{ instance.config.X }}` where
      appropriate, not just hardcoded values.
- [ ] You've successfully run an end-to-end deploy → backup → restore
      → upgrade cycle on a test environment.
- [ ] The driver lives in version control. Driver iteration is much
      easier when each version is reviewable.

### Next

- [**The Context**](./context.md) — full reference for the fields your
  template and actions receive.
- [**Lifecycle hooks and actions**](../concepts-and-architecture/hooks-and-actions.md) —
  the hook / mode model and the available primitives.
- [**Backups and restores**](../concepts-and-architecture/backups-and-restores.md) —
  full list of backup strategies, what each one does.
- [**Loading a Driver**](./loading-drivers.md) — how to ship your
  driver to production (git repository or custom image).
