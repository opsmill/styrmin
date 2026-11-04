---
title: What is an application driver?
sidebar_position: 1
description: What an application driver contains and how Styrmin uses it to deploy an application.
---

## What is an application driver?

An **application driver** is a versioned, self-contained specification
of how Styrmin deploys one application. Drivers are the unit of
deployment in Styrmin: Styrmin deploys an application only through its
driver, and every deployment step comes from the driver.

If you know Helm: a driver is a Helm chart reference, plus the metadata
that Styrmin needs to deploy, observe, configure, and upgrade the
application.

### What a driver contains

A driver contains:

- **A Helm chart reference.** Either an OCI registry URL or an HTTP
  repository, pinned to a specific chart version.
- **Component definitions.** Logical parts of the application (for
  example, `server` and `task-worker`), each identified by a Kubernetes
  label selector. Styrmin starts, stops, scales, and reports the status
  of each component as a unit. Each component can name a **component
  container**: the container that receives the env vars, the
  [image override](./image-overrides.md), and the `command` and `args`
  overrides that users set on a deployment.
- **User-facing parameters.** Typed inputs (string, integer, boolean,
  enum) that the user sets when they create a deployment. The UI and the
  SDK show the parameters, and the Jinja2 values template reads them.
- **Services.** Network endpoints that the driver declares (kind, scope,
  port, component). Styrmin creates a Kubernetes `Service` for each one.
- **Lifecycle actions.** Python functions that run inside a Prefect flow
  at a hook (`setup` or `upgrade`) and a mode (`pre`, `core`, or `post`).
  Use them for migrations, seeding, smoke tests, and any other step that
  the application needs before or after its Helm release.
- **Supported application versions.** A PEP 440 version specifier of the
  application versions that this driver supports.

### Drivers, driver versions, and deployments

These three terms are different:

| Term | What it is |
|------|------------|
| **Application driver** | A named driver, identified by `metadata.name` (for example, `infrahub`). |
| **Application driver version** | One revision of a driver, with its own Helm chart, components, parameters, services, and actions. Loaded from a directory or a git repository. |
| **Deployment** | A long-lived record of intent that sets one driver _version_ and one application version in one environment, with its configuration. |

When you upgrade a deployment, you change the driver version that it
uses. A loaded driver version does not change: each change to a driver
is a new version.

A driver version is identified, among other values, by a **provenance
fingerprint**: a SHA-256 content hash for a local driver, and the
resolved git commit SHA for a git driver. Because of the fingerprint, a
reload of unchanged content changes nothing, and a change to any of the
three hashed files (`driver.styrmin.yml`, the values template,
`actions.py`) creates a new driver version, even when `spec.version` is
the same. The UI, the CLI, and the SDK show the label as
`<version>@<short-fingerprint>`. See
[Load a driver](../drivers/loading-drivers.md#reloading-a-local-driver-while-you-iterate)
for how to reload a driver while you edit it.

### File layout

A driver is a directory:

```text
my-driver/
├── driver.styrmin.yml   # required — the specification
├── values.j2.yml        # optional — Jinja2 template for Helm values
└── actions.py           # required only if the spec declares actions
```

`driver.styrmin.yml` declares the metadata, the Helm chart, the
components, the parameters, the services, _and_ the actions, which
`actions.py` implements. See
[ADR-002](https://github.com/opsmill/styrmin/blob/develop/dev/adr/adr-002-consolidate-driver-single-yaml.md)
for why the specification is one file.

A minimal example:

```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: infrahub
spec:
  version: "0.4.0"
  supported_versions: ">=1.6.0,<2.0.0"
  info:
    icon: "https://docs.infrahub.app/img/infrahub-logo.svg"
    description: "Infrahub deployment driver"
    authors: ["OpsMill"]
  helm:
    main:
      location: oci://registry.opsmill.io/charts/infrahub
      version: "1.6.0"
  components:
    server:
      identifier:
        label:
          styrmin/component: server
    task-worker:
      identifier:
        label:
          styrmin/component: task-worker
  parameters:
    - name: storage_size
      label: "Storage size (Gi)"
      kind: integer
      default: 10
  services:
    - name: web
      kind: http
      scope: external
      port: 8000
      component: server
```

The driver list page and the driver detail page show the logo
(`info.icon`), the description (`info.description`) and the links
(`info.links`) of each driver version.

[Create a driver](../drivers/creating-a-driver.md) explains how to write
one.

### How a driver becomes a deployment

Styrmin does not use a driver on disk until you load it. To run an
application:

1. **Load** the driver: Styrmin records an application driver version
   in the database, from a local directory or from a git repository.
2. **Choose an environment**: a driver is not bound to a cluster. The
   _deployment_ places the driver version in one **environment**, which
   is bound to one **cluster**.
3. **Reconcile**: the agent reads the new intent from a
   `StyrminDeployment` resource and changes the cluster to match. It
   renders the Helm values, creates the release, schedules the lifecycle
   actions, and reports the observed state to the server.

```text
Driver on disk  ──load──►  Application driver version
                                 │
                                 │  pinned by
                                 ▼
                          Deployment ── in ──► Environment ── in ──► Cluster
```

### Where to find drivers

#### Bundled examples

The Styrmin repository includes example drivers under
[`driver/examples/`](https://github.com/opsmill/styrmin/tree/develop/driver/examples):

| Driver | Purpose |
|--------|---------|
| [`infrahub`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/infrahub) | OpsMill's driver for Infrahub, the most complete example driver. |
| [`generic-app`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/generic-app) | Any single-container HTTP application, such as a Streamlit app: see [the generic-app driver](../drivers/generic-app.md). |
| [`semaphore`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/semaphore) | Driver for Semaphore UI, a web UI and API for Ansible, Terraform, and other DevOps tools. |
| [`slurpit`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/slurpit) | Slurpit network discovery driver. |

When you run [`uv run invoke start`](../installation/quickstart.md), the
bootstrap step loads `infrahub` and `semaphore`, so you can deploy an
application right after the install.

#### Loading your own

You can load any directory that follows the layout above: from a path
in the server container, or from a git repository (public or private).
See [Load a driver](../drivers/loading-drivers.md) for the steps, the
GraphQL mutations, the `styrminctl` commands, and how to configure the
token for a private repository.

The [driver overview in the Styrmin repository](https://github.com/opsmill/styrmin/blob/develop/driver/DRIVERS.md)
is the version-controlled description of the driver format.

### Next steps

- [**Load a driver**](../drivers/loading-drivers.md): load a driver from
  a local directory or a git repository.
- [**The context (GlobalContext)**](../drivers/context.md): the data
  structure that every driver template and action receives at runtime.
- [**Create a driver**](../drivers/creating-a-driver.md): write your
  first driver, step by step.
