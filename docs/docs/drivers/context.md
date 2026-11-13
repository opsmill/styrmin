---
title: The context (GlobalContext)
sidebar_label: The context
sidebar_position: 3
description: The hierarchical structure that drivers receive at runtime — what's in it, where each value comes from, and how to use it in templates and actions.
---

## The context (GlobalContext)

A driver's templates and actions use values that are not in the driver:
the cluster, the environment, the namespace that Styrmin chose, the
storage class, and the application version that the user requested.

Styrmin puts these values in one object, the **context**
(`GlobalContext` in code). Every Helm values template and every
lifecycle action receives it, and every `StyrminDeployment` resource
contains it. Driver templates and actions read most of their values
from the context.

### Where the context comes from

Styrmin builds the context once, when it creates an instance of a
deployment. The server reads configuration from five sources and merges
them into one object:

```text
Cluster config        ──┐
Environment config    ──┤
Deployment config     ──┼──►  GlobalContext  ──►  driver templates + actions
Driver / chart        ──┤                            +
Resolved values       ──┘                          embedded in StyrminDeployment
```

The context does not change during the lifetime of the instance. When
something changes, Styrmin creates a new instance with a new context.
Templates and actions therefore read one consistent set of values, and
do not query the server for the latest value. See
[Reconciliation](../concepts-and-architecture/reconciliation.md) for why
this matters.

### Structure

The context is a hierarchical Pydantic model. Top level:

```text
GlobalContext
├── cluster        ── cluster-level config + capabilities
├── environment    ── environment-level config + capabilities (overrides cluster)
├── deployment     ── deployment-level config (overrides environment)
├── instance       ── the merged config + namespace + Helm release name
├── app            ── application name, version, Helm chart info
├── components     ── per-component config (optional)
├── parameters     ── user-supplied parameter values
├── services       ── declared services (from the driver spec)
├── deployed_services  ── services as they exist in the cluster
├── utilities      ── per-cluster utility info (ingress, etc.)
└── labels         ── Kubernetes labels Styrmin will apply
```

The sections below describe each entry.

#### `cluster`

```text
cluster:
  config:          # ClusterConfig — URLs, FQDN suffix, storage-class mappings…
  capabilities:    # dict — what this cluster can do (ingress, backups, …)
```

The cluster configuration, set when the cluster is created and changed
with [`styrminctl clusters update`](../reference/styrminctl.md#clusters-update--change-a-clusters-config).
It includes values such as `fqdn_suffix` and `standard_storage` that most
driver templates use.

#### `environment`

```text
environment:
  name:            # the environment's name
  config:          # EnvironmentConfig — IP whitelist, dedicated_ingress, …
  capabilities:    # dict — what this environment can do
```

The environment configuration, which overrides the cluster
configuration. A field can be set at both levels; where it is, the
environment's value applies.

When the environment has a backup storage location,
`capabilities.backup.velero.storage_location` is the name of the
location's Velero `BackupStorageLocation` object,
`styrmin-bsl-<location id>`. Renaming the location does not change it.

#### `deployment`

```text
deployment:
  config:          # DeploymentConfig — the user's deployment-level config
```

The deployment configuration that the user set. It is the most specific
of the three configuration layers.

#### `instance`

```text
instance:
  id:                  # the instance ID (None for a freshly generated context)
  deployment_id:       # the ID of the parent deployment
  namespace:           # the Kubernetes namespace Styrmin chose for this deployment
  release_reference:   # the Helm release name (and version reference)
  config:              # ResolvedConfig — the merged view of cluster + env + deployment
```

Most templates read from this layer. **`instance.config` is the merged
configuration** of the cluster, the environment, and the deployment,
where each layer overrides the one above it. **Read
`{{ instance.config.X }}` instead of the individual layers**, unless you
need the value of one layer.

Templates also often read `namespace` and `release_reference`: the
Kubernetes namespace and the Helm release name that Styrmin chose.

#### `app`

```text
app:
  name:            # application name (e.g. "infrahub")
  version:         # the application version the user picked
  helm:            # info about the Helm chart this driver version uses
```

Use it for the image tag, for version-specific paths, or for any chart
value that depends on the application version you deploy.

#### `components`

```text
components:        # ComponentsContext, keyed by component name
```

The configuration of each component. A driver declares its components
in `driver.styrmin.yml`, and Styrmin puts the resolved values of each
component here:

- `components.<name>.config`: the component's definition, including its
  declared `container`
- `components.<name>.env_vars.config`: its resolved env vars
- `components.<name>.image_override`: its image override
- `components.<name>.container_override`: its container `command` and
  `args` override
- `components.<name>.replica_override`: its replica override

`components` is `None` when the driver has no per-component
configuration.

#### Env vars are read-only data

After the chart renders, Styrmin adds the env vars that users set to
each component's declared component container, so templates do not pass
them to the chart (see
[Create a driver](./creating-a-driver.md#the-component-container)).
The resolved values stay readable for other uses, such as building a
ConfigMap or enabling a chart feature:

- `instance.config.env_vars`: the environment and deployment scopes
  merged, where the most specific scope wins.
- `components.<name>.env_vars.config`: the environment, deployment, and
  component scopes merged, where the most specific scope wins.

Both are absent when no env var is set, so write
`(instance.config.env_vars or {})`. Do not write them into a chart env
key: Styrmin already adds them, and because Helm replaces lists, the
chart's own env defaults would be removed.

#### Image overrides are read-only data

After the chart renders, Styrmin also applies a user's
[image override](../concepts-and-architecture/image-overrides.md) to the
component container, so templates do not pass it to the chart either.
`components.<name>.image_override` is present only when the user set
one, and Styrmin applies it only when the component declares a
component container. Its `reference` is the stored string, with any
`{{ app.version }}` token not yet replaced. Do not write it into a
chart image key: Styrmin already sets the image.

#### Container overrides are read-only data

After the chart renders, Styrmin applies a user's container `command`
and `args` override to the component container, so templates do not
pass it to the chart. `components.<name>.container_override` is present
only when the user set `command` or `args`, and Styrmin applies it only
when the component declares a component container. Its `command` and
`args` are lists, and a field that the user did not set is absent. Do
not write them into a chart `command` or `args` key: Styrmin already
applies them, and when no override is set, the chart key would no
longer hold the chart's own value.

#### Replica overrides are read-only data

After the chart renders, Styrmin sets each component's replica count on
its `Deployment` and `StatefulSet` workloads (see
[Replica overrides](../concepts-and-architecture/replica-overrides.md)),
so templates do not pass a count to the chart.
`components.<name>.replica_override` is present only when the user set
one. The driver's own `replicas` and `singleton` are under
`components.<name>.config`, each only when the driver sets it. Do not
write either into a chart replica key: Styrmin sets `spec.replicas`
after the chart renders, which replaces any count the chart renders.

#### `parameters`

```text
parameters:        # dict[str, Any] — values the user filled in for the driver's parameters
```

When the driver declares `spec.parameters` in `driver.styrmin.yml`,
`parameters` contains the values that the user set. Use them directly:
`{{ parameters.storage_size }}`.

#### `services`

```text
services:          # dict — declared services from the driver spec
deployed_services: # list of dicts — services as they exist in the cluster
```

`services` contains the services that the driver declares under
`spec.services`. `deployed_services` contains the services that Styrmin
created in the cluster. Templates usually read `services`; actions
sometimes read `deployed_services`.

Each entry of `services`, keyed by service name, has these keys:

- `host`, `port`, `kind` and `url`: how to connect to the service inside the
  cluster.
- `primary_fqdn`: the application address,
  `<driver name>-<deployment id>.<fqdn suffix>`, or `None` without a suffix.
  It is the same for every service of a deployment.
- `human_readable_fqdn`: the readable host,
  `<service name>-<environment name>.<fqdn suffix>`, or `None` without a
  suffix. When the deployment has a
  [service ingress override](../concepts-and-architecture/service-ingress-overrides.md)
  for the service, the suffix is the override's suffix.
- `ingress_class`: the effective ingress class of the service, the override's
  class when there is one.
- `overridden`: `true` when the service has an override with at least one field
  set.

Styrmin builds the Ingress of each external service, so a template does not
render one for it. See
[Declare services](./creating-a-driver.md#step-6-declare-services).

#### `utilities` and `labels`

```text
utilities: [UtilityContext]   # ingress controller, etc.
labels:    {key: value}       # Kubernetes labels Styrmin applies to managed resources
```

Most drivers do not read these.

### Using the context in a Helm values template

Your `values.j2.yml` receives the context as Jinja variables: each
top-level field is available by name.

A minimal example:

```yaml
# values.j2.yml
fullnameOverride: styrmin-{{ app.name }}

image:
  repository: {{ app.name }}
  tag: "{{ app.version }}"

ingress:
  enabled: true
  hosts:
    - host: "{{ app.name }}-{{ instance.deployment_id }}.{{ instance.config.fqdn_suffix }}"

storage:
  storageClassName: "{{ instance.config.standard_storage.storage_class }}"
```

The example shows these patterns:

- **`{{ app.X }}`** for the application name and version.
- **`{{ instance.config.X }}`** for the merged configuration. Read from
  it by default.
- **`{{ cluster.config.X }}`** only when you need the cluster's own
  value, not the value that the environment or the deployment sets. When
  an administrator changes the cluster config, Styrmin redeploys only the
  deployments whose `instance.config` changes, so a deployment that is
  not redeployed keeps the `cluster.config` of its last render.
- **Do not pass env vars to the chart.** User env vars reach each
  component's declared container without template code. The
  `component_env_vars` filter is removed (see
  [Migrate env vars to component containers](./migrating-env-vars.md)).
- **Do not pass `command` or `args` to the chart.** A user's container
  `command` and `args` overrides reach each component's declared
  container without template code. The `component_command` and
  `component_args` filters are retired: a template that calls either one
  fails to load with `RETIRED_TEMPLATE_FILTER` (see
  [Migrate command and args overrides to component containers](./migrating-container-overrides.md)).
- **You do not need to set the Ingress class.** Styrmin sets the class
  of every Ingress after the chart renders, or removes it when the
  environment has a dedicated ingress controller. A template that still
  sets the class gives the same Ingress, so you can remove the line in
  the driver's next version. The class that the template sets stays only
  when the environment has no dedicated ingress controller and no
  `ingress_class` is resolved. See
  [Dedicated ingress controller or shared ingress class](../concepts-and-architecture/ingress-and-networking.md#dedicated-ingress-controller-or-shared-ingress-class).

### Using the context in an action

Lifecycle actions receive the context as a Python object. Its fields
match the structure above; read them as attributes:

```python
from prefect import flow
from styrmin_backend.actions import GlobalContext

@flow
async def post_setup(context: GlobalContext) -> None:
    namespace = context.instance.namespace
    app_version = context.app.version
    ingress_class = context.instance.config.ingress_class
    # … use them to compose subsequent calls
```

Built-in primitives such as `stop_components`, `start_components`, and
`execute_commands` take the context as an argument and read the values
they need from it, such as the deployment ID:

```python
await stop_components(components=["server"], context=context)
```

### Rules for reading the context

1. **Read from `instance.config` by default.** It holds the merged
   configuration, which most templates need. Read an individual layer
   only when you need the value of that layer.
2. **Do not change the context.** It stays the same for the lifetime of
   the instance. To change a value, add a parameter or create a new
   deployment.
3. **Read values only from the context.** A driver that reads cluster
   state, environment variables, or live APIs can render differently for
   the same instance, which breaks the declarative model. Add the value
   to the context through the cluster or environment configuration, or
   through a driver parameter.

### Next steps

- [**Create a driver**](./creating-a-driver.md): write your first driver
  with the context.
- [**Reconciliation**](../concepts-and-architecture/reconciliation.md):
  why the context does not change during the lifetime of an instance.
