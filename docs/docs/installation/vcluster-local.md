---
title: Install Styrmin on a local vCluster
sidebar_label: Local laptop (vCluster)
sidebar_position: 4
description: Install a released version of Styrmin on a vCluster on your laptop, from the Helm chart and the container image on registry.opsmill.io.
---

## Install Styrmin on a local vCluster

Install a released version of Styrmin on a [vCluster](https://www.vcluster.com/)
that runs in Docker on your laptop. Every step uses the Helm chart and the
container image that OpsMill publishes on `registry.opsmill.io`, so you need
no copy of the Styrmin repository.

By the end, you have:

- a vCluster named `styrmin` that runs in Docker on your machine,
- [Traefik](https://traefik.io/) as the ingress controller of the vCluster,
- a [Garage](https://garagehq.deuxfleurs.fr/) object store in the vCluster,
  which Velero uses to store backups,
- Styrmin (server, agent, Prefect, PostgreSQL) installed from the published
  Helm chart,
- one cluster, one environment, one backup storage location, and the
  bundled `infrahub` and `semaphore` application drivers loaded,
- the frontend at `http://styrmin.local.styrmin.io:8080`.

> To run Styrmin from a clone of the repository with one command, for
> example to test a change to Styrmin, see the
> [Quickstart](../installation/quickstart.md).

### Prerequisites

You need the following on your `PATH`:

- Docker: the vCluster runs in Docker with the vCluster `docker` driver
- `kubectl`
- `helm` 3.8 or later, which can install charts from an OCI registry
- the `vcluster` CLI ([install instructions](https://www.vcluster.com/docs/getting-started/setup))

TCP port `8080` must be free on your machine, because the port-forward to
Traefik listens on it. The guide does not use port `80`, which is a
privileged port.

> The DNS zone `*.local.styrmin.io` resolves to `127.0.0.1`, so
> `http://styrmin.local.styrmin.io:8080` opens the frontend without a
> change to `/etc/hosts`.

### 1. Choose the Styrmin version

The commands below install the Styrmin version in `STYRMIN_VERSION`.
The examples use 0.1.52, the latest release when this guide was written.
The [Changelog](../changelog.md) lists the releases.

```shell
export STYRMIN_VERSION=0.1.52
```

The Helm chart and the container image have the same version number, and
the chart installs the image of its own version.

### 2. Create the vCluster

vCluster runs a virtual Kubernetes control plane. With the `docker` driver,
the control plane runs in a Docker container, so you need no Kubernetes
cluster on your machine.

```shell
vcluster create styrmin \
  --upgrade \
  --driver=docker \
  --connect=false
```

- `--driver=docker` runs the vCluster in Docker.
- `--upgrade` upgrades the vCluster if it exists, so you can run the
  command again without an error.
- `--connect=false` leaves your kubeconfig unchanged. The next step changes
  it.

`vcluster list --driver=docker` now shows `styrmin` as `running`.

### 3. Connect `kubectl` to the vCluster

```shell
vcluster connect styrmin --driver=docker
```

The command adds a kubeconfig context for the vCluster and makes it the
current context. Check the result:

```shell
kubectl config current-context
kubectl get nodes
```

The output lists one node.

> Every later `kubectl` and `helm` command in this guide runs against the
> vCluster. If your kubeconfig has other clusters, check
> `kubectl config current-context` before each step.

### 4. Install Traefik

Styrmin serves its frontend through a Kubernetes `Ingress`, so the
vCluster needs an ingress controller. This guide uses Traefik. Another
ingress controller also works, but the values and the host names below are
for Traefik.

Write the values file:

```shell
cat > traefik-values.yaml <<'EOF'
service:
  spec:
    type: ClusterIP
ports:
  web:
    port: 80
    expose:
      default: true
providers:
  kubernetesIngress:
    publishedService:
      enabled: true
resources:
  requests:
    cpu: 100m
    memory: 128Mi
EOF
```

Install the chart:

```shell
helm repo add traefik https://helm.traefik.io/traefik --force-update
helm repo update traefik
helm upgrade --install traefik traefik/traefik \
  --version 42.1.2 \
  -n styrmin --create-namespace \
  -f traefik-values.yaml \
  --wait --timeout 5m
```

- `service.spec.type: ClusterIP` gives Traefik a Service without an external
  IP. Step 7 forwards a port of your machine to it, so the steps are the
  same on Linux and macOS.
- `publishedService` makes Traefik write the address of its Service in the
  status of each `Ingress`.
- `--force-update` updates the `traefik` repository entry if it exists.
- `--version 42.1.2` installs the chart version that this guide was tested
  with.

Check that the Service type is `ClusterIP`:

```shell
kubectl get service traefik -n styrmin
```

### 5. Install Garage

Styrmin runs backups with Velero, which stores them in an S3-compatible
object store. On your laptop, run Garage in the same namespace. The
manifest below creates a `ConfigMap` with the Garage configuration, a
volume claim for the data, a `Deployment` with one replica, and a `Service`
for the S3 API on port `3900`:

```shell
cat > garage.yaml <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: garage
data:
  garage.toml: |
    metadata_dir = "/var/lib/garage/meta"
    data_dir = "/var/lib/garage/data"
    db_engine = "sqlite"
    replication_factor = 1
    rpc_bind_addr = "[::]:3901"
    rpc_public_addr = "127.0.0.1:3901"
    rpc_secret = "a0b1c2d3e4f5061728394a5b6c7d8e9fa0b1c2d3e4f5061728394a5b6c7d8e9f"

    [s3_api]
    s3_region = "garage"
    api_bind_addr = "[::]:3900"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: garage
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: garage
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: garage
  template:
    metadata:
      labels:
        app: garage
    spec:
      containers:
        - name: garage
          image: dxflrs/garage:v2.4.1
          ports:
            - containerPort: 3900
          readinessProbe:
            tcpSocket:
              port: 3901
            periodSeconds: 2
          volumeMounts:
            - name: config
              mountPath: /etc/garage.toml
              subPath: garage.toml
            - name: data
              mountPath: /var/lib/garage
      volumes:
        - name: config
          configMap:
            name: garage
        - name: data
          persistentVolumeClaim:
            claimName: garage
---
apiVersion: v1
kind: Service
metadata:
  name: garage
spec:
  selector:
    app: garage
  ports:
    - name: s3
      port: 3900
EOF
kubectl apply -n styrmin -f garage.yaml
kubectl rollout status deployment/garage -n styrmin --timeout=120s
```

The pod is ready when Garage listens on its RPC port, `3901`. A new Garage
node stores no data until it has a cluster layout. Assign the layout, then
create the access key and the `velero` bucket with the `garage` CLI in the
pod:

```shell
NODE_ID=$(kubectl exec -n styrmin deploy/garage -- /garage node id -q)
kubectl exec -n styrmin deploy/garage -- \
  /garage layout assign -z styrmin -c 10G "${NODE_ID%%@*}"
kubectl exec -n styrmin deploy/garage -- /garage layout apply --version 1
kubectl exec -n styrmin deploy/garage -- \
  /garage key import --yes -n velero \
  GKdeadbeefdeadbeefdeadbeef \
  deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
kubectl exec -n styrmin deploy/garage -- /garage bucket create velero
kubectl exec -n styrmin deploy/garage -- \
  /garage bucket allow --read --write --owner velero --key velero
```

- `garage node id -q` prints the node ID followed by `@` and its address.
  `${NODE_ID%%@*}` keeps the part before the `@`.
- `key import` creates the access key `GKdeadbeefdeadbeefdeadbeef` with the
  secret key that follows it. Step 9 gives the same keys to Styrmin. These
  are demo values: use your own keys for an installation that you keep.

The volume claim keeps the data, the layout, the key and the bucket when
the pod restarts, so you run these commands once.

### 6. Install Styrmin

Write the values file:

```shell
cat > styrmin-values.yaml <<'EOF'
ingress:
  enabled: true
  className: traefik
  hosts:
    - host: styrmin.local.styrmin.io
      paths:
        - path: /
          pathType: Prefix

styrmin:
  url:
    apiK8s: http://styrmin-server.styrmin.svc.cluster.local:8000
  adminUsername: admin
  adminPassword: styrmin
  sessionCookieSecure: false
  telemetry:
    enabled: false

velero:
  backupsEnabled: false
  credentials:
    useSecret: false
EOF
```

- `ingress` serves the frontend and the API at
  `styrmin.local.styrmin.io` through Traefik.
- `styrmin.url.apiK8s` is the address of the Styrmin API that pods in the
  vCluster use.
- `adminUsername` and `adminPassword` set the first admin user. Styrmin
  creates this user at the first install only: a later change to these values
  does not change the password.
- `sessionCookieSecure: false` lets your browser keep the session cookie over
  plain HTTP. Leave it at `true` on an installation that uses HTTPS.
- `telemetry.enabled: false` turns off the daily anonymous report of the
  server. See [Telemetry & privacy](../reference/telemetry.md).
- `velero.backupsEnabled: false` and `velero.credentials.useSecret: false`
  install Velero without a backup storage location of its own. Step 9
  creates one in Styrmin, for the Garage bucket.

Install the chart from the OpsMill registry:

```shell
helm upgrade --install styrmin \
  oci://registry.opsmill.io/opsmill/chart/styrmin \
  --version "$STYRMIN_VERSION" \
  -n styrmin --create-namespace \
  -f styrmin-values.yaml \
  --wait --timeout 10m
```

The chart installs the Styrmin server and its task worker, the Styrmin
agent with the FluxCD controllers, Prefect, PostgreSQL and Velero. The
server and the agent run the image
`registry.opsmill.io/opsmill/styrmin:$STYRMIN_VERSION`.

Check that the server is running:

```shell
kubectl rollout status deployment/styrmin-server -n styrmin --timeout=300s
```

### 7. Forward a port to Traefik

Traefik has a `ClusterIP` Service, so forward a port of your machine to it.
This guide uses `8080`:

```shell
kubectl port-forward svc/traefik 8080:80 -n styrmin
```

Leave the command running in its own terminal. The frontend is now
available at:

```text
http://styrmin.local.styrmin.io:8080
```

Log in with the user `admin` and the password `styrmin`.

### 8. Run `styrminctl` in the server pod

The Styrmin image includes `styrminctl`, the Styrmin CLI. Run it in the
server pod with `kubectl exec`, which needs no installation on your
machine. Define a shell function for it:

```shell
styrminctl() {
  kubectl exec -n styrmin deploy/styrmin-server -- \
    env STYRMIN_USERNAME=admin STYRMIN_PASSWORD=styrmin styrminctl "$@"
}
```

- `styrminctl` connects to the server at `http://localhost:8000`, its
  default address, which is the server in the same pod.
- `STYRMIN_USERNAME` and `STYRMIN_PASSWORD` log `styrminctl` in on each
  call, with the admin user of step 6.
- The command runs in the container, so a file that you pass to it, such as
  `--config @file.json`, must be in the container. Pass the JSON inline
  instead.

Check that the function works:

```shell
styrminctl whoami
```

The output shows `Username: admin` and `Role: ADMIN`.

### 9. Create the first records

The Styrmin database has no records yet. Create the cluster, the
environment and the backup storage location, then load the bundled
application drivers.

#### 9a. Create the cluster

```shell
styrminctl clusters create local \
  --config '{
        "fqdn_suffix": "local.styrmin.io",
        "external_url_scheme": "http",
        "external_url_port": 8080,
        "ingress_class": "traefik",
        "standard_storage": {"storage_class": "local-path"},
        "fast_storage": {"storage_class": "local-path"}
      }'
```

- `fqdn_suffix`, `external_url_scheme` and `external_url_port` set the URLs
  of the applications that you deploy, for example
  `http://infrahub-<deployment-id>.local.styrmin.io:8080`.
- `ingress_class` is the ingress class of Traefik.
- `standard_storage` and `fast_storage` name the storage class of the
  vCluster, `local-path`. The `infrahub` driver uses `fast_storage` for its
  databases.

#### 9b. Create the environment

```shell
styrminctl environments create local --cluster local -c '{}'
```

#### 9c. Create the backup storage location

Create a backup storage location for the Garage bucket of step 5:

```shell
styrminctl backup-locations create local \
  --endpoint http://garage.styrmin.svc:3900 \
  --bucket velero \
  --region garage \
  --access-key-id GKdeadbeefdeadbeefdeadbeef \
  --secret-access-key deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
```

Note the `id` in the output. The next step uses it as `<BSL_ID>`.

#### 9d. Assign the backup storage location to the environment

```shell
styrminctl backup-locations assign local <BSL_ID> --cluster local
```

Styrmin creates a Velero `BackupStorageLocation` for it. After a few
seconds, its phase is `Available`:

```shell
kubectl get backupstoragelocations -n styrmin
```

#### 9e. Load the bundled application drivers

The Styrmin image includes the example drivers in `/styrmin/drivers/`.
Load `infrahub` and `semaphore`:

```shell
styrminctl drivers load-local-version /styrmin/drivers/infrahub
styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

The server and the agent read these paths in their own containers, which
run the same image, so the actions of these drivers run. See
[Actions of a driver loaded from a local directory](../drivers/loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory).

Reload the frontend. It shows one cluster (`local`), one environment
(`local`), and the two drivers.

### 10. Deploy an application

Deploy Infrahub 1.6.0 in the `local` environment:

```shell
styrminctl deployments create infrahub 1.6.0 local --cluster local
```

The output shows the id of the deployment. Follow the deployment:

```shell
styrminctl deployments get <DEPLOYMENT_ID>
```

The status changes from `pending` to `deploying`, then to `running`, after
a few minutes. Infrahub is then available at
`http://infrahub-local.local.styrmin.io:8080`. The deployment page of the
frontend shows the same status and the steps of each task.

To view the flow runs in Prefect, forward a port to the Prefect server in
another terminal:

```shell
kubectl port-forward svc/prefect-server 4200:4200 -n styrmin
```

Then open [http://localhost:4200](http://localhost:4200).

### Pause, resume and delete the installation

| Task | Command |
|------|---------|
| Pause the vCluster and keep its data | `vcluster pause styrmin --driver=docker` |
| Resume the vCluster | `vcluster resume styrmin --driver=docker`, then run the port-forward of step 7 again |
| Delete the vCluster and all its data | `vcluster delete styrmin --driver=docker` |

The vCluster stores its data on a Docker volume, so a pause and a resume
keep the cluster, the environment, the drivers, the deployments and the
backups. To start again with no data, delete the vCluster and start again
from step 2.

### Troubleshooting

`kubectl` connects to another cluster. `vcluster connect` changes your
current context, and a later `kubectl config use-context` changes it back.
Run `vcluster connect styrmin --driver=docker` again.

Port 8080 is in use. The port-forward command fails immediately. Stop the
process that listens on the port, or use another port in both the
`kubectl port-forward` command and the `external_url_port` of the cluster
in step 9a.

A pod is in `ImagePullBackOff`. Check that `STYRMIN_VERSION` is a published
release:

```shell
helm show chart oci://registry.opsmill.io/opsmill/chart/styrmin --version "$STYRMIN_VERSION"
```

`styrminctl` fails with "invalid credentials". Styrmin sets the admin
password at the first install only. If you changed `adminPassword` in
`styrmin-values.yaml` after the first install, use the first password in
the `styrminctl` function, or delete the vCluster and install again.

`styrminctl clusters create` fails because the cluster exists. A previous
run created it. List the existing records with `styrminctl clusters list`
and `styrminctl environments list`, and continue with the next step.

### Next steps

- [Platform overview](../introduction/platform-overview.md): the
  components and terms of Styrmin.
- [What is an application driver?](../concepts-and-architecture/what-is-a-driver.md):
  the specification that Styrmin uses to deploy each application.
- [Install Styrmin on DigitalOcean](./digitalocean.md): install Styrmin on
  a managed Kubernetes cluster.
