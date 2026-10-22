---
title: Install Styrmin on DigitalOcean
sidebar_label: DigitalOcean
sidebar_position: 2
description: Deploy Styrmin on a DigitalOcean Kubernetes cluster (DOKS) with Spaces-backed backups and hostname-based ingress, using the published Styrmin container image and Helm chart.
---

## Install Styrmin on DigitalOcean

This guide installs Styrmin on a
[DigitalOcean Kubernetes](https://www.digitalocean.com/products/kubernetes)
cluster (DOKS), with two DigitalOcean load balancers (one for the
Styrmin control plane, one for application traffic) and a DigitalOcean
Spaces bucket for Velero backups. At the end, you deploy **Infrahub** and
**Semaphore** through Styrmin and open them by hostname.

This guide installs the **published** Styrmin container image and Helm
chart from `registry.opsmill.io`, so you do not need a source checkout,
`docker build`, or `helm dependency update`. To run Styrmin from a
source checkout, for example to contribute, see the
[Quickstart](./quickstart.md).

### Architecture

```text
                     ┌────────────────────────────────────────┐
                     │  DigitalOcean Kubernetes (DOKS)        │
                     │                                        │
   demo.styrmin.app  │  ┌──────────┐    ┌──────────────────┐  │
   ──FRONT_LB──────► │  │ Traefik  │ ─► │ styrmin-server   │  │
                     │  │ (front)  │    │ + agent + prefect│  │
                     │  └──────────┘    └──────────────────┘  │
                     │                                        │
   *.styrmin.io      │  ┌──────────┐    ┌──────────────────┐  │
   ──APPS_LB───────► │  │ Traefik  │ ─► │ Infrahub /       │  │
                     │  │ (apps,   │    │ Semaphore / …    │  │
                     │  │ per-env) │    │  deployments     │  │
                     │  └──────────┘    └──────────────────┘  │
                     │                                        │
                     │           DO Spaces (Velero backups)   │
                     └────────────────────────────────────────┘
```

- The **front** load balancer terminates traffic to `demo.styrmin.app` and
  routes it to the Styrmin GraphQL API and frontend.
- The **apps** load balancer terminates wildcard traffic to
  `*.styrmin.io` and routes it to the Traefik ingress controller of each
  environment. Styrmin creates one dedicated Traefik controller per
  environment.
- Velero stores the backups of every deployment in the environment in
  one DigitalOcean Spaces bucket.

### Prerequisites

You need the following on your `PATH`:

- [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/) — DigitalOcean CLI
- [`helm`](https://helm.sh/docs/intro/install/) ≥ 3.8 (OCI support)
- [`kubectl`](https://kubernetes.io/docs/tasks/tools/)
- [`styrminctl`](./quickstart.md) — the Styrmin CLI

You also need:

- A DigitalOcean account with billing enabled.
- A registered domain. This guide uses `demo.styrmin.app` for the control
  plane and `*.styrmin.io` for applications; replace them with your own.

Helm pulls the Styrmin chart, and the cluster pulls the Styrmin image,
from the public OCI registry at `registry.opsmill.io`, so you do not need
a DigitalOcean container registry.

### 1. Authenticate with DigitalOcean

```shell
doctl auth init
```

### 2. Create a Spaces bucket for Velero backups

Velero stores backup data in an S3-compatible object store. Create a
Spaces bucket in the same region as your cluster (this guide uses
`ams3`).

1. Create the bucket, for example named `styrmin-velero`, from the
   [DigitalOcean control panel](https://cloud.digitalocean.com/spaces).
2. Create Spaces access keys for this bucket with `doctl`:

   ```shell
   doctl spaces keys create styrmin-velero-key \
     --grants 'bucket=styrmin-velero;permission=readwrite'
   ```

Record the returned **Access Key** and **Secret Key**. You need them in
[step 10](#10-create-a-backup-storage-location).

### 3. One-time infrastructure setup

Create two load balancers and one Kubernetes cluster. Create the load
balancers first: when you install Traefik, you pass a load balancer's ID
in the `kubernetes.digitalocean.com/load-balancer-id` annotation, and
DOKS then uses that load balancer instead of creating a new one for each
Service.

#### 3a. Front load balancer (Styrmin control plane)

```shell
doctl compute load-balancer create \
  --name ams3-load-balancer-styrmin-front \
  --region ams3 \
  --size lb-small \
  --forwarding-rules entry_protocol:tcp,entry_port:80,target_protocol:tcp,target_port:80 \
  --health-check protocol:http,port:80,path:/,check_interval_seconds:10,response_timeout_seconds:5,healthy_threshold:5,unhealthy_threshold:3
```

Record the returned **ID** and **IP**, referred to as `<FRONT_LB_ID>`
and `<FRONT_LB_IP>` below.

#### 3b. Apps load balancer (application ingress)

```shell
doctl compute load-balancer create \
  --name ams3-load-balancer-styrmin-apps \
  --region ams3 \
  --size lb-small \
  --forwarding-rules entry_protocol:tcp,entry_port:80,target_protocol:tcp,target_port:80 \
  --health-check protocol:http,port:80,path:/,check_interval_seconds:10,response_timeout_seconds:5,healthy_threshold:5,unhealthy_threshold:3
```

Record the returned **ID** and **IP**, referred to as `<APPS_LB_ID>`
and `<APPS_LB_IP>` below.

#### 3c. DNS

Create these DNS records at your registrar:

| Record           | Type | Target           |
|------------------|------|------------------|
| `demo.styrmin.app` | `A`  | `<FRONT_LB_IP>`  |
| `*.styrmin.io`     | `A`  | `<APPS_LB_IP>`   |

If you use your own hostnames, use them in every later step, including
[step 8](#8-create-a-cluster-record), which records the FQDN suffix on
the cluster.

#### 3d. Kubernetes cluster

```shell
doctl kubernetes cluster create styrmin-demo \
  --region ams3 \
  --version 1.35.1-do.0 \
  --node-pool "name=worker-pool;size=s-2vcpu-4gb;count=2"
```

`doctl` writes the kubeconfig and switches your current context to the
new cluster.

### 4. Connect to the cluster

```shell
kubectl get nodes  # verify connectivity
```

The output lists two `Ready` nodes.

### 5. Install Traefik (front ingress controller)

Install Traefik as the cluster-wide ingress controller, on the front load
balancer you created in step 3a:

```shell
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm upgrade --install traefik traefik/traefik \
  --create-namespace \
  -n styrmin \
  --set service.annotations."kubernetes\.digitalocean\.com/load-balancer-id"=<FRONT_LB_ID> \
  --set ingressClass.enabled=false \
  --set rbac.namespaced=true \
  --wait \
  --timeout 3m
```

With the `load-balancer-id` annotation, the DigitalOcean cloud controller
attaches this Service to the existing load balancer instead of creating a
new one.

### 6. Install Styrmin from the published Helm chart

Create a values file with the public hostname and the ingress class of
your install, and save it as `do-values.yaml`:

```yaml
# do-values.yaml
ingress:
  enabled: true
  annotations:
    kubernetes.io/ingress.class: traefik
  hosts:
    - host: demo.styrmin.app
      paths:
        - path: /
          pathType: Prefix
```

Then install Styrmin from the OCI registry. The chart pins its agent
subchart and Bitnami dependencies, so you do not run
`helm dependency update`. Set `--version` to a published release, such
as `0.1.24`, or leave it out to install the latest published release.

```shell
helm upgrade --install styrmin \
  oci://registry.opsmill.io/opsmill/chart/styrmin \
  --version 0.1.24 \
  --create-namespace \
  -n styrmin \
  -f do-values.yaml \
  --wait \
  --timeout 5m
```

The chart sets `image.registry` to `registry.opsmill.io/opsmill` by
default, so the cluster pulls the server and agent images of the same
release from the public registry. You do not need an `image.repository`
override or an `imagePullSecret`.

### 7. Access the Styrmin API

When Helm finishes, the GraphQL API is available through the front load
balancer at:

```text
https://demo.styrmin.app/graphql
```

To debug from your machine, you can also port-forward the server:

```shell
kubectl port-forward svc/styrmin-server 8000:8000 -n styrmin &
```

The next steps run [`styrminctl`](./quickstart.md) against the public
URL. Export it once:

```shell
export STYRMIN_SERVER_ADDRESS=https://demo.styrmin.app
```

### 8. Create a cluster record

Register the DOKS cluster with Styrmin. `fqdn_suffix` is the wildcard
domain from step 3c, and `standard_storage` sets the DigitalOcean
block-storage CSI driver as the default `StorageClass`:

```shell
styrminctl clusters create do-demo \
  -c '{"fqdn_suffix": "styrmin.io", "standard_storage": {"storage_class": "do-block-storage"}}'
```

Record the returned `id`, referred to as `<CLUSTER_ID>` below.

### 9. Create an environment

The environment contains its own ingress configuration. The
`dedicated_ingress.service.annotations` block attaches the environment's
Traefik controller, which Styrmin creates, to the **apps** load balancer
from step 3b:

```shell
styrminctl environments create demo <CLUSTER_ID> \
  -c '{"ip_whitelist": ["0.0.0.0/0"], "dedicated_ingress": {"service": {"annotations": {"kubernetes.digitalocean.com/load-balancer-id": "<APPS_LB_ID>"}}}}'
```

Record the returned `id`, referred to as `<ENVIRONMENT_ID>` below.

Any `dedicated_ingress` object enables the environment's own controller,
including an empty one (`{}`), which uses the default values: Traefik
with a `LoadBalancer` Service. To route through the cluster's shared
ingress controller instead, leave the key out of both the cluster and
the environment configuration.

> **Restrict `ip_whitelist` before production.** `0.0.0.0/0` accepts
> traffic from any address. List only the addresses that need access.

### 10. Create a backup storage location

Register the Spaces bucket from step 2 as a backup storage location
(BSL). Replace the placeholders with your Spaces keys:

```shell
styrminctl backup-locations create do-spaces \
  --endpoint https://ams3.digitaloceanspaces.com \
  --bucket styrmin-velero \
  --region ams3 \
  --access-key-id <DO_SPACES_ACCESS_KEY> \
  --secret-access-key <DO_SPACES_SECRET_KEY>
```

Record the returned `id`, referred to as `<BSL_ID>` below.

### 11. Assign the backup storage location to the environment

Assign the BSL to the environment, so every deployment in the
environment stores its backups in the same Spaces bucket:

```shell
styrminctl backup-locations assign <ENVIRONMENT_ID> <BSL_ID>
```

### 12. Load application drivers

The published Styrmin image includes the example drivers at
`/styrmin/drivers/`. Load the drivers you want to deploy:

```shell
styrminctl drivers load-local-version /styrmin/drivers/infrahub
styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

To load a driver from a public or private git repository instead, see
[Load a driver](../drivers/loading-drivers.md).

### 13. Deploy Infrahub

```shell
styrminctl deployments create infrahub 1.6.0 <ENVIRONMENT_ID>
```

### 14. Deploy Semaphore

```shell
styrminctl deployments create semaphore 2.16.47 <ENVIRONMENT_ID>
```

### 15. Monitor deployments

```shell
styrminctl deployments get <DEPLOYMENT_ID>
```

To follow the Prefect flow runs of each task, port-forward the Prefect
UI:

```shell
kubectl port-forward svc/prefect-server 4200:4200 -n styrmin &
```

Then open [http://localhost:4200](http://localhost:4200).

### 16. Open the applications

When the deployments are running, the environment's Traefik controller
routes requests to them by hostname, through the apps load balancer:

- Infrahub: `http://infrahub-<DEPLOYMENT_ID>.styrmin.io`
- Semaphore: `http://semaphore-<DEPLOYMENT_ID>.styrmin.io`

The `*.styrmin.io` record already points to the apps load balancer, so
you add no DNS record for each deployment.

### Delete the installation

You created both load balancers outside Kubernetes. Before you delete
the cluster, add the `service.kubernetes.io/do-loadbalancer-disown`
annotation to the Traefik Services, so DigitalOcean does not delete the
load balancers with the cluster:

```shell
# Disown the load balancers so DigitalOcean keeps them when it deletes the cluster
kubectl annotate svc --all-namespaces -l app.kubernetes.io/name=traefik \
  service.kubernetes.io/do-loadbalancer-disown="true"
```

Then delete the cluster:

```shell
doctl kubernetes cluster delete styrmin-demo
```

To remove everything, also delete:

- the front and apps load balancers (`doctl compute load-balancer delete <id>`),
- the Spaces bucket and access keys,
- the DNS records.

### Troubleshooting

**The Traefik install does not finish.** The `<FRONT_LB_ID>` annotation
must match a load balancer that exists in the same region as the
cluster. Run `doctl compute load-balancer list` to check.

**`helm pull` / `helm install` fails with `not found` on the OCI URL.**
The published chart is at
`oci://registry.opsmill.io/opsmill/chart/styrmin`. Check that your Helm
version is 3.8 or later (`helm version`): earlier releases do not
support OCI registries. If `--version` names a release that does not
exist, run the command without `--version` to install the latest
release, or set it to a published release.

**`do-block-storage` PVCs stay `Pending`.** Check that the DigitalOcean
block-storage CSI driver is enabled on the cluster (DOKS 1.20 and later
enable it by default). `kubectl get sc` lists `do-block-storage` as the
default.

**Applications return 404 from `*.styrmin.io`.** Check that
`*.styrmin.io` resolves to `<APPS_LB_IP>`: an outdated record sends
requests to another address, and no component reports an error. Also
check that the environment's Traefik controller is `Running` in the
environment's namespace.

**Velero backups fail with `403 SignatureDoesNotMatch`.** Check the
endpoint (`https://<region>.digitaloceanspaces.com`), the region
(`ams3`, `nyc3`, …), and that the access key has `readwrite` permission
on the bucket.

### Next steps

- [**Platform overview**](../introduction/platform-overview.md): the
  components and terms of Styrmin.
- [**What is an application driver?**](../concepts-and-architecture/what-is-a-driver.md):
  the specification that Styrmin uses to deploy each application.
- [**Create a driver**](../drivers/creating-a-driver.md): write your own
  driver and load it into the cluster.
