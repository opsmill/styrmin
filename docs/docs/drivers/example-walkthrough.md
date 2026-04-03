---
title: Example Walkthrough
sidebar_position: 4
description: A complete Application Driver example explained step by step.
---

# Example Walkthrough: Simple App Driver

This walkthrough explains a complete, working Application Driver — the `simple-app` driver that deploys a 3-tier FastAPI application with PostgreSQL.

## Directory Structure

```
simple-app/
├── styrmin_driver.yaml      # Driver specification
├── chart_values.j2.yaml     # Helm values template
├── actions.yaml             # Action definitions
└── actions.py               # Action implementations
```

## File 1: `styrmin_driver.yaml`

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: simple-app
spec:
  version: "1"
  supported_versions: ">=0.1,<1.0"
  info:
    description: Simple 3-tier FastAPI application with PostgreSQL
    authors: [opsmill]
    license: Apache-2.0
  helm:
    main:
      location: simple-app
      version: 0.1.0

  components:
    server:
      identifier:
        label:
          app.kubernetes.io/name: simple-app

    database:
      identifier:
        label:
          app.kubernetes.io/name: postgresql
      backup:
        enabled: true
        kind: postgres
        database_name: simple_app

  services:
    - name: simple-app
      kind: http
      scope: internal
      port: 8000
      component: server
```

### What this defines

- **`metadata.name: simple-app`** — The driver is uniquely identified as "simple-app"
- **`spec.version: "1"`** — This is version 1 of the driver
- **`spec.supported_versions: ">=0.1,<1.0"`** — Compatible with app versions 0.1.x through 0.9.x
- **`spec.helm.main`** — Points to the `simple-app` Helm chart at version `0.1.0`
- **Two components:**
  - `server` — The FastAPI application, identified by label `app.kubernetes.io/name: simple-app`
  - `database` — PostgreSQL, identified by label `app.kubernetes.io/name: postgresql`, with backup enabled
- **One service:**
  - `simple-app` — An HTTP service on port 8000, associated with the `server` component

## File 2: `chart_values.j2.yaml`

```yaml
fullnameOverride: styrmin-simple-app

image:
  repository: simple-app
  tag: "{{ app.version }}"

ingress:
  enabled: true
  className: "{{ instance.config.ingress_class }}"
  hosts:
    - host: "{{ services['simple-app'].primary_fqdn }}"
      paths:
        - path: /
          pathType: Prefix

database:
  host: styrmin-postgresql

postgresql:
  enabled: true
  fullnameOverride: styrmin-postgresql
  auth:
    username: simple-app
    password: simple-app-password
    database: simple_app
  primary:
    livenessProbe:
      initialDelaySeconds: 1
      periodSeconds: 1
      timeoutSeconds: 1
      failureThreshold: 60
    readinessProbe:
      initialDelaySeconds: 1
      periodSeconds: 1
      timeoutSeconds: 1
      failureThreshold: 60
    persistence:
      enabled: true
      size: 1Gi
    extraVolumes:
      - name: backup
        emptyDir: {}
    extraVolumeMounts:
      - name: backup
        mountPath: /backup
```

### What this does

- **`fullnameOverride: styrmin-simple-app`** — Sets the Kubernetes resource name prefix. This is required to avoid name-length issues.
- **`image.tag: "{{ app.version }}"`** — Dynamically sets the container image tag to match the deployed application version.
- **`ingress.className: "{{ instance.config.ingress_class }}"`** — Uses the ingress class configured for this deployment's environment.
- **`services['simple-app'].primary_fqdn`** — Styrmin computes the FQDN for the service based on the deployment context and injects it here.
- **`database.host: styrmin-postgresql`** — References the PostgreSQL subchart by its `fullnameOverride`. This is critical — the hostname must match exactly.
- **`postgresql.fullnameOverride: styrmin-postgresql`** — Sets the PostgreSQL service name. The `database.host` value above references this.

## File 3: `actions.yaml`

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ActionDefinition
metadata:
  package: simple-app
spec:
  actions:
    - name: upgrade
      hook: upgrade
      mode: core
      description: Upgrade Simple App
      location: "actions.py::upgrade"

    - name: pre_setup
      hook: setup
      mode: pre
      description: Pre-setup of Simple App
      location: "actions.py::pre_setup"

    - name: post_setup
      hook: setup
      mode: post
      description: Post-setup of Simple App
      location: "actions.py::post_setup"
```

### What this defines

Three lifecycle actions:

1. **`upgrade`** — A `core` action on the `upgrade` hook. This replaces the default upgrade behavior with custom logic.
2. **`pre_setup`** — A `pre` action on the `setup` hook. Runs before the initial Helm install.
3. **`post_setup`** — A `post` action on the `setup` hook. Runs after the initial Helm install.

## File 4: `actions.py`

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
    logger.info("Starting simple-app upgrade...")

    await stop_components(components=["server"], context=context)

    await upgrade_deployment_version(target_version=target_version, context=context)

    images = await get_component_images(component="server", context=context)
    image = next(img for img in images if "simple-app" in img)
    image_base = image.rsplit(":", 1)[0]

    await execute_commands(
        ["simple-app-upgrade"],
        image=f"{image_base}:{target_version}",
        context=context,
        env_from_component="server",
        labels_from_component="server",
    )

    await start_components(components=["server"], context=context)

    logger.info(f"Simple-app upgrade to {target_version} complete.")


@flow
def pre_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing simple-app pre-setup...")


@flow
def post_setup(context: GlobalContext):
    logger = get_run_logger()
    logger.info("Executing simple-app post-setup...")
```

### How the upgrade works

The `upgrade` function demonstrates a typical zero-downtime upgrade pattern:

1. **Stop the server** — Scale down the `server` component so no requests are served during the upgrade
2. **Update the version** — Tell Styrmin to target the new version (updates the Helm release)
3. **Find the image** — Look up the current container image for the server component and derive the base image name
4. **Run migrations** — Execute the `simple-app-upgrade` command in a Kubernetes job using the new version's image, inheriting environment variables and labels from the server component
5. **Restart the server** — Scale the server component back up with the new version

The `pre_setup` and `post_setup` functions are placeholders in this example — they log messages but don't perform additional operations. In a real driver, these might initialize databases, create API keys, or configure external services.

## Summary

This driver demonstrates all the key features of Application Drivers:

| Feature | How it's used |
|---------|--------------|
| Helm chart management | `spec.helm.main` points to the chart |
| Dynamic configuration | Jinja2 template with `app.version`, `instance.config`, and `services` |
| Component lifecycle | `server` and `database` components with label selectors |
| Service definitions | HTTP service on port 8000 with computed FQDN |
| Custom upgrade logic | Coordinated stop → migrate → restart workflow |
| `fullnameOverride` convention | Both main chart and PostgreSQL subchart set it |

To create your own driver, start with this example and adapt it to your application's requirements. See the [Creating a Driver](./creating-a-driver.md) guide for a step-by-step approach.
