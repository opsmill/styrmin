---
title: Specification Reference
sidebar_position: 3
description: Complete reference for all Application Driver fields, versioning, and lifecycle.
---

# Driver Specification Reference

This page documents all fields available in Application Driver files.

## Driver Specification (`styrmin_driver.yaml`)

### Schema

```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: <string>               # Unique driver name (required)
spec:
  version: <string>            # Driver version (required)
  supported_versions: <string> # Semver specifier for supported app versions (required)
  info:                        # Optional metadata
    icon: <string>
    description: <string>
    authors: [<string>]
    license: <string>
    links:
      - link: <string>
        url: <string>
  helm:
    main:
      location: <string>       # OCI or HTTP URL to Helm chart (required)
      version: <string>        # Helm chart version (required)
  components:                  # Component definitions (optional)
    <component-name>:
      identifier:
        label:
          <key>: <value>       # Kubernetes label selector
      cpu: <number>            # CPU allocation (optional)
      memory: <string>         # Memory allocation (optional)
      backup:                  # Backup configuration (optional)
        enabled: <boolean>
        kind: <string>
        database_name: <string>
  services:                    # Service definitions (optional)
    - name: <string>
      kind: <string>           # Service type (e.g., "http")
      scope: <string>          # Scope (e.g., "internal", "external")
      port: <number>           # Service port
      component: <string>      # Associated component name
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `apiVersion` | string | Must be `styrmin.io/v1` |
| `kind` | string | Must be `ApplicationDriver` |
| `metadata.name` | string | Unique identifier for the driver |
| `spec.version` | string | Version string for this driver |
| `spec.supported_versions` | string | Semver specifier (e.g., `>=1.0.0,<2.0.0`) |
| `spec.helm.main.location` | string | Helm chart location — OCI or HTTP URL |
| `spec.helm.main.version` | string | Helm chart version |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `spec.info.icon` | string | Icon identifier |
| `spec.info.description` | string | Human-readable description |
| `spec.info.authors` | string[] | List of author names |
| `spec.info.license` | string | SPDX license identifier |
| `spec.info.links` | object[] | Related links (each with `link` and `url`) |
| `spec.components` | object | Component definitions (see [Components](#components)) |
| `spec.services` | object[] | Service definitions (see [Services](#services)) |

---

## Helm Values Template (`chart_values.j2.yaml`)

A Jinja2 template that generates Helm values for the deployment. The template receives a rich context object at render time.

### Context Variables

| Variable | Type | Description |
|----------|------|-------------|
| `app.name` | `str` | Application name |
| `app.version` | `str` | Application version being deployed |
| `app.helm.repository` | `str` | Helm repository URL |
| `app.helm.chart` | `str` | Helm chart name |
| `app.helm.version` | `str` | Helm chart version |
| `cluster.config.storage_class` | `str` | Default storage class |
| `cluster.config.ingress_class` | `str` | Ingress class name |
| `cluster.config.runtime_class` | `str` | Runtime class |
| `cluster.config.node_selector` | `str` | Node selector |
| `cluster.config.standard_storage.storage_class` | `str` | Standard storage class |
| `environment.config.ingress_class` | `str` | Environment-level ingress class |
| `environment.config.ip_whitelist` | `list[str]` | IP whitelist |
| `deployment.config.*` | various | Deployment-specific overrides |
| `instance.namespace` | `str` | Kubernetes namespace |
| `instance.release_reference` | `str` | Helm release name |
| `instance.deployment_id` | `UUID` | Unique deployment identifier |
| `instance.config.*` | various | Resolved configuration (merged from all layers) |
| `services['<name>'].primary_fqdn` | `str` | Primary FQDN for a named service |

### `fullnameOverride` Convention

Every `chart_values.j2.yaml` **must** set `fullnameOverride` for the main chart and all subcharts:

```yaml
fullnameOverride: styrmin-<name>
```

**Why:** Kubernetes enforces a 63-character limit on resource names. Without `fullnameOverride`, Helm generates names by combining the release name with the chart name, which can exceed this limit.

**Important:** Setting `fullnameOverride` changes the Kubernetes service name for that component. Any application configuration referencing a subchart's service must use the matching `fullnameOverride` value as the hostname.

```yaml
# Main chart
fullnameOverride: styrmin-my-app

# Subcharts
postgresql:
  fullnameOverride: styrmin-postgresql
redis:
  fullnameOverride: styrmin-redis

# App config must reference the same hostnames
env:
  DB_HOST: styrmin-postgresql
  CACHE_HOST: styrmin-redis-master
```

---

## Components

Components define the independently manageable parts of an application. Each component must have a label selector that matches Kubernetes resources.

### Schema

```yaml
components:
  <component-name>:
    identifier:
      label:
        <key>: <value>     # Kubernetes label selector (required)
    cpu: <number>           # CPU allocation (optional)
    memory: <string>        # Memory allocation (optional)
    backup:                 # Backup configuration (optional)
      enabled: <boolean>
      kind: <string>
      database_name: <string>
```

### How Components Work

1. The `identifier.label` is used to select Kubernetes resources (Deployments, StatefulSets, etc.)
2. `stop_components` scales down matching resources to zero replicas
3. `start_components` scales them back up to the original replica count
4. Component names in action primitives must match the names in the driver spec

### Example

```yaml
components:
  server:
    cpu: 4
    identifier:
      label:
        app.kubernetes.io/name: my-app
  worker:
    identifier:
      label:
        app.kubernetes.io/name: my-app-worker
  database:
    identifier:
      label:
        app.kubernetes.io/name: postgresql
    backup:
      enabled: true
      kind: postgres
      database_name: my_app
```

---

## Services

Services define network endpoints exposed by the application.

### Schema

```yaml
services:
  - name: <string>         # Service name (required)
    kind: <string>         # Service type: "http", "grpc", etc. (required)
    scope: <string>        # "internal" or "external" (required)
    port: <number>         # Service port (required)
    component: <string>    # Associated component name (required)
```

The `services` context variable in templates provides access to computed FQDNs based on these definitions. Use `services['<name>'].primary_fqdn` in your values template for ingress host configuration.

---

## Actions

Actions define custom logic that executes during application lifecycle events.

### Action Definition (`actions.yaml`)

```yaml
apiVersion: "styrmin.io/v1"
kind: ActionDefinition
metadata:
  package: <string>          # Package name (usually matches driver name)
spec:
  actions:
    - name: <string>         # Unique action name
      hook: <string>         # Lifecycle hook: "setup" or "upgrade"
      mode: <string>         # Execution phase: "pre", "core", or "post"
      description: <string>  # Human-readable description
      location: <string>     # Python function: "file.py::function_name"
      parameters: []         # Optional parameters
      image: <string>        # Optional container image
```

### Hooks

| Hook | Description |
|------|-------------|
| `setup` | Runs during initial application deployment |
| `upgrade` | Runs during application version upgrades |

### Modes

| Mode | Description |
|------|-------------|
| `pre` | Runs before the core operation |
| `core` | Replaces the default operation |
| `post` | Runs after the core operation |

### Action Primitives

These functions are available in action implementations:

#### `stop_components`

Scales down specified components to zero replicas.

```python
await stop_components(components: list[str], context: GlobalContext) -> None
```

#### `start_components`

Scales up specified components to their original replica count.

```python
await start_components(components: list[str], context: GlobalContext) -> None
```

#### `execute_commands`

Runs commands in a Kubernetes job.

```python
await execute_commands(
    commands: list[str],
    context: GlobalContext,
    image: str | None = None,
    env_from_component: str | None = None,
    labels_from_component: str | None = None,
) -> None
```

#### `upgrade_deployment_version`

Updates the deployment to target a new application version.

```python
await upgrade_deployment_version(target_version: str, context: GlobalContext) -> None
```

#### `get_component_images`

Retrieves container images used by a component.

```python
await get_component_images(component: str, context: GlobalContext) -> list[str]
```

---

## Driver Loading

When Styrmin loads a driver from a Git repository, it:

1. Clones the repository at the specified branch or tag
2. Parses and validates `styrmin_driver.yaml`
3. Reads `chart_values.j2.yaml` as a template string
4. If present, parses `actions.yaml` and loads `actions.py`
5. Stores the driver version in the database
6. Registers any actions with the workflow engine
