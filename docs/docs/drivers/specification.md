---
title: Specification Reference
sidebar_position: 3
description: Complete reference for all Application Driver fields, versioning, and lifecycle.
---

## Driver Specification Reference

This page documents all fields available in Application Driver files.

### Driver Specification (`driver.styrmin.yml`)

The specification file defines the driver metadata, supported versions, Helm chart location, component definitions, service declarations, parameters, and actions — all in a single file.

#### Schema

```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: <string>               # Unique driver name (required)
spec:
  version: <string>            # Driver version (required)
  supported_versions: <string> # Semver specifier for supported app versions (required)
  default_version: <string>    # Default app version (optional, must satisfy supported_versions)
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
      # Additional fields allowed (cpu, memory, etc.)
  parameters:                  # Configurable parameters (optional)
    - name: <string>
      label: <string>
      kind: <string>           # string, integer, boolean, or enum
      default: <any>
      values: [<string>]       # Required for enum kind
  services:                    # Service definitions (optional)
    - name: <string>           # DNS label format
      kind: <string>           # http, https, tcp, or udp
      scope: <string>          # internal or external
      port: <number>           # 1-65535
      component: <string>      # Must reference a defined component
  actions:                     # Action declarations (optional)
    - name: <string>           # Unique action name
      hook: <string>           # Lifecycle hook: "setup" or "upgrade"
      mode: <string>           # Execution phase: "pre", "core", or "post"
      description: <string>
      location: <string>       # Python function: "file.py::function_name"
      parameters: []           # Optional parameters
      image: <string>          # Optional container image
```

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `apiVersion` | string | Must be `styrmin.io/v1` |
| `kind` | string | Must be `ApplicationDriver` |
| `metadata.name` | string | Unique identifier for the driver |
| `spec.version` | string | Version string for this driver |
| `spec.supported_versions` | string | Semver specifier (e.g., `>=1.0.0,<2.0.0`) |
| `spec.helm.main.location` | string | Helm chart location — OCI or HTTP URL |
| `spec.helm.main.version` | string | Helm chart version |

#### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `spec.default_version` | string | Default application version; must satisfy `supported_versions` |
| `spec.info.icon` | string | Icon identifier |
| `spec.info.description` | string | Human-readable description |
| `spec.info.authors` | string[] | List of author names |
| `spec.info.license` | string | SPDX license identifier |
| `spec.info.links` | object[] | Related links (each with `link` and `url`) |
| `spec.components` | object | Component definitions (see [Components](#components)) |
| `spec.parameters` | object[] | Configurable parameters (see [Parameters](#parameters)) |
| `spec.services` | object[] | Service definitions (see [Services](#services)) |
| `spec.actions` | object[] | Action declarations (see [Actions](#actions)) |

---

### Helm Values Template (`values.j2.yml`)

A Jinja2 template that generates Helm values for the deployment. The template receives a rich context object at render time.

#### Context Variables

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
| `parameters.*` | various | User-provided parameter values (e.g., `parameters.docker_image`) |
| `services['<name>'].primary_fqdn` | `str` | Primary FQDN for a named service |
| `services['<name>'].human_readable_fqdn` | `str` | Human-readable FQDN for display |

#### `fullnameOverride` Convention

Every `values.j2.yml` **must** set `fullnameOverride` for the main chart and all subcharts:

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

### Components

Components define the independently manageable parts of an application. Each component must have a label selector that matches Kubernetes resources.

#### Schema

```yaml
components:
  <component-name>:
    identifier:
      label:
        <key>: <value>         # Kubernetes label selector (required)
    cpu: <number>               # CPU allocation (optional)
    memory: <string>            # Memory allocation (optional)
    backup:                     # Backup configuration (optional)
      enabled: <boolean>
      kind: <string>            # disk, mariadb, mongodb, postgres, neo4j, or action
      database_name: <string>   # Required for database kinds
      volume: <string>          # For disk kind (mutually exclusive with volumes)
      volumes: [<string>]       # For disk kind (mutually exclusive with volume)
      credentials_secret: <string>  # Kubernetes secret name (optional)
```

#### How Components Work

1. The `identifier.label` is used to select Kubernetes resources (Deployments, StatefulSets, etc.)
2. `stop_components` scales down matching resources to zero replicas
3. `start_components` scales them back up to the original replica count
4. Component names in action primitives must match the names in the driver spec

#### Example

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

#### Backup Configuration

Components can declare backup configurations. The `kind` field determines the backup strategy:

| Kind | Description | Required Fields |
|------|-------------|-----------------|
| `disk` | Generic volume backup | At least one of `volume` or `volumes` |
| `postgres` | PostgreSQL database backup | `database_name` |
| `mariadb` | MariaDB database backup | `database_name` |
| `mongodb` | MongoDB database backup | `database_name` (optional) |
| `neo4j` | Neo4j database backup | `database_name` (optional) |
| `action` | Custom action-based backup | Requires `backup` and `restore` action hooks |

---

### Parameters

Parameters allow drivers to declare typed configuration values that users provide when deploying an application. Parameters are accessible in the values template via `{{ parameters.<name> }}`.

#### Schema

```yaml
parameters:
  - name: <string>             # Parameter name (unique, required)
    label: <string>            # Human-readable label (required)
    kind: <string>             # Type: string, integer, boolean, or enum (required)
    default: <any>             # Default value (optional, must match kind)
    values: [<string>]         # Allowed values (required for enum kind only)
```

#### Supported Types

| Kind | Type | Notes |
|------|------|-------|
| `string` | `str` | Default type |
| `integer` | `int` | Booleans are not accepted as integers |
| `boolean` | `bool` | Strict boolean type |
| `enum` | `str` | Requires a non-empty `values` list; default must be in the list |

#### Example

```yaml
parameters:
  - name: docker_image
    kind: string
    label: "Docker image to use"
    default: "my-registry.io/my-app"
  - name: replicas
    kind: integer
    label: "Number of server replicas"
    default: 2
  - name: enable_debug
    kind: boolean
    label: "Enable debug mode"
    default: false
  - name: log_level
    kind: enum
    label: "Log level"
    default: "info"
    values: ["debug", "info", "warning", "error"]
```

#### Validation Rules

- Parameter names must be unique within a driver
- For `enum` kind, the `values` list must be non-empty
- If `default` is specified, it must match the declared `kind`
- For `enum`, the `default` must be one of the values in the `values` list
- Non-enum kinds cannot have a `values` field

---

### Services

Services define network endpoints exposed by the application. Styrmin uses service definitions to compute FQDNs for ingress and service discovery.

#### Schema

```yaml
services:
  - name: <string>             # Service name, DNS label format (required)
    kind: <string>             # Protocol: http, https, tcp, or udp (required)
    scope: <string>            # Accessibility: internal or external (required)
    port: <number>             # Port number, 1-65535 (required)
    component: <string>        # Associated component name (required)
```

#### Validation Rules

- Service names must be unique within a driver
- Service names must be valid DNS labels (lowercase alphanumeric and hyphens, max 63 characters)
- The `component` field must reference a component defined in the driver
- Port must be in the range 1-65535

#### Template Access

The `services` context variable in templates provides access to computed FQDNs:

```yaml
# In values.j2.yml
ingress:
  hosts:
    - host: "{{ services['my-app'].primary_fqdn }}"
```

Each service exposes:

- `primary_fqdn` — Primary FQDN for the service
- `human_readable_fqdn` — Human-readable FQDN for display purposes

---

### Actions

Actions define custom logic that executes during application lifecycle events. Actions are declared inline in `driver.styrmin.yml` under `spec.actions` and implemented in `actions.py`.

#### Action Declaration

```yaml
spec:
  actions:
    - name: <string>           # Unique action name
      hook: <string>           # Lifecycle hook: "setup" or "upgrade"
      mode: <string>           # Execution phase: "pre", "core", or "post"
      description: <string>    # Human-readable description
      location: <string>       # Python function: "file.py::function_name"
      parameters: []           # Optional parameters
      image: <string>          # Optional container image
```

#### Hooks

| Hook | Description |
|------|-------------|
| `setup` | Runs during initial application deployment |
| `upgrade` | Runs during application version upgrades |

#### Modes

| Mode | Description |
|------|-------------|
| `pre` | Runs before the core operation |
| `core` | Replaces the default operation |
| `post` | Runs after the core operation |

#### Action Primitives

These functions are available in action implementations:

##### `stop_components`

Scales down specified components to zero replicas.

```python
await stop_components(components: list[str], context: GlobalContext) -> None
```

##### `start_components`

Scales up specified components to their original replica count.

```python
await start_components(components: list[str], context: GlobalContext) -> None
```

##### `execute_commands`

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

##### `upgrade_deployment_version`

Updates the deployment to target a new application version.

```python
await upgrade_deployment_version(target_version: str, context: GlobalContext) -> None
```

##### `get_component_images`

Retrieves container images used by a component.

```python
await get_component_images(component: str, context: GlobalContext) -> list[str]
```

---

### Driver Loading

When Styrmin loads a driver from a Git repository, it:

1. Clones the repository at the specified branch or tag
2. Parses `driver.styrmin.yml` and validates the schema (including embedded action declarations)
3. Reads `values.j2.yml` as a template string (if present)
4. If actions are declared, loads and validates `actions.py` to ensure all referenced functions exist
5. Stores the driver version in the database
6. Registers any actions with the workflow engine
