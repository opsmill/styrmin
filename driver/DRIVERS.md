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
  info:                    # Required block; every key is optional
    icon: <string>         # Absolute https URL of the logo image
    description: <string>  # Plain text that describes the application
    authors: [<string>]
    license: <string>
    links:                 # Links to the application's pages
      - link: <string>     # Label of the link
        url: <string>      # Absolute http or https URL
  helm:
    main:
      location: <string>   # OCI or HTTP URL to Helm chart
      version: <string>    # Helm chart version
  components:              # Optional component definitions
    <component-name>:
      container: <string>  # Optional component container: receives user env var, image, command and args overrides by post-render
      replicas: <integer>  # Optional driver default replica count, from 1 to 2147483647
      singleton: <boolean> # Optional, default false: the replica count is fixed at 1
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
      kind: <string>       # http, https, tcp, udp
      scope: <string>      # internal, or external: Styrmin builds the Ingress of the service
      port: <integer>
      component: <string>
  actions:                 # Optional action declarations
    - name: <string>       # Unique action name
      hook: <string>       # Lifecycle hook: "setup" or "upgrade"
      mode: <string>       # Execution phase: "pre", "core", or "post"
      description: <string>
      location: <string>   # Python function reference: "file.py::function"
      parameters: []       # Optional parameters
      image: <string>      # Optional container image; no effect today (see "Actions")
```

### Required Fields

| Field | Description |
|-------|-------------|
| `apiVersion` | Must be `styrmin.io/v1` |
| `kind` | Must be `ApplicationDriver` |
| `metadata.name` | Unique identifier for the driver |
| `spec.version` | Version string for this driver |
| `spec.supported_versions` | Semver specifier (e.g., `>=1.1.5,<=1.2.0`) |
| `spec.info` | Block that describes the application. It can be empty (`info: {}`); every key in it is optional |
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
    icon: https://docs.infrahub.app/img/infrahub-logo.svg
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
      scope: external      # Styrmin builds its Ingress; the chart's Prefect Ingress is off
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

### Info Block: Logo, Description and Links

The `spec.info` block describes the application that the driver deploys. Styrmin stores `icon`, `description` and `links` on each driver version. The table lists which driver version each place on the driver pages takes the values from.

| Key | Accepted format | Where users view it |
|-----|-----------------|---------------------|
| `icon` | Absolute `https` URL of an image, without a username or password | Driver list page: the driver header in the "Group by application" view (latest driver version), and each row in the "Flat list" view (the driver version of the row). Driver detail page: next to the driver name (selected driver version). |
| `description` | Plain text | Driver list page: under the driver name in the "Group by application" view, cut to one line, with a "Show more" button when it is longer (latest driver version). Driver detail page: above the tabs, with its line breaks, cut to three lines with a "Show more" button when it is longer (selected driver version). The driver list filter matches it. |
| `links` | List of entries with exactly two keys: `link` (the label) and `url` (an absolute `http` or `https` URL, without a username or password) | Driver detail page: the "Links" section of the Overview tab, in file order, with the host name of each URL (selected driver version). Each link opens in a new browser tab. |
| `authors` | List of strings | Not shown |
| `license` | String | Not shown |

An empty `description` or an empty `links` list counts as not set.

The logo image:

- Styrmin does not download the image. The browser of each person who opens the driver pages loads it from the `icon` URL, so the URL must be reachable from those browsers. In an installation without internet access, host the image on an internal server or leave `icon` out.
- The browser does not send the address of the Styrmin page to the image host, but the host receives a request with the IP address of each viewer. Use an image host that you trust. An operator can stop these requests for the whole installation with the Helm value `styrmin.driver.showLogos: false` (environment variable `STYRMIN_DRIVER_SHOW_LOGOS=false`); the pages then show the generic package icon for every driver.
- The URL must use `https`. A Styrmin server served over HTTPS cannot show an `http` image, because browsers block it as mixed content.
- The pages show the logo on a white square tile, in the light and the dark theme. Use a square SVG or PNG image that is visible on a white background, for example with a transparent background and dark or colored marks. The pages show the logo at 32 by 32 pixels or smaller.
- The pages show a generic package icon in the same place until the image has loaded, and when `icon` is not set or the browser cannot load the image.

Loading the driver does not fail because of an invalid `icon` or `links` entry. The load leaves out:

- `icon`, when it is not an absolute `https` URL (for example `xxxx`, `logo.svg`, `http://example.com/logo.png` or `javascript:alert(1)`), or when it contains a username or password.
- Each `links` entry that has a key other than `link` and `url`, does not have one of them, has a `link` that is not text, or has a `url` that is not an absolute `http` or `https` URL or that contains a username or password. The other entries are kept.

For each value it leaves out, the load returns a warning that names the field, for example `spec.info.icon` or `spec.info.links[1].url`, and says why. `styrminctl drivers load-version` and `styrminctl drivers load-local-version` print the warnings, the Load driver drawer shows them in a notification, and the GraphQL load mutations return them in `loadWarnings`. Styrmin does not store the warnings, so loading the same file again returns them again.

To change the logo, description or links, edit `spec.info` and load the driver again. For a local driver, the changed file creates a new driver version. For a Git driver, a new commit creates a new driver version.

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
| `services['<name>'].human_readable_fqdn` | `str` | Human-readable FQDN for display. Has the suffix of the service ingress override when the deployment has one |
| `services['<name>'].ingress_class` | `str` | Effective ingress class of the service (the override's class when there is one) |
| `services['<name>'].overridden` | `bool` | `true` when the service has a service ingress override |

Prefer `instance.config.*` over `cluster.config.*` and `environment.config.*`. When an
administrator changes the cluster config, Styrmin redeploys only the deployments whose resolved
config (`instance.config`) changes. A deployment that is not redeployed keeps the
`cluster.config` of its last render, so a template that reads `cluster.config.*` sees the
previous cluster value until the deployment is redeployed for another reason (see
[ADR-066](../dev/adr/0066-cluster-config-fanout.md)).

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
    storageClassName: {{ instance.config.standard_storage.storage_class }}
  replicas: "1"
```

### Credentials in a driver that can be cloned

An environment clone restores the data of each deployment into a new deployment in the new environment, and renders the Helm values again for that new deployment. The clone copies the deployment's config and parameters unchanged, so a credential set there still matches the restored data.

A chart that generates a credential when it is installed, for example a random password from `randAlphaNum` without `lookup`, creates a new credential over restored data that expects the old one. The restored component then cannot connect to its data. A driver meant to be cloned must therefore take its credentials from the deployment's config or parameters, not generate them at install time. See [Backups and restores](../docs/docs/concepts-and-architecture/backups-and-restores.md) and [ADR-056](../dev/adr/0056-environment-clone-record-and-cross-target-restore.md).

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
      image: <string>      # Optional container image; no effect today (see below)
```

The pull steps of an action from git run Prefect's `git_clone` step with
`clone_directory_name`, which releases before Prefect 3.6.9 refuse. The
Prefect of the Styrmin agent runs these pull steps, so the image that the
agent runs needs Prefect 3.6.9 or later.

The `image` field has no effect today: the Styrmin agent runs every action
as a process in the agent pod, not in a container of that image.

For a driver loaded from a local directory, each action runs the
`actions.py` at the path the driver was loaded from, in the agent pod.
Before the action runs, Styrmin checks that the driver files at that path
have the provenance fingerprint the driver version was loaded with, and
fails the hook step when they are missing or differ. The agent pod must
therefore hold the driver at the same path as the server, and a
`styrmin_backend` package that has this check. In a standard install,
the server and the agent run the same Styrmin image, which holds the
bundled drivers at `/styrmin/drivers/<name>` and the check. See
[Loading a Driver](../docs/docs/drivers/loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory)
for the errors and how to fix each one.

The check covers `driver.styrmin.yml`, the values template and
`actions.py`, but not the modules that `actions.py` imports. An edit of a
module such as `helpers.py` at the path takes effect in the next action
run, and the check does not report it. A load from a local directory of a
driver that declares actions is therefore refused when an action's
`location` is in another file than `actions.py`, and when the path is
relative or contains `{` or `}`.

A driver declares at most one action for each hook and mode. Styrmin
registers the actions of one hook and mode under one key, so a load of a
driver that declares two of them, from git or from a local directory, is
refused. To run several steps in one hook and mode, call them from one
action.

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

Do not write secrets to the logs of an action. When an action's flow run
crashes, its first log line of level `ERROR` becomes part of the error of
its hook step, which every signed-in user who can read the task can read.
Styrmin replaces the action's API token and some common forms of secrets
in that line with `<redacted>`, but not every form (see
[Logs of a crashed action are shown on its hook step](../docs/docs/drivers/loading-drivers.md#logs-of-a-crashed-action-are-shown-on-its-hook-step)).
It replaces the same forms in every other log line too.

Log ids and names, such as `context.instance.deployment_id`, not the values
of the context: its values template, parameters and env vars can hold
passwords. Printing the whole context shows only its ids and names (see
[Logging in an action](../docs/docs/drivers/creating-a-driver.md#logging-in-an-action)).

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

The Job is named `<release reference>-job` in the deployment's namespace, has the label `styrmin.io/action-job=true`, and ends at its first failed pod (`backoffLimit: 0`). It stays in the cluster after it ends, so you can read its output with `kubectl logs`. The next `execute_commands` call on the same deployment deletes that Job and its pods once it has ended, completed or failed, then creates its own; the hook step that runs the action shows a line that names the deleted Job. The call fails instead of deleting anything when:

- the Job of that name is still running, for example because another change of the deployment runs its action at the same time (`JobStillRunningError`). Wait until the Job ends and request the change again.
- a Job of that name exists that no driver action created: it has no `styrmin.io/action-job=true` label, and its only container is not `user-job` (`JobNotFromActionError`).

When the Job is deleted while the call waits for it to end, the call fails with `JobDeletedError`.

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
| `env_from_component` | `str \| None` | Copy environment variables from this component's component container, then set the user's env vars from the context on top |
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
    container: <string>  # Component container that receives env var, image, command and args overrides
    replicas: <integer>  # Driver default replica count, from 1 to 2147483647
    singleton: <boolean> # Default false; true fixes the replica count at 1
    cpu: <number>        # CPU allocation
    memory: <string>     # Memory allocation
```

### How Components Work

1. The `identifier.label` is used to select Kubernetes resources (Deployments, StatefulSets, etc.)
2. When `stop_components` is called, Styrmin sets `spec.replicas` of the matching `Deployment` and `StatefulSet` resources to 0
3. When `start_components` is called, Styrmin sets them back to the component's replica count (see [Replica counts](#replica-counts))
4. Component names in action primitives must match the names defined in the driver spec

### Replica counts

Styrmin sets each component's replica count after the chart renders, with a post-render patch on `spec.replicas` of every `Deployment` and `StatefulSet` that the component's label selector matches. `Job`, `CronJob` and `DaemonSet` resources are not changed. The count comes from the first of these that is set:

1. The **replica override** that a user sets on the component of a deployment (`components[].replicas` in the deployment config).
2. The **driver default**: `replicas` on the component, or 1 when the component sets `singleton: true` and no `replicas`.
3. The count that the chart renders: Styrmin does not change `spec.replicas`.

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `replicas` | integer from 1 to 2147483647 | not set | The count of the component when a deployment sets no replica override |
| `singleton` | boolean | `false` | The count is fixed at 1: Styrmin sets 1 when `replicas` is not set, and rejects a replica override greater than 1 with `SINGLETON_REPLICA_OVERRIDE` |

Mark a component `singleton: true` when a second pod would break it, for example a database that runs as a single primary. The flag limits the replica count, not the number of pods during a rolling update: the chart's update strategy can run a second pod for a short time.

A component needs no `container` to receive a replica count, and `values.j2.yml` does not pass a count to the chart. Do not declare a parameter for a replica count; users set a replica override instead.

The driver fails to load, and no driver version is stored, when:

- `singleton: true` is combined with `replicas` greater than 1;
- `replicas` is below 1 or above 2147483647, a string, a float or a boolean;
- `singleton` is not a boolean.

The error names the field, for example:

```text
- spec.components.database: Value error, a singleton component runs exactly 1 replica; `singleton: true` cannot be combined with `replicas: 3`
- spec.components.server.replicas: Input should be greater than or equal to 1 (found 0)
```

`singleton: true` with `replicas: 1` loads.

### Example

```yaml
components:
  server:
    cpu: 4
    replicas: 1
    identifier:
      label:
        service: infrahub-server
  task-worker:
    replicas: 2
    identifier:
      label:
        service: infrahub-task-worker
  database:
    singleton: true
    identifier:
      label:
        infrahub/service: database
```

## Driver Loading

Drivers are loaded from Git repositories, or from a directory on the Styrmin server. A load from git takes the repository URL, the branch and, optionally, the driver directory: the folder of the repository that holds the driver's files, given as a path relative to the repository root. When loading a driver from git, Styrmin:

1. Clones the whole repository at the tip of the branch and records the commit
2. Reads the driver files from the driver directory, or from the repository root when no driver directory is given. It refuses the load when the driver directory, `driver.styrmin.yml`, `values.j2.yml` or `actions.py` is a symlink to a path outside the repository
3. Parses `driver.styrmin.yml` and validates the schema (including embedded action declarations)
4. Reads `values.j2.yml` as a template string (if present)
5. If actions are declared, loads and validates `actions.py` to ensure all referenced functions exist
6. Stores the driver version in the database, with the driver directory in `source_path`
7. Registers any actions with the workflow engine (Prefect)

Each action runs with the driver directory as its working directory. `actions.py` can import modules from the driver directory, such as a `helpers.py` next to it, but not modules from other folders of the repository. Packages installed in the agent's image, such as `prefect` and `styrmin_backend`, import as before. Code that several drivers share goes into each driver directory, or is installed in the image that the agent runs.

A load from a local directory reads the driver from the path on the server, stores the path in `source_path`, and registers the driver's actions in the same way. Each action then runs from that path in the agent pod, after the check described in [Actions](#actions).

See [Loading a Driver](../docs/docs/drivers/loading-drivers.md#from-a-git-repository) for the CLI, SDK, GraphQL and UI options and the values refused as a driver directory, and [ADR-079](../dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md) for the reasons behind the import rule and the symlink check.

## Examples

See the [`examples/`](examples/) directory for complete driver examples:

- [`examples/simple-app/`](examples/simple-app/) - Simple 3-tier FastAPI application with PostgreSQL
- [`examples/infrahub/`](examples/infrahub/) - Driver for the Infrahub application
- [`examples/infrahub-mcp/`](examples/infrahub-mcp/) - Infrahub MCP server Driver — exposes an existing Infrahub instance to AI agents over the Model Context Protocol in token-passthrough auth mode
- [`examples/slurpit/`](examples/slurpit/) - Driver for the Slurpit application
- [`examples/generic-app/`](examples/generic-app/) - Generic driver for any single-container HTTP application, such as a Streamlit app
- [`examples/semaphore/`](examples/semaphore/) - Driver for Ansible Semaphore
- [`examples/db-test/`](examples/db-test/) - Database test driver
