---
title: Creating a Driver
sidebar_position: 2
description: Step-by-step guide to creating a new Application Driver for Styrmin.
---

# Creating a Driver

This guide walks you through creating an Application Driver from scratch. By the end, you'll have a fully functional driver that can deploy an application through Styrmin.

## Prerequisites

- A running Styrmin instance (see [Installation guides](../category/installation))
- A Helm chart for the application you want to deploy
- Basic familiarity with YAML and Jinja2 templates

## Step 1: Create the Driver Directory

Create a new directory for your driver:

```bash
mkdir my-app-driver
cd my-app-driver
```

## Step 2: Write the Driver Specification

Create `driver.styrmin.yml` — the single specification file that defines everything about your driver:

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: my-app
spec:
  version: "1"
  supported_versions: ">=1.0.0,<2.0.0"
  info:
    description: My application driver
    authors: [my-team]
    license: Apache-2.0
  helm:
    main:
      location: oci://my-registry.io/charts/my-app
      version: 1.0.0
  components:
    server:
      identifier:
        label:
          app.kubernetes.io/name: my-app
  services:
    - name: my-app
      kind: http
      scope: internal
      port: 8000
      component: server
```

### Key Fields

- **`metadata.name`** — Unique name for your driver
- **`spec.version`** — Version of the driver itself (not the application)
- **`spec.supported_versions`** — Semver range of application versions this driver supports
- **`spec.helm.main.location`** — OCI or HTTP URL to the Helm chart
- **`spec.helm.main.version`** — Helm chart version to use
- **`spec.components`** — Define the manageable parts of your application
- **`spec.services`** — Declare network services the application exposes

## Step 3: Define Services

Services declare network endpoints so Styrmin can compute FQDNs for ingress and service discovery:

```yaml
services:
  - name: my-app
    kind: http          # http, https, tcp, or udp
    scope: internal     # internal or external
    port: 8000
    component: server   # must reference a defined component
```

The computed FQDNs are available in your values template as `{{ services['my-app'].primary_fqdn }}`.

## Step 4: Define Parameters (Optional)

Parameters allow users to customize deployments without modifying the driver:

```yaml
parameters:
  - name: docker_image
    kind: string
    label: "Docker image to use"
    default: "my-registry.io/my-app"
  - name: replicas
    kind: integer
    label: "Number of replicas"
    default: 2
```

Supported parameter types: `string`, `integer`, `boolean`, `enum`. For `enum`, provide a `values` list.

Parameters are available in your values template as `{{ parameters.docker_image }}`.

## Step 5: Create the Values Template

Create `values.j2.yml` — a Jinja2 template that generates Helm values:

```yaml
fullnameOverride: styrmin-my-app

image:
  repository: "{{ parameters.docker_image }}"
  tag: "{{ app.version }}"

ingress:
  enabled: true
  className: "{{ instance.config.ingress_class }}"
  hosts:
    - host: "{{ services['my-app'].primary_fqdn }}"
      paths:
        - path: /
          pathType: Prefix

resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: "2"
    memory: 2Gi
```

### Important: `fullnameOverride`

Every values template **must** set `fullnameOverride` using the pattern `styrmin-<name>`. This prevents Kubernetes resource name conflicts caused by Helm's default naming, which combines the release name with the chart name and can exceed the 63-character limit.

If your chart has subcharts, set `fullnameOverride` for each one:

```yaml
fullnameOverride: styrmin-my-app

postgresql:
  fullnameOverride: styrmin-postgresql
redis:
  fullnameOverride: styrmin-redis
```

### Available Template Variables

The template has access to these context variables:

| Variable | Description |
|----------|-------------|
| `app.version` | Application version being deployed |
| `app.helm.version` | Helm chart version |
| `cluster.config.storage_class` | Default storage class |
| `cluster.config.ingress_class` | Ingress class name |
| `instance.namespace` | Kubernetes namespace |
| `instance.config.*` | Resolved configuration (merged from cluster, environment, deployment) |
| `parameters.*` | User-provided parameter values |
| `services['name'].primary_fqdn` | Service FQDN for ingress |

See the [Specification Reference](./specification.md#context-variables) for the complete list.

## Step 6: Add Lifecycle Actions (Optional)

If your application needs custom logic during setup or upgrades, declare actions inline in `driver.styrmin.yml`:

```yaml
spec:
  # ... other spec fields ...
  actions:
    - name: upgrade
      hook: upgrade
      mode: core
      description: Upgrade My App
      location: "actions.py::upgrade"
```

And implement the action in `actions.py`:

```python
from styrmin_backend.actions import (
    GlobalContext,
    stop_components,
    start_components,
    execute_commands,
    upgrade_deployment_version,
)
from prefect import flow, get_run_logger


@flow
async def upgrade(context: GlobalContext, target_version: str):
    logger = get_run_logger()
    logger.info(f"Upgrading my-app to {target_version}...")

    # Stop the application server
    await stop_components(components=["server"], context=context)

    # Update the deployment version
    await upgrade_deployment_version(target_version=target_version, context=context)

    # Run database migrations
    await execute_commands(
        ["my-app", "migrate"],
        image=f"my-registry.io/my-app:{target_version}",
        context=context,
    )

    # Restart the server
    await start_components(components=["server"], context=context)
    logger.info("Upgrade complete.")
```

### Hooks and Modes

| Hook | When it runs |
|------|-------------|
| `setup` | During initial application deployment |
| `upgrade` | During application version upgrades |

| Mode | Execution phase |
|------|----------------|
| `pre` | Before the core operation |
| `core` | Replaces the default operation |
| `post` | After the core operation |

## Step 7: Register the Driver

Load your driver into Styrmin by pointing it at your driver's Git repository:

```bash
styrmin driver load --repo https://github.com/my-org/my-app-driver --branch main
```

Styrmin will clone the repository, validate the driver specification, and register it for use.

## Final Directory Structure

```
my-app-driver/
├── driver.styrmin.yml    # Driver specification (includes action declarations)
├── values.j2.yml         # Helm values template
└── actions.py            # Action implementations (optional)
```

## Next Steps

- Review the [Specification Reference](./specification.md) for all available fields
- See a [complete example](./example-walkthrough.md) of a working driver
- Learn about [Components](./specification.md#components) for advanced lifecycle management
