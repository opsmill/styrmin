---
title: The generic-app driver
sidebar_position: 6
description: Deploy any single-container HTTP application, such as a Streamlit app or Semaphore, without writing a driver.
---

## The generic-app driver

`generic-app` deploys one container image that serves HTTP. Use it for an
application that has no driver of its own and needs no database or other
component next to it: a Streamlit dashboard, an internal tool, a
single-container service such as Semaphore with SQLite.

The driver is bundled in the Styrmin image. Load it like any bundled driver:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/generic-app
```

It builds on the public
[bjw-s `app-template`](https://github.com/bjw-s-labs/helm-charts/tree/main/charts/library/common)
Helm chart. The driver declares one component, `app`.

### What your application must do

- **Listen on port 8080.** A driver's service port is a fixed number, and
  Styrmin's service discovery sends traffic to that port on the pod. Tell the
  application to listen there with its own settings: an environment variable,
  a flag, or the command.
- **Serve HTTP.** The driver publishes the application at its public address
  through the environment's ingress.
- **Run in one container.** Several containers, or a database next to the
  application, need a driver of their own: see [Creating a Driver](./creating-a-driver.md).

### Parameters

Parameters are set once per deployment.

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `image_repository` | none, required | The image to run, without the tag. |
| `image_tag` | empty | The image tag. When empty, the deployment's application version is the tag. The application version must be a valid version number such as `2.17.12`, so for a tag like `latest` or `v2.17.12`, set `image_tag` and give the deployment any valid version. |
| `image_pull_policy` | `IfNotPresent` | `IfNotPresent`, `Always` or `Never`. |
| `health_path` | empty | An HTTP path that answers 200 when the application is ready. When empty, the driver checks that port 8080 accepts connections. |
| `storage_size` | `0` | The size in Gi of a persistent volume. `0` means no volume. |
| `storage_path` | `/data` | Where the volume is mounted in the container. |
| `fs_group` | `0` | A group ID that owns the volume. `0` leaves the volume as it is. |
| `allow_internet` | `true` | Whether the application can reach the internet. |

### Settings per deployment

The `app` component takes the settings every component takes, set on the
deployment and not on the driver:

- **Environment variables**, which is how most applications are configured.
- **Command and arguments**, to replace the image's entrypoint or arguments.
  Clearing them returns to the image's own.
- **An image override**, to run another image of the same application. See
  [image overrides](../concepts-and-architecture/image-overrides.md).

### Example: a Streamlit application

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: dashboard
spec:
  driver: generic-app
  version: "1.0.0"          # the image tag, because image_tag is empty
  parameters:
    image_repository: registry.example/acme/dashboard
    health_path: /_stcore/health
  config:
    components:
      - name: app
        env_vars:
          - name: STREAMLIT_SERVER_PORT
            value: "8080"
          - name: STREAMLIT_SERVER_HEADLESS
            value: "true"
```

### Example: Semaphore with its data on a volume

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: ansible
spec:
  driver: generic-app
  version: "2.17.12"
  parameters:
    image_repository: semaphoreui/semaphore
    image_tag: v2.17.12
    health_path: /api/ping
    storage_size: 1
    storage_path: /var/lib/semaphore
    fs_group: 1001            # the group of the user the image runs as
  config:
    components:
      - name: app
        env_vars:
          - name: SEMAPHORE_PORT
            value: "8080"
          - name: SEMAPHORE_DB_DIALECT
            value: sqlite
          - name: SEMAPHORE_ADMIN
            value: admin
          - name: SEMAPHORE_ADMIN_PASSWORD
            value: "<admin password>"
```

### Storage

When `storage_size` is above 0, the driver creates a `ReadWriteOnce` volume and
mounts it at `storage_path`. A volume is created owned by root, so an image that
runs as another user needs `fs_group` set to that user's group, or it cannot
write to the volume. A volume can be mounted by one pod at a time, so
with a volume the deployment replaces its pod instead of starting the new one
next to the old one, and the application is down for the few seconds that
takes. Without a volume, the deployment starts the new pod before it stops the
old one.

The driver declares a `disk` [backup](../concepts-and-architecture/backups-and-restores.md)
of the volume named `data`. That volume exists only when `storage_size` is above
0. Without it, the backup has nothing to capture: Velero skips a volume that a
pod does not have.

### Networking

- **Public address.** The application is published at the address Styrmin
  generates for its service, and at a readable one made of the service name and
  the environment name.
- **Other applications of the environment.** An application can call the other
  applications of its environment, and they can call it, by service name. A
  name resolves only after the application it names has started and Styrmin has
  created its service alias, which can take a minute or two.
- **Other environments.** An application cannot reach, and cannot be reached
  from, the applications of another environment.
- **The internet.** An application reaches public IPv4 and IPv6 addresses when
  `allow_internet` is `true`, and cannot when it is `false`. It never reaches
  private address ranges, except the other applications of its environment.

The driver declares these network policies itself, because Styrmin's
default policies for an environment only let the environment's ingress
controller and Styrmin's own components talk to a deployment
([opsmill/styrmin#284](https://github.com/opsmill/styrmin/issues/284)).

### Several deployments in one environment

Every deployment of `generic-app` declares the service name `app`, and a service
name is unique within an environment. The second deployment in an environment
fails with `ALREADY_EXISTS`, so give each deployment its own service name with a
service name override, when you create it. A manifest cannot set one yet: use
the SDK or the API.

```python
await client.deployments.create(
    driver="generic-app",
    version="2.17.12",
    environment_name="demo",
    cluster_name="local",
    name="ansible",
    parameters=[...],
    config=...,
    service_name_overrides=[{"driverServiceName": "app", "overrideName": "ansible"}],
)
```

The override also sets the service's readable address, here `ansible-demo`
followed by the cluster's domain suffix, and the name the other applications of
the environment call it by. When you change the override of a running
deployment, the other applications call it by the new name, and the old name
stops resolving for them.
