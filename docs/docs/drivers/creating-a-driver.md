---
title: Create a driver
sidebar_position: 4
description: Write an application driver for an existing Helm chart.
---

## Create a driver

This guide writes a driver for `my-app`, a small application with two
components: a FastAPI server and a PostgreSQL database. Replace the
chart and the names with your own.

Read [What is an application driver?](../concepts-and-architecture/what-is-a-driver.md)
and [The context](./context.md) first.

### Before you start

You need:

- **A Helm chart** for the application. The chart must install on its
  own with `helm install`. Styrmin deploys and operates an existing
  chart.
- **A running Styrmin install** to load and test the driver. Use the
  [Quickstart](../installation/quickstart.md) or the
  [local vCluster install](../installation/vcluster-local.md).
- **Knowledge of the application's lifecycle**: what it stores, what an
  upgrade requires, and how to back it up. You write these procedures
  into the driver.

### Driver files

A driver is a directory with three files:

```text
my-driver/
├── driver.styrmin.yml   # required — the specification
├── values.j2.yml        # optional — Jinja2 template for the Helm values
└── actions.py           # required only if the spec declares actions
```

Write them in this order: the specification, then the values template,
then the actions, if the application needs lifecycle steps that Helm
values cannot express.

This directory is the driver directory. In git, it can be the root of a
repository, or a directory of a repository that holds other drivers:

```text
styrmin-drivers/
└── drivers/
    ├── my-driver/
    │   ├── driver.styrmin.yml
    │   ├── values.j2.yml
    │   ├── actions.py
    │   └── helpers.py      # imported by actions.py with "import helpers"
    └── other-driver/
        └── driver.styrmin.yml
```

The driver's actions run with the driver directory as their working
directory. `actions.py` can import modules from the driver directory,
such as `helpers.py` above, but not from other directories of the
repository, such as `other-driver/` or a directory at the repository
root. To share code between drivers, copy it into each driver
directory, or install it in the image that the Styrmin agent runs. The
agent runs each action as a process in its own pod, and an action's
`image` field currently has no effect (see
[Actions run from the driver directory](./loading-drivers.md#actions-run-from-the-driver-directory)).
A symlink to shared code does not work: a load fails when `actions.py`,
`driver.styrmin.yml` or `values.j2.yml` is a symlink to a path outside
the driver directory.

See [Load a driver](./loading-drivers.md#loading-a-driver-from-a-driver-directory)
for how to load a driver from a driver directory. For a driver loaded from
a local directory, the check of the driver files before each action covers
`actions.py` but not `helpers.py`, so an edit of `helpers.py` takes effect
without a new driver version (see
[Actions of a driver loaded from a local directory](./loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory)).

<!-- Keeps the anchor that earlier releases of CHANGELOG.md link to. -->
<a id="step-1-analyse-the-helm-chart"></a>

### Step 1: Analyze the Helm chart

Before you write the driver, render the chart, or install it in a test
namespace, and list the resources it creates:

```shell
helm install test-run <chart> -n test --dry-run --debug | less
kubectl get all -n test
```

Look for three things.

**The workloads**: every `Deployment`, `StatefulSet`, `Job`, or
`CronJob` that the chart creates. Styrmin may need to start, stop,
scale, or back up each of them separately. These are your candidate
**components**.

For `my-app`, the chart creates two workloads: the FastAPI server (a
`Deployment`) and a PostgreSQL primary (a `StatefulSet`).

Note any `progressDeadlineSeconds` on a chart `Deployment`. FluxCD
waits for the chart's resources with kstatus, which reports a
`Deployment` as failed after its progress deadline passes. FluxCD then
fails the change and rolls the release back. The readiness timeout of
Styrmin's operator is 270 seconds by default; when it expires, the
failed step names why the pods are not ready. With a deadline below
270 seconds, FluxCD fails the change first, so the failed step shows
FluxCD's `ProgressDeadlineExceeded` failure instead of the pods'
reason, such as `ImagePullBackOff`. The Kubernetes default deadline is
600 seconds.

**Stateful and replicated workloads**: workloads with replicas,
persistent volumes, clustering, leader election, or a required restart
order.

- **Stateful storage** (databases, caches, queues with disk): almost
  always its own component, with an application-specific backup
  strategy. A volume snapshot alone is usually not enough.
- **Replicated services** (an API server with N replicas): usually one
  component.
- **Background workers** (task queues, async processors): often a
  separate component, so that you can stop them during a migration.

For `my-app`, the FastAPI server is a stateless workload (one
component, no backup), and PostgreSQL is stateful (one component, with
the `postgres` backup strategy).

**The Helm hooks**: resources annotated `helm.sh/hook`, which Helm
creates at a given point of an install, upgrade, rollback, uninstall or
test, for example a pre-upgrade migration `Job`. The `--dry-run` output
lists them in its `HOOKS:` section, before the `MANIFEST:` section.
Styrmin applies its post-render patches to Helm hooks as it does to
the chart's other resources:

- **Styrmin's labels**: Styrmin adds them to every hook, even a hook
  without `metadata.labels`. A hook whose own `metadata.labels` include
  a component's first identifier label also gets that component's
  `styrmin/component` label.
- **The deployment's scheduling settings** (affinity, node affinity,
  tolerations, topology spread, resources and runtime class): Styrmin
  applies them to hook `Job`, `CronJob`, `Deployment`, `StatefulSet`,
  `DaemonSet` and `ReplicaSet` resources whose own `metadata.labels`
  include a component's first identifier label, with that component's
  settings. When the driver declares no components, Styrmin applies them
  to every hook of these kinds. A hook `Job` that must run on the
  deployment's nodes therefore needs the component's label on the `Job`
  itself, not only on its pod template.
- **Env var, image and container overrides, and the
  component-container check**: Styrmin applies them to a hook only when
  it is a `Deployment` or `StatefulSet` that matches a component. When
  an override applies to that component, a matching hook without the
  component container fails the install or upgrade with
  `COMPONENT_CONTAINER_NOT_FOUND`, as a template would (see
  [The component container](#the-component-container)).
- **The component's replica count** (replica override, driver default,
  or 0 pods while the component is stopped): Styrmin sets it on a hook
  `Deployment` or `StatefulSet` whose own `metadata.labels` include the
  component's identifier label (see
  [Replica overrides](../concepts-and-architecture/replica-overrides.md)).

**Result of this step:** a list of components, with what each one is
and how to back it up, and a list of the chart's Helm hooks with the
component each one matches, if any.

### Step 2: Write the driver specification

Create `driver.styrmin.yml`. The specification for `my-app`:

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: my-app              # must be unique across the Styrmin install
spec:
  version: "1"              # the driver version
  supported_versions: ">=0.1,<1.0"   # the application versions this driver supports
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

Notes:

- **`metadata.name`** is the name users see. If you change it later,
  you must re-create every deployment that uses the old name.
- **`supported_versions`** is a [PEP 440 version
  specifier](https://peps.python.org/pep-0440/#version-specifiers) of
  the application versions this driver supports. Styrmin refuses to
  deploy an application version outside this range, so a user cannot
  select a version that you have not tested.
  - Styrmin reads the application version of a deployment as a PEP 440
    version, such as `1.6.0`, `1.6.0rc1` or `2026.8.5`. It refuses a
    version in another format, such as `latest`, a commit hash or
    `1.2.3-ls45`, and the same applies to `default_version`.
  - A pre-release such as `1.6.0rc1` is outside a range unless the range
    names a pre-release. For example, `>=1.5,<2.0` excludes `1.6.0rc1`,
    and `>=1.6.0rc0,<2.0` includes it.
  - If the application uses image tags in another format, let the user
    set the tag in a driver parameter. The [generic-app
    driver](./generic-app.md) does this with `image_tag`.
- **`helm.main.location`** is a chart location that the Styrmin server
  can pass to Helm: an OCI URL (`oci://registry.example.com/charts/foo`),
  an HTTP repository URL, or a relative path in a chart directory of
  the server image.
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

For each candidate component from Step 1, add an entry under
`spec.components`:

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

The **`identifier.label`** block tells the agent which pods belong to
each component. A pod that matches all the labels in the block is part
of that component.

Each component **must** therefore have pods with a label combination
that Styrmin can match. There are two ways to do this:

- **Use the labels the chart already sets.** Many charts label pods with
  `app.kubernetes.io/name` or a similar label, and subcharts use
  different names. The `my-app` example uses these labels: the embedded
  `postgresql` chart labels its pods `app.kubernetes.io/name: postgresql`,
  and the main chart labels its pods `app.kubernetes.io/name: my-app`.
- **Add a label through chart values.** Many charts accept `podLabels`
  or `extraLabels` in their `values.yaml`. Styrmin uses the label
  `styrmin/component: <name>` for its own components. For a chart that
  does not label its workloads separately, set this label in
  `values.j2.yml`:

  ```yaml
  server:
    podLabels:
      styrmin/component: server
  worker:
    podLabels:
      styrmin/component: worker
  ```

  Then identify each component by that label.

**Match on the fewest labels that identify the pods.** One stable label
is better than two. Use labels that the chart already sets.

#### The component container

The optional **`container`** field names the **component container**:
the container in the component's pod that receives the overrides users
set on one component of a deployment. These are env vars,
[image overrides](../concepts-and-architecture/image-overrides.md), and
container `command` and `args` overrides. Styrmin applies them after the
chart renders:

- Styrmin merges env vars by name: the chart's env entries stay, and a
  user value with the same name replaces the chart's value.
- An image override replaces the container's image.
- A `command` or `args` override replaces that whole list.

Do not pass these overrides to the chart in `values.j2.yml`. To choose
the name:

- Use the name of the application container in the rendered chart (from
  the `helm install --dry-run` output of Step 1), not the name of a
  sidecar.
- The name must exist in every `Deployment` and `StatefulSet` that the
  component's first identifier label selects. Styrmin matches that label
  against the workload's own `metadata.labels`, so the chart must label
  the workload, not only its pods (`podLabels` alone is not enough; many
  charts also expose a `labels` or `commonLabels` value).
- A wrong name makes the reconciliation fail the first time any
  override applies to that component, even a `command` or `args`
  override alone. Styrmin never adds a container: the deployment fails
  with `COMPONENT_CONTAINER_NOT_FOUND` and a message that names the
  component and the container.
- Without `container`, the component accepts no component-scope env
  vars, image override, or `command` or `args` override, and Styrmin
  does not apply deployment-scope or environment-scope env vars to it.

Styrmin applies the overrides only to this container. It does not apply
them to other containers in the pod, to init containers, or to chart
`Job`s and `CronJob`s, including Helm hook `Job`s. When any override
applies, the component container moves to the first position in the
pod, which changes the default container of `kubectl logs` for pods
with several containers. In the container's env list, user entries come
before the chart's entries.

If your driver used the removed `component_env_vars` filter, see
[Migrate env vars to component containers](./migrating-env-vars.md). If
it used the retired `component_command` or `component_args` filter, see
[Migrate command and args overrides to component containers](./migrating-container-overrides.md).

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
  `replicas`, Styrmin sets the count to 1, even when the chart renders
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
[Retire a replica parameter in your own driver](./migrating-replica-parameters.md#retire-a-replica-parameter-in-your-own-driver).

:::warning Existing drivers: mark single-primary components before you upgrade Styrmin

Users can set a replica override on any component as soon as the Styrmin
server runs the release that adds replica overrides, even on a driver
version loaded before it. A driver version from an earlier release marks
no component as singleton, so a user can scale a database that runs as a
single primary to 2 pods, and each pod gets its own volume and data. If
you maintain a driver outside `driver/examples/`, load a new driver
version that marks each such component with `singleton: true` before you
upgrade Styrmin, and move your deployments onto it.

:::

### Step 4: Configure backups

Choose how to back up each component. The choices come from a fixed set
of **backup strategies**, which
[Backups and restores](../concepts-and-architecture/backups-and-restores.md)
lists and explains. Leave out the `backup` block for a stateless
component. For a stateful component, choose the strategy that matches
its storage:

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
template that produces the values file Helm receives. The template
reads the [context](./context.md), the same context that Styrmin embeds
in the `StyrminDeployment` resource.

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

Common patterns:

- **`{{ app.version }}`** for the application version the user selected.
- **`{{ instance.config.X }}`** for the merged cluster, environment, and
  deployment configuration. Use it instead of reading the individual
  layers.
- **`{{ services['<name>'].primary_fqdn }}`** for the hostname that
  Styrmin generates for a service you declare (see Step 6).
- **Do not pass env vars to the chart.** Styrmin adds user env vars to
  the component container declared in Step 3, without template code. Do
  not write them into the chart's `env` or `extraEnv` keys: Helm
  replaces lists, so the chart's own env defaults would be removed.
- **Styrmin sets the Ingress class.** Styrmin sets the class of every
  Ingress after the chart renders, or removes it when the environment
  has a dedicated ingress controller. A template that still sets the
  class produces the same Ingress, so you can remove the line in the
  driver's next version. The class that the template sets is kept only
  when the environment has no dedicated ingress controller and no
  `ingress_class` is resolved. See
  [Dedicated ingress controller or shared ingress class](../concepts-and-architecture/ingress-and-networking.md#dedicated-ingress-controller-or-shared-ingress-class).

#### Container `command` and `args` overrides

A user can override the `command` or `args` of one component for one
deployment, for example to run a debug mode or change worker flags,
without forking your driver. The override needs only the component
container: Styrmin patches the override into that container after the
chart renders, whether or not the chart exposes `command` or `args` as
values. Do not pass the override to the chart in `values.j2.yml`.

- A set `command` or `args` replaces the whole list on the component
  container. A field without an override keeps the chart's value, so an
  `args`-only override keeps the chart's `command`.
- When the user clears the override, the next reconciliation restores
  the `command` and `args` that the chart renders.
- Adding or changing `command` or `args` on a component without a
  `container` is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`.

The `component_command` and `component_args` filters are retired: a
template that calls either one fails to render. `spec.container_overrides`
is removed from `driver.styrmin.yml`, and a driver file that still
contains it fails to load. To migrate a driver that uses them, see
[Migrate command and args overrides to component containers](./migrating-container-overrides.md).

See [The context](./context.md) for all available fields.

### Step 6: Declare services

If the application accepts network connections, declare each service
under `spec.services`. Styrmin generates a hostname for each external
service, and the ingress controller routes traffic to it:

```yaml
spec:
  services:
    - name: my-app
      kind: http             # http | https | tcp
      scope: internal        # internal | external
      port: 8000
      component: server      # which component this service belongs to
```

Notes:

- **`scope: external`** turns on hostname generation for the service,
  and the application becomes reachable through the environment's
  ingress. With `internal`, the service is reachable only inside the
  cluster.
- **The hostname** of an external service has the form
  `<service-name>-<deployment-id>.<fqdn-suffix>`, and the template reads
  it from `{{ services['<service-name>'].primary_fqdn }}`.
- **The other applications of the environment** can connect to each
  declared service, internal or external, on its port. A component that
  serves no declared service is reachable from its own deployment only, so
  declare every port that other applications need.
- See [Ingress and networking](../concepts-and-architecture/ingress-and-networking.md)
  for how Styrmin uses these declarations.

### Step 7: Lifecycle actions, only when you need them

Most drivers need no actions. The Helm chart and a backup strategy per
component cover install, uninstall, backup, and restore.

You need an action when:

- **The upgrade needs steps in a fixed order.** Stop the workers, run a
  migration, start the workers, run a smoke test. This is the most
  common reason for an action.
- **Setup needs work that the chart cannot do**, such as loading
  initial data, registering a webhook, or pre-loading a cache.
- **Backup needs custom logic** because no built-in strategy fits
  (`backup.kind: action`).

Declare actions in the specification:

```yaml
spec:
  actions:
    - name: upgrade
      hook: upgrade           # setup | upgrade
      mode: core              # pre | core | post
      description: Upgrade my-app
      location: "actions.py::upgrade"
```

Implement them as Prefect flows in `actions.py`. An example for
`my-app`:

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
`execute_commands`, `upgrade_deployment_version`, …) instead of calling
the Kubernetes API. They are idempotent, tested, and the same in every
driver.

An action that changes a resource of the chart directly, for example
with `kubectl patch`, does not keep that change on a deployment
installed with server-side apply (see
[The HelmRelease](../concepts-and-architecture/operator-and-crds.md#the-helmrelease)).
At the next upgrade, a field that the chart sets returns to the
chart's value: helm-controller applies the chart with forced field
ownership, so it becomes the owner of the field again. The upgrade does
not fail. A field that the
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
for hooks and modes.

### Step 8: Parameters, only when you need them

Hardcode a value when it is the same for every deployment. Declare a
parameter only for a value that changes per deployment. The UI shows
each declared parameter when a user creates a deployment. A replica
count is not a parameter: declare it as `replicas` on the component (see
[Replica counts](#replica-counts-replicas-and-singleton)).

```yaml
spec:
  parameters:
    - name: storage_size
      label: "Storage size (Gi)"
      kind: integer
      default: 10
```

The template reads the value from `{{ parameters.storage_size }}`.

When a later version of your driver removes a parameter, a deployment
that changes to that version drops the parameter's value if it equals the
parameter's default in the deployment's current driver version. Any other
value rejects the change with `RETIRED_PARAMETER_VALUE`, which names the
parameter and the value. See
[Change a deployment's driver version](./changing-driver-versions.md#parameters-the-target-driver-version-no-longer-declares).
Styrmin cannot drop a parameter without a default this way, so give a
default to every parameter that you may retire later.

### Step 9: Load and test

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/my-app
```

(See [Load a driver](./loading-drivers.md) for the path inside the
container and for loading from a git repository.)

Then deploy:

```shell
uv run styrminctl deployments create my-app 0.1.0 <environment-id>
```

Open the deployment in the UI and check that:

- all components report `Running` when the deployment finishes;
- a backup completes and is stored in the environment's backup storage
  location (BSL);
- an upgrade to another version in `supported_versions` runs the
  upgrade action, and the new version starts without errors;
- deleting the deployment removes all of its resources.

To change the driver, edit it and run `load-local-version` again. When
`driver.styrmin.yml`, the values template, or `actions.py` changed, the
load creates a new application driver version, even when `spec.version`
is the same. Deployments keep their driver version until you upgrade
them, and the actions of a driver version loaded before the edit fail
the check of the driver files. Create or upgrade your deployments with
the new driver version (see
[Reloading a local driver while you iterate](./loading-drivers.md#reloading-a-local-driver-while-you-iterate)).

### Validation checklist

Before you use the driver in production, check that:

- [ ] Every workload in the chart maps to a declared component, or you
      decided not to expose it.
- [ ] Each component's `identifier.label` matches the pods you expect.
      Check with `kubectl get pods -l <label>=<value>`.
- [ ] Each component that should receive env vars, an image override,
      or a `command` or `args` override declares a `container` that
      exists in every workload its label selects, and `values.j2.yml`
      passes none of these overrides to the chart.
- [ ] Every component that must run a single pod sets
      `singleton: true`, and every component whose count the chart does
      not set the way you want sets `replicas`.
- [ ] In a driver with components, each Helm hook `Job` that must run
      with the deployment's scheduling settings has a component's
      first identifier label in its own `metadata.labels`.
- [ ] Every stateful component has a `backup` block with the strategy
      that matches its storage.
- [ ] Every externally reachable service is declared under
      `spec.services` with `scope: external`.
- [ ] The values template reads cluster, environment, and deployment
      settings from `{{ instance.config.X }}`, not from hardcoded values.
- [ ] A deploy, a backup, a restore, and an upgrade on a test
      environment each succeeded.
- [ ] The driver is in version control, so each version can be
      reviewed.

### Next steps

- [**The context**](./context.md) — the fields your template and
  actions receive.
- [**Lifecycle hooks and actions**](../concepts-and-architecture/hooks-and-actions.md) —
  hooks, modes, and the available primitives.
- [**Backups and restores**](../concepts-and-architecture/backups-and-restores.md) —
  every backup strategy and what it does.
- [**Load a driver**](./loading-drivers.md) — how to load your driver
  from a git repository or a custom image.
