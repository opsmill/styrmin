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

You're looking for three things.

**The workloads** — every `Deployment`, `StatefulSet`, `Job`, or
`CronJob` the chart creates. Each of these is something Styrmin might
need to start, stop, scale, or back up independently. These are your
candidate **components**.

For `my-app`, the chart produces two workloads: the FastAPI server
(a `Deployment`) and a PostgreSQL primary (a `StatefulSet`). That's the
list of candidate components.

Note any `progressDeadlineSeconds` on a chart `Deployment`. FluxCD
waits for the chart's resources with kstatus, which reports a
`Deployment` as failed once its progress deadline passes, and FluxCD
then fails the change and rolls the release back. With a deadline below
270 seconds, the default readiness timeout of Styrmin's operator,
FluxCD does this before Styrmin reads why the pods are not ready, so
the failed step shows FluxCD's `ProgressDeadlineExceeded` failure
instead of the pods' reason, such as `ImagePullBackOff`. Kubernetes'
default deadline is 600 seconds.

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

**The Helm hooks** — resources annotated `helm.sh/hook`, which Helm
creates at a set point of an install, upgrade, rollback, uninstall or
test, for example a pre-upgrade migration `Job`. The `--dry-run` output
lists them in its `HOOKS:` section, before the `MANIFEST:` section.
Styrmin applies its post-render patches to Helm hooks as it does to
the chart's other resources:

- **Styrmin's labels** reach every hook, also a hook without
  `metadata.labels`. A hook whose own `metadata.labels` carry a
  component's first identifier label also gets that component's
  `styrmin/component` label.
- **The deployment's scheduling settings** (affinity, node affinity,
  tolerations, topology spread, resources and runtime class) reach hook
  `Job`, `CronJob`, `Deployment`, `StatefulSet`, `DaemonSet` and
  `ReplicaSet` resources whose own `metadata.labels` carry a component's
  first identifier label, with that component's settings. When the
  driver declares no components, they reach every hook of these kinds.
  A hook `Job` that should run on the deployment's nodes therefore needs
  the component's label on the `Job` itself, not only on its pod
  template.
- **Env var, image and container overrides, and the
  component-container guard** reach a hook only when it is a
  `Deployment` or `StatefulSet` that matches a component. Once an
  override applies to that component, a matching hook without the
  component container fails the install or upgrade with
  `COMPONENT_CONTAINER_NOT_FOUND`, as a template would (see
  [The component container](#the-component-container)).

**Output of this step:** a short list of components, with notes on what
each one is and how it should be backed up, and a list of the chart's
Helm hooks with the component each one matches, if any.

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
  info:                     # required block; every key in it is optional
    icon: https://docs.infrahub.app/img/infrahub-logo.svg   # replace with the URL of your application's logo
    description: Example FastAPI application with PostgreSQL
    authors: [you]
    license: Apache-2.0
    links:
      - link: Documentation  # label shown on the driver detail page
        url: https://docs.example.com/my-app
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
- **`info.icon`, `info.description` and `info.links`** describe the
  application on the driver list page and the driver detail page:
  - `icon` is the absolute `https` URL of the logo image. Use a square
    SVG or PNG that is visible on a white background: the pages show it
    on a white tile next to the driver name, in the light and the dark
    theme. They show a generic package icon until the image has loaded,
    and when `icon` is not set or cannot be loaded.
  - `description` is plain text. The driver list page shows its first
    line, and the driver detail page its first three lines, each with a
    "Show more" button when the text is longer.
  - Each `links` entry has exactly two keys: `link`, the label, and
    `url`, an absolute `http` or `https` URL. The Overview tab of the
    driver detail page lists the links with the host name of each URL.

  Styrmin does not download the logo. The browser of each person who
  opens the driver pages loads it from the URL, so use an image host
  that you trust and that those browsers can reach. Neither URL can
  contain a username or password. When `icon` or a `links` entry is
  invalid, the driver still loads: the load leaves that value out and
  returns a warning that names the field (see
  [Warnings about spec.info values](./loading-drivers.md#warnings-about-specinfo-values)).

### Step 3: Declare the components

This is the core of the driver. For each candidate component from Step
1, add an entry under `spec.components`:

```yaml
spec:
  components:
    server:
      container: my-app
      identifier:
        label:
          app.kubernetes.io/name: my-app
    database:
      container: postgresql
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

#### The component container

The optional **`container`** field names the **component container**:
the one container in the component's pod that receives the per-component
overrides users set on a deployment: env vars,
[image overrides](../concepts-and-architecture/image-overrides.md), and
container `command` and `args` overrides. Styrmin applies them after the
chart renders. Env vars merge in by name, so every env entry the chart
ships survives and a user value with the same name replaces the chart's;
an image override replaces the container's image; a `command` or `args`
override replaces that whole list. Your `values.j2.yml` mentions none of
them.

- Use the application container's name from the rendered chart (from
  Step 1's `helm install --dry-run`), not a sidecar's.
- The name must exist in every `Deployment` and `StatefulSet` that the
  component's first identifier label selects. Styrmin matches that label
  against the workload's own `metadata.labels`, so the chart must label
  the workload, not only its pods (`podLabels` alone is not enough; many
  charts also expose a `labels` or `commonLabels` value).
- A wrong name fails the reconcile the first time any override applies
  to that component, including a `command` or `args` override alone.
  Styrmin never adds a container: the deployment fails with
  `COMPONENT_CONTAINER_NOT_FOUND` and a message naming the component and
  the container.
- Without `container`, the component accepts no component-scope env
  vars, no image override and no `command` or `args` override, and
  deployment- or environment-scope env vars skip it.

Overrides reach only this container: not other containers in the pod,
not init containers, and not chart `Job`s or `CronJob`s, including Helm
hook `Job`s. Once any
override applies, the component container moves to the first position
in the pod, which changes the default container of `kubectl logs` for
multi-container pods. In the container's env list, user entries come
before the chart's. See [Migrating env var wiring](./migrating-env-vars.md)
if your driver used the removed `component_env_vars` filter, and
[Migrating container overrides](./migrating-container-overrides.md) if
it used the retired `component_command` or `component_args` filter.

#### Replica counts: `replicas` and `singleton`

Two optional fields set how many pods (replicas) a component runs:

```yaml
spec:
  components:
    server:
      container: my-app
      replicas: 2
      identifier:
        label:
          app.kubernetes.io/name: my-app
    database:
      container: postgresql
      singleton: true
      identifier:
        label:
          app.kubernetes.io/name: postgresql
```

- **`replicas`** is the component's driver default: a whole number from 1
  to 2147483647. Styrmin sets it on `spec.replicas` of every `Deployment`
  and `StatefulSet` that the component's label selector matches, after the
  chart renders. Without `replicas`, Styrmin does not change the count, and
  the chart's count applies.
- **`singleton: true`** fixes the component's count at 1. Without
  `replicas`, Styrmin sets the count to 1, also when the chart renders
  more pods. Use it for a component that a second pod would break, such as
  a database that runs as a single primary. The flag limits the replica
  count, not the number of pods during a rolling update.

Users can set a [replica override](../concepts-and-architecture/replica-overrides.md)
on any component of a deployment, with or without these fields: the
override comes first, then `replicas`, then the chart's count. A
replica override greater than 1 on a singleton component is rejected. The
component needs no `container` for this, and `values.j2.yml` does not
pass a count to the chart, so do not add a parameter for a replica count.

The driver fails to load when it sets `singleton: true` with `replicas`
greater than 1, when `replicas` is below 1, above 2147483647, a string, a
float or a boolean, or when `singleton` is not a boolean. The error names
the field:

```text
- spec.components.database: Value error, a singleton component runs exactly 1 replica; `singleton: true` cannot be combined with `replicas: 3`
- spec.components.server.replicas: Input should be a valid integer (found '2')
```

`singleton: true` with `replicas: 1` loads. If your driver passes a replica
count parameter to the chart, see
[Migrating Replica Parameters](./migrating-replica-parameters.md#retire-a-replica-parameter-in-your-own-driver).

:::warning Existing drivers: mark single-primary components before you upgrade Styrmin

Users can set a replica override on any component as soon as the Styrmin
server runs the release that adds replica overrides, also on a driver
version loaded before it. A driver version from an earlier release marks
no component as singleton, so a user can scale a database that runs as a
single primary to 2 pods, and each pod gets its own volume and data. If
you maintain a driver outside `driver/examples/`, load a new driver
version that marks each such component with `singleton: true` before you
upgrade Styrmin, and move your deployments onto it.

:::

### Step 4: Configure backups

Per component, decide *how* it should be backed up. The choices come
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

ingress:
  enabled: true
  hosts:
    - host: "{{ services['my-app'].primary_fqdn }}"
      paths:
        - path: /
          pathType: Prefix

postgresql:
  enabled: true
  fullnameOverride: styrmin-postgresql
```

Patterns to know:

- **`{{ app.version }}`** for the application version the user picked.
- **`{{ instance.config.X }}`** for merged cluster/environment/deployment
  configuration. Use this in preference to reading the individual
  layers.
- **`{{ services['<name>'].primary_fqdn }}`** to get the auto-generated
  hostname for a service you declared (see next step).
- **No env var wiring.** User env vars reach the component container
  declared in Step 3 without any template code. Do not write them into
  the chart's `env` or `extraEnv` keys: Helm replaces lists, so that
  drops the chart's own env defaults.
- **You do not need to set the Ingress class.** Styrmin sets the class
  of every Ingress after the chart renders, or removes it when the
  environment has a dedicated ingress controller. A template that still
  sets the class gives the same Ingress, so you can remove the line in
  the driver's next version. The class that the template sets stays only
  when the environment has no dedicated ingress controller and no
  `ingress_class` is resolved. See
  [Dedicated ingress controller or shared ingress class](../concepts-and-architecture/ingress-and-networking.md#dedicated-ingress-controller-or-shared-ingress-class).

#### Container `command` and `args` overrides

A user can override the `command` or `args` of one component for one
deployment, for example to run a debug mode or change worker flags,
without forking your driver. The component container is the only
declaration this needs: Styrmin patches the override into that
container after the chart renders, whether or not the chart exposes
`command` or `args` as values. Do not pass the override to the chart in
`values.j2.yml`.

- A set `command` or `args` replaces the whole list on the component
  container. A field without an override keeps the chart's value, so an
  `args`-only override keeps the chart's `command`.
- When the user clears the override, the next reconcile brings back the
  `command` and `args` the chart renders.
- Adding or changing `command` or `args` on a component without a
  `container` is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`.

The `component_command` and `component_args` filters are retired: a
template that calls either one fails to render. `spec.container_overrides`
is removed from `driver.styrmin.yml`, and a driver file that still
contains it fails to load. See
[Migrating container overrides](./migrating-container-overrides.md) to
migrate a driver that uses them.

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
    # images[0] is the component container's image (with any image override);
    # drop a digest, then the tag ("registry:5000/app" keeps its port).
    name = images[0].split("@", 1)[0]
    repository, separator, tag = name.rpartition(":")
    image_base = repository if separator and "/" not in tag else name

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

An action that changes a resource of the chart directly, for example
with `kubectl patch`, does not keep that change on a deployment
installed with server-side apply (see
[The HelmRelease](../concepts-and-architecture/operator-and-crds.md#the-helmrelease--styrmins-other-crd)).
At the next upgrade, a field that the chart sets returns to the
chart's value, because helm-controller forces field ownership conflicts
and takes the field back. The upgrade does not fail. A field that the
chart does not set keeps the action's value. `stop_components` and
`start_components` change the component's state through Styrmin, which
applies it in its next render, so their effect lasts.

`get_component_images` returns the image of every container in the
component's pod template, with the component container's image first
when the component declares one. Take `images[0]` rather than searching for an image name: when a user
sets an image override, the first image is the override, so the
migration Job runs the user's build. The override comes from the
deployment's new configuration, so this holds even when the user sets it
in the same apply that changes the version.

See [Lifecycle hooks and actions](../concepts-and-architecture/hooks-and-actions.md)
for the full hook/mode model.

### Step 8: Parameters — only when you need them

Hardcode where you can; expose a parameter when the value genuinely
varies per deployment. Each parameter the driver declares shows up in
the UI when a user creates a deployment. A replica count is not a
parameter: declare it as `replicas` on the component (see
[Replica counts](#replica-counts-replicas-and-singleton)).

```yaml
spec:
  parameters:
    - name: storage_size
      label: "Storage size (Gi)"
      kind: integer
      default: 10
```

Values land in `{{ parameters.storage_size }}` in the template.

When a later version of your driver removes a parameter, a deployment
that changes to that version drops the parameter's value if it equals the
parameter's default in the deployment's current driver version. Any other
value rejects the change with `RETIRED_PARAMETER_VALUE`, which names the
parameter and the value. See
[Changing Driver Versions](./changing-driver-versions.md#parameters-the-target-driver-version-no-longer-declares).
A parameter without a default cannot be dropped this way: give a
parameter you may retire later a default.

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
- [ ] Each component that should receive env vars, an image override,
      or a `command` or `args` override declares a `container` that
      exists in every workload its label selects, and `values.j2.yml`
      wires none of these overrides.
- [ ] Every component that must run a single pod sets
      `singleton: true`, and every component whose count the chart does
      not set the way you want sets `replicas`.
- [ ] In a driver with components, each Helm hook `Job` that must run
      with the deployment's scheduling settings carries a component's
      first identifier label in its own `metadata.labels`.
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
