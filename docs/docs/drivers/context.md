---
title: The Context
sidebar_position: 3
description: The hierarchical structure that drivers receive at runtime — what's in it, where each value comes from, and how to use it in templates and actions.
---

## The Context

When Styrmin deploys an application, the driver needs to know things
that aren't in the driver itself: which cluster is this running on,
which environment, what namespace did Styrmin pick, what storage class
should I use, what version of the application did the user ask for.

All of that is bundled into a single object called the **Context** (more
formally, `GlobalContext`). Every Helm-values template, every
lifecycle action, and every `StyrminDeployment` CRD carries this
context. If you're writing a driver, the Context is the single most
important data structure to understand.

### Where context comes from

The Context is built — once — at the moment Styrmin decides to act on
a deployment. The server walks the database, gathers configuration from
five sources, and merges them into one object:

```text
Cluster config        ──┐
Environment config    ──┤
Deployment config     ──┼──►  GlobalContext  ──►  driver templates + actions
Driver / chart        ──┤                            +
Resolved values       ──┘                          embedded in StyrminDeployment CRD
```

Once built, the Context is **frozen** for the lifetime of that
deployment's Instance — a re-resolution only happens when something
changes and a new Instance is created. This means the driver always
sees a stable, complete picture; it never has to call back to the
server for "the latest value of X". See
[Reconciliation](../concepts-and-architecture/reconciliation.md) for why this
matters.

### Structure

The Context is a hierarchical Pydantic model. Top level:

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

Each entry is documented below.

#### `cluster`

```text
cluster:
  config:          # ClusterConfig — URLs, FQDN suffix, storage-class mappings…
  capabilities:    # dict — what this cluster can do (ingress, backups, …)
```

This is the cluster-wide configuration set once when the cluster was
registered. It includes things like `fqdn_suffix` and `standard_storage`
that nearly every driver template ends up consuming.

#### `environment`

```text
environment:
  name:            # the environment's name
  config:          # EnvironmentConfig — IP whitelist, dedicated_ingress, …
  capabilities:    # dict — what this environment can do
```

Environment-level overlay on top of the cluster. The same fields can
appear at both levels; the environment's value wins where they overlap.

#### `deployment`

```text
deployment:
  config:          # DeploymentConfig — the user's deployment-level config
```

The user-supplied deployment configuration. This is the most specific
of the three "config-bearing" layers.

#### `instance`

```text
instance:
  id:                  # the Instance ID (None for a freshly generated context)
  deployment_id:       # the parent Deployment ID
  namespace:           # the Kubernetes namespace Styrmin chose for this deployment
  release_reference:   # the Helm release name (and version reference)
  config:              # ResolvedConfig — the merged view of cluster + env + deployment
```

This is the layer most templates actually read from.
**`instance.config` is the fully-merged configuration** — cluster +
environment + deployment, with each layer overriding the one above.
**Always prefer `{{ instance.config.X }}` over reading from individual
layers** unless you specifically need to see a single layer.

`namespace` and `release_reference` are also commonly used — they tell
your template the Kubernetes namespace and Helm release identity
Styrmin picked.

#### `app`

```text
app:
  name:            # application name (e.g. "infrahub")
  version:         # the application version the user picked
  helm:            # info about the Helm chart this driver version uses
```

Use this to template the image tag, version-specific paths, or any
chart value that depends on which application version you're deploying.

#### `components`

```text
components:        # ComponentsContext, keyed by component name
```

Per-component configuration. A driver declares its components in
`driver.styrmin.yml`; this is where the resolved per-component values
end up at runtime: the component's definition under
`components.<name>.config` (including its declared `container`), its
resolved env vars under `components.<name>.env_vars.config`, its
image override under `components.<name>.image_override`, its
container `command` and `args` override under
`components.<name>.container_override`, and its replica override under
`components.<name>.replica_override`.

May be `None` if the driver has no per-component configuration.

#### Env vars are read-only data

Styrmin injects the env vars users set into each component's declared
component container after the chart renders; templates do not wire
them (see
[Creating a Driver](./creating-a-driver.md#the-component-container)).
The resolved values stay readable for other uses, such as building a
ConfigMap or switching a chart feature on:

- `instance.config.env_vars` — environment and deployment scopes merged,
  deepest wins.
- `components.<name>.env_vars.config` — environment, deployment, and
  component scopes merged, deepest wins.

Both are absent when nothing is set, so guard with
`(instance.config.env_vars or {})`. Don't write them into a chart env
key: Styrmin already injects them, and Helm's list replacement would
drop the chart's own env defaults.

#### Image overrides are read-only data

Styrmin also applies a user's
[image override](../concepts-and-architecture/image-overrides.md) to the
component container after the chart renders, so templates do not wire
it either. `components.<name>.image_override` is present only when the
user set one, and it is applied only when the component declares a
component container. Its `reference` is the stored string, with any
`{{ app.version }}` token not yet substituted. Don't write it into a
chart image key; Styrmin already sets the image.

#### Container overrides are read-only data

Styrmin applies a user's container `command` and `args` override to the
component container after the chart renders, so templates do not pass
it to the chart. `components.<name>.container_override` is present only when the user
set `command` or `args`, and it is applied only when the component
declares a component container. Its `command` and `args` are lists, and
a field the user did not set is absent. Don't write them into a chart
`command` or `args` key: Styrmin already applies them, and when no
override is set the chart key would no longer hold the chart's own
value.

#### Replica overrides are read-only data

Styrmin sets each component's replica count on its `Deployment` and
`StatefulSet` workloads after the chart renders (see
[Replica overrides](../concepts-and-architecture/replica-overrides.md)),
so templates do not pass a count to the chart.
`components.<name>.replica_override` is present only when the user set
one. The driver's own `replicas` and `singleton` are under
`components.<name>.config`, each only when the driver sets it. Don't
write either into a chart replica key: Styrmin sets `spec.replicas`
after the chart renders, which replaces any count the chart renders.

#### `parameters`

```text
parameters:        # dict[str, Any] — values the user filled in for the driver's parameters
```

If the driver declares `spec.parameters` in `driver.styrmin.yml`, the
user-supplied values show up here. Use them directly:
`{{ parameters.storage_size }}`.

#### `services`

```text
services:          # dict — declared services from the driver spec
deployed_services: # list of dicts — services as they exist in the cluster
```

`services` reflects what the driver declared under `spec.services`.
`deployed_services` is what Styrmin actually materialised. Templates
usually need `services`; actions sometimes need `deployed_services`.

#### `utilities` and `labels`

```text
utilities: [UtilityContext]   # ingress controller, etc.
labels:    {key: value}       # Kubernetes labels Styrmin applies to managed resources
```

Most drivers don't touch these directly.

### Using context in a Helm values template

The Context is exposed to your `values.j2.yml` as a Jinja namespace.
Every top-level field is reachable by name.

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

Notice the typical patterns:

- **`{{ app.X }}`** for application-level identity.
- **`{{ instance.config.X }}`** for merged configuration — this is the
  default-correct place to read from.
- **`{{ cluster.config.X }}`** only when you specifically need the
  cluster's own value, not the one the environment or the deployment
  sets. When an administrator changes the cluster config, Styrmin
  redeploys only the deployments whose `instance.config` changes, so a
  deployment that is not redeployed keeps the `cluster.config` of its
  last render.
- **No env var wiring.** User env vars reach each component's
  declared container without template code; the `component_env_vars`
  filter is removed (see
  [Migrating env var wiring](./migrating-env-vars.md)).
- **No `command` or `args` wiring.** A user's container `command` and
  `args` overrides reach each component's declared container without
  template code. The `component_command` and `component_args` filters are
  retired: a template that calls either one fails to load with
  `RETIRED_TEMPLATE_FILTER` (see
  [Migrating container overrides](./migrating-container-overrides.md)).
- **No Ingress class.** Styrmin sets the class of every Ingress after
  the chart renders, or removes it when the environment has a dedicated
  ingress controller, so the values template sets no class. See
  [Dedicated ingress controller or shared ingress class](../concepts-and-architecture/ingress-and-networking.md#dedicated-ingress-controller-or-shared-ingress-class).

### Using context in an action

Lifecycle actions get the Context too — as a Python object. The fields
match the structure above; access them by attribute:

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

Built-in primitives like `stop_components`, `start_components`, and
`execute_commands` know how to consume the Context themselves — you
usually just pass them the deployment ID and let them resolve what they
need.

### Three rules of thumb

1. **Read from `instance.config` by default.** It's the merged view
   every template should want; individual layers exist for the cases
   where you explicitly need to see a single source.
2. **Treat the Context as immutable.** It's frozen for the Instance's
   lifetime. If you find yourself wanting to mutate it, you probably
   want a new parameter or a new deployment instead.
3. **If a value isn't in the Context, it doesn't belong in the
   driver.** Drivers that reach for cluster state, environment
   variables, or live API calls break the declarative model. Add the
   value to the Context (via cluster/environment config or a driver
   parameter) instead.

### Next

- [**Creating a Driver**](./creating-a-driver.md) — write your first
  driver using the Context.
- [**Reconciliation**](../concepts-and-architecture/reconciliation.md) — why the
  Context is frozen per Instance.
