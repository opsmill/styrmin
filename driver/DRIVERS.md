# Application Drivers

Application Drivers are versioned deployment specifications that define how applications should be deployed, configured, and managed on Kubernetes clusters through Styrmin.

## Overview

A driver provides Styrmin with all the information needed to:

- Deploy an application using Helm charts
- Generate dynamic configuration values using templates
- Define application components for lifecycle management
- Execute custom actions during setup and upgrade workflows

## File Structure

A driver is a directory containing the following files:

| File | Required | Description |
|------|----------|-------------|
| `driver.styrmin.yml` | **Yes** | Driver specification (includes action declarations) |
| `values.j2.yml` | No | Jinja2 template for Helm values |
| `actions.py` | No* | Python implementation of actions |

> \* Required if actions are declared in `driver.styrmin.yml`.

## Driver Specification (`driver.styrmin.yml`)

The specification file defines the driver metadata, supported versions, Helm chart location, component definitions, and action declarations — all in a single file.

### Schema

```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: <string>           # Unique driver name
spec:
  version: <string>        # Driver version
  supported_versions: <string>  # Semver specifier for supported app versions
  info:                    # Optional metadata
    icon: <string>
    description: <string>
    authors: [<string>]
    license: <string>
    links:
      - link: <string>
        url: <string>
  helm:
    main:
      location: <string>   # OCI or HTTP URL to Helm chart
      version: <string>    # Helm chart version
  components:              # Optional component definitions
    <component-name>:
      identifier:
        label:
          <key>: <value>   # Kubernetes label selector
      # Additional fields allowed (cpu, memory, etc.)
  parameters:              # Optional configurable parameters
    - name: <string>
      label: <string>
      kind: <string>       # string, integer, boolean, enum
      default: <any>
  services:                # Optional service definitions
    - name: <string>
      kind: <string>
      scope: <string>
      port: <integer>
      component: <string>
  actions:                 # Optional action declarations
    - name: <string>       # Unique action name
      hook: <string>       # Lifecycle hook: "setup" or "upgrade"
      mode: <string>       # Execution phase: "pre", "core", or "post"
      description: <string>
      location: <string>   # Python function reference: "file.py::function"
      parameters: []       # Optional parameters
      image: <string>      # Optional container image for execution
```

### Required Fields

| Field | Description |
|-------|-------------|
| `apiVersion` | Must be `styrmin.io/v1` |
| `kind` | Must be `ApplicationDriver` |
| `metadata.name` | Unique identifier for the driver |
| `spec.version` | Version string for this driver |
| `spec.supported_versions` | Semver specifier (e.g., `>=1.1.5,<=1.2.0`) |
| `spec.helm.main.location` | Helm chart location (OCI or HTTP URL) |
| `spec.helm.main.version` | Helm chart version |

### Example

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: infrahub
spec:
  version: "1"
  supported_versions: ">=1.5,<1.9"
  info:
    icon: xxxx
    description: Next generation source of truth for infrastructure management
    authors: [fatih]
    license: Apache-2.0
    links:
      - link: Homepage
        url: 'https://www.opsmill.com/'
      - link: Documentation
        url: 'https://docs.infrahub.app'
      - link: Github
        url: 'https://github.com/opsmill/infrahub'
  helm:
    main:
      location: oci://registry.opsmill.io/opsmill/chart/infrahub
      version: 4.16.3
  components:
    server:
      cpu: 4
      identifier:
        label:
          service: infrahub-server
    task-worker:
      identifier:
        label:
          service: infrahub-task-worker
    database:
      identifier:
        label:
          infrahub/service: database
    cache:
      identifier:
        label:
          infrahub/service: cache
    message-queue:
      identifier:
        label:
          infrahub/service: message-queue
    task-manager:
      identifier:
        label:
          app.kubernetes.io/name: prefect-server
  services:
    - name: infrahub
      kind: http
      scope: internal
      port: 8000
      component: server
    - name: task-manager
      kind: http
      scope: internal
      port: 4200
      component: task-manager
  actions:
    - name: upgrade
      hook: upgrade
      mode: core
      description: Upgrade Infrahub
      location: "actions.py::upgrade"

    - name: pre_setup
      hook: setup
      mode: pre
      description: Initial Setup of Infrahub
      location: "actions.py::pre_setup"

    - name: post_setup
      hook: setup
      mode: post
      description: Initial Setup of Infrahub
      location: "actions.py::post_setup"
```

## Helm Values Template (`values.j2.yml`)

A Jinja2 template that generates Helm values for the deployment. The template has access to a context object containing deployment, cluster, environment, and application information.

### Context Variables

The template receives a context object with the following structure:

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
| `instance.config.*` | various | Resolved configuration (merged from cluster, environment, deployment) |
| `parameters.*` | various | User-provided parameter values (e.g., `parameters.docker_image`) |
| `services['<name>'].primary_fqdn` | `str` | Primary FQDN for a named service |
| `services['<name>'].human_readable_fqdn` | `str` | Human-readable FQDN for display |

### Naming Convention (`fullnameOverride`)

Every `values.j2.yml` **must** set `fullnameOverride` for the main chart and all subcharts, using the pattern:

```yaml
fullnameOverride: styrmin-<name>
```

Where `<name>` is the name of the upstream chart or component (e.g. `infrahub`, `postgresql`, `neo4j`).

**Why:** Kubernetes enforces a 63-character limit on resource names. Without `fullnameOverride`, Helm generates names by combining the release name with the chart name, which can easily exceed this limit in Styrmin deployments.

**Important:** Setting `fullnameOverride` changes the Kubernetes service name for that component. Any application configuration that references a subchart's service (e.g. database host, cache address, message queue URL) **must** use the matching `fullnameOverride` value as the hostname.

**Example for a chart with subcharts:**

```yaml
# Main chart
fullnameOverride: styrmin-infrahub

# Subcharts
neo4j:
  fullnameOverride: styrmin-neo4j
redis:
  fullnameOverride: styrmin-cache
rabbitmq:
  fullnameOverride: styrmin-message-queue
prefect-server:
  fullnameOverride: styrmin-task-manager
  postgresql:
    fullnameOverride: styrmin-postgresql

# App config must reference the same names as hostnames
env:
  DB_HOST: styrmin-neo4j              # must match neo4j.fullnameOverride
  CACHE_HOST: styrmin-cache-master    # must match redis.fullnameOverride (+ service suffix)
  BROKER_HOST: styrmin-message-queue  # must match rabbitmq.fullnameOverride
```

### Example

```yaml
fullnameOverride: styrmin-infrahub
global:
  imagePullPolicy: Always
  infrahubRepository: opsmill/infrahub-enterprise
  infrahubTag: {{ app.version }}

infrahubServer:
  persistence:
    storageClassName: {{ cluster.config.standard_storage.storage_class }}
  replicas: "1"
```

## Actions

Actions allow drivers to define custom logic that executes during application lifecycle events (setup, upgrade). Actions are declared in the `actions` section of `driver.styrmin.yml` and implemented in `actions.py`.

### Action Declaration

Actions are defined as a list under `spec.actions` in `driver.styrmin.yml`:

```yaml
spec:
  # ... other spec fields ...
  actions:
    - name: <string>       # Unique action name
      hook: <string>       # Lifecycle hook: "setup" or "upgrade"
      mode: <string>       # Execution phase: "pre", "core", or "post"
      description: <string>
      location: <string>   # Python function reference: "file.py::function"
      parameters: []       # Optional parameters
      image: <string>      # Optional container image for execution
```

### Hooks and Modes

| Hook | Description |
|------|-------------|
| `setup` | Executes during initial application setup |
| `upgrade` | Executes during application upgrades |

| Mode | Description |
|------|-------------|
| `pre` | Runs before the core operation |
| `core` | The main operation (replaces default behavior) |
| `post` | Runs after the core operation |

### Example

```yaml
spec:
  actions:
    - name: upgrade
      hook: upgrade
      mode: core
      description: Upgrade Infrahub
      location: "actions.py::upgrade"

    - name: pre_setup
      hook: setup
      mode: pre
      description: Initial Setup of Infrahub
      location: "actions.py::pre_setup"

    - name: post_setup
      hook: setup
      mode: post
      description: Initial Setup of Infrahub
      location: "actions.py::post_setup"
```

### Action Implementation (`actions.py`)

Actions are implemented as Python functions decorated with Prefect's `@flow` decorator.

```python
from styrmin_backend.actions import stop_components, start_components, execute_commands, GlobalContext
from prefect import flow, get_run_logger

@flow
async def upgrade(context: GlobalContext, target_version: str):
    logger = get_run_logger()
    logger.info("Executing upgrade...")

    # Stop components before upgrade
    await stop_components(components=["server", "task-worker"], context=context)

    # Run migration commands
    await execute_commands(
        ["sh", "-c", "infrahub db migrate && infrahub db update-core-schema"],
        image=f"opsmill/infrahub:{target_version}",
        context=context,
    )

    # Restart components
    await start_components(components=["server", "task-worker"], context=context)

@flow
def pre_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Pre-setup tasks...")

@flow
def post_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Post-setup tasks...")
```

### Available Primitives

The following primitives are available for use in action implementations:

#### `stop_components`

Stops specified deployment components.

```python
await stop_components(components: list[str], context: GlobalContext) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `components` | `list[str]` | Component names to stop (must match `components` in driver spec) |
| `context` | `GlobalContext` | The global context object |

#### `start_components`

Starts specified deployment components.

```python
await start_components(components: list[str], context: GlobalContext) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `components` | `list[str]` | Component names to start |
| `context` | `GlobalContext` | The global context object |

#### `execute_commands`

Executes shell commands as a Kubernetes job.

```python
await execute_commands(
    commands: list[str],
    image: str,
    context: GlobalContext,
    env_from_component: str | None = None,
    labels_from_component: str | None = None,
) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `commands` | `list[str]` | Commands to execute (passed to container) |
| `image` | `str` | Container image to use for the job |
| `context` | `GlobalContext` | The global context object |
| `env_from_component` | `str \| None` | Copy environment variables from this component |
| `labels_from_component` | `str \| None` | Copy labels from this component |

## Components

Components define the parts of an application that can be independently managed (started, stopped, scaled). Each component must have an `identifier` with a `label` selector that matches Kubernetes resources.

### Schema

```yaml
components:
  <component-name>:
    identifier:
      label:
        <key>: <value>   # Kubernetes label selector
    # Optional fields:
    cpu: <number>        # CPU allocation
    memory: <string>     # Memory allocation
```

### How Components Work

1. The `identifier.label` is used to select Kubernetes resources (Deployments, StatefulSets, etc.)
2. When `stop_components` is called, Styrmin scales down the matching resources
3. When `start_components` is called, Styrmin scales them back up
4. Component names in action primitives must match the names defined in the driver spec

### Example

```yaml
components:
  server:
    cpu: 4
    identifier:
      label:
        service: infrahub-server
  task-worker:
    identifier:
      label:
        service: infrahub-task-worker
  database:
    identifier:
      label:
        infrahub/service: database
```

## Driver Loading

Drivers are loaded from Git repositories. When loading a driver, Styrmin:

1. Clones the repository at the specified branch/tag
2. Parses `driver.styrmin.yml` and validates the schema (including embedded action declarations)
3. Reads `values.j2.yml` as a template string (if present)
4. If actions are declared, loads and validates `actions.py` to ensure all referenced functions exist
5. Stores the driver version in the database
6. Registers any actions with the workflow engine (Prefect)

## Examples

See the [`examples/`](examples/) directory for complete driver examples:

- [`examples/simple-app/`](examples/simple-app/) - Simple 3-tier FastAPI application with PostgreSQL
- [`examples/infrahub/`](examples/infrahub/) - Driver for the Infrahub application
- [`examples/infrahub-mcp/`](examples/infrahub-mcp/) - Infrahub MCP server Driver — exposes an existing Infrahub instance to AI agents over the Model Context Protocol in token-passthrough auth mode
- [`examples/slurpit/`](examples/slurpit/) - Driver for the Slurpit application
- [`examples/semaphore/`](examples/semaphore/) - Driver for Ansible Semaphore
- [`examples/db-test/`](examples/db-test/) - Database test driver
