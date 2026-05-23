---
title: DigitalOcean
sidebar_position: 2
description: Deploy Styrmin on a DigitalOcean Kubernetes cluster (DOKS) with Spaces-backed backups and hostname-based ingress.
---

## DigitalOcean

This guide walks through deploying Styrmin on a
[DigitalOcean Kubernetes](https://www.digitalocean.com/products/kubernetes)
cluster (DOKS), wiring it up with two DigitalOcean Load Balancers
(one for the Styrmin control plane, one for application traffic) and a
DigitalOcean Spaces bucket for Velero backups. At the end you'll deploy
**Infrahub** and **Semaphore** through Styrmin and reach them via
hostname-based ingress.

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
  `*.styrmin.io` and routes it to each deployment's own Traefik ingress
  controller. Styrmin provisions one dedicated Traefik per environment.
- Velero backs every deployment in the environment up to a single
  DigitalOcean Spaces bucket.

### Prerequisites

You need the following on your `PATH`:

- [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/) — DigitalOcean CLI
- [`helm`](https://helm.sh/docs/intro/install/) ≥ 3.x
- [`kubectl`](https://kubernetes.io/docs/tasks/tools/)
- [Docker](https://docs.docker.com/get-docker/) (for building the Styrmin image)
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (for running `styrminctl`)

You also need:

- A DigitalOcean account with billing enabled.
- A registered domain (this guide uses `demo.styrmin.app` for the control
  plane and `*.styrmin.io` for applications — substitute your own).
- A container registry that DOKS can pull from. The README uses an OVH
  Cloud registry; any public or DOKS-reachable private registry works.

### 1. Authenticate with DigitalOcean

```shell
doctl auth init
```

### 2. Create a Spaces bucket for Velero backups

Velero stores backup data in an S3-compatible object store. Create a
Spaces bucket in the same region as your cluster (this guide uses
`ams3`).

1. Create the bucket — for example named `styrmin-velero` — from the
   [DigitalOcean control panel](https://cloud.digitalocean.com/spaces).
2. Create scoped Spaces access keys with `doctl`:

   ```shell
   doctl spaces keys create styrmin-velero-key \
     --grants 'bucket=styrmin-velero;permission=readwrite'
   ```

Record the returned **Access Key** and **Secret Key**. You'll need them
in [step 11](#11-create-a-backup-storage-location).

### 3. One-time infrastructure setup

You'll provision two load balancers and one Kubernetes cluster. The load
balancers are created _before_ the cluster so their IDs can be passed in
when Traefik is installed — DOKS will then adopt them via the
`kubernetes.digitalocean.com/load-balancer-id` annotation rather than
provisioning a new one per Service.

#### 3a. Front load balancer (Styrmin control plane)

```shell
doctl compute load-balancer create \
  --name ams3-load-balancer-styrmin-front \
  --region ams3 \
  --size lb-small \
  --forwarding-rules entry_protocol:tcp,entry_port:80,target_protocol:tcp,target_port:80 \
  --health-check protocol:http,port:80,path:/,check_interval_seconds:10,response_timeout_seconds:5,healthy_threshold:5,unhealthy_threshold:3
```

Record the returned **ID** and **IP** — referred to as `<FRONT_LB_ID>`
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

Record the returned **ID** and **IP** — referred to as `<APPS_LB_ID>`
and `<APPS_LB_IP>` below.

#### 3c. DNS

Configure the following DNS records at your registrar:

| Record           | Type | Target           |
|------------------|------|------------------|
| `demo.styrmin.app` | `A`  | `<FRONT_LB_IP>`  |
| `*.styrmin.io`     | `A`  | `<APPS_LB_IP>`   |

If you use your own hostnames, substitute them in every subsequent step
(including [step 9](#9-create-a-cluster-record) where the FQDN suffix is
recorded on the Cluster).

#### 3d. Kubernetes cluster

```shell
doctl kubernetes cluster create styrmin-demo \
  --region ams3 \
  --version 1.35.1-do.0 \
  --node-pool "name=worker-pool;size=s-2vcpu-4gb;count=2"
```

`doctl` automatically writes the kubeconfig and switches your context to
the new cluster.

### 4. Connect to the cluster

```shell
kubectl get nodes  # verify connectivity
```

You should see two `Ready` nodes.

### 5. Build and push the Styrmin image

DOKS needs to be able to pull `styrmin:latest` from a registry it can
reach. Substitute your own registry URL in the command below — the
example uses an OVH container registry:

```shell
docker buildx build \
  --platform linux/amd64 \
  -t <registry>/opsmill/styrmin:latest \
  -f docker/Dockerfile \
  --push .
```

If the registry is private, also create an `imagePullSecret` in the
`styrmin` namespace and reference it from `demo/do-values.yaml`.

### 6. Install Traefik (front ingress controller)

Install Traefik as the cluster-wide ingress controller, reusing the
front load balancer you created in step 3a:

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

The `load-balancer-id` annotation tells the DigitalOcean cloud
controller to attach this Service to the existing load balancer rather
than provisioning a new one.

### 7. Install Styrmin via Helm

```shell
helm dependency update helm/agent
helm dependency update helm/styrmin
helm upgrade --install styrmin helm/styrmin \
  --dependency-update \
  --create-namespace \
  -n styrmin \
  -f demo/do-values.yaml \
  --wait \
  --timeout 5m
```

`demo/do-values.yaml` is the DigitalOcean-flavoured values file (image
repository, host, ingress class, …). Review it before installing — at
minimum you'll want to point `image.repository` at the registry you
pushed to in step 5.

### 8. Access the Styrmin API

Once Helm finishes, the GraphQL API is available through the front load
balancer at:

```text
https://demo.styrmin.app/graphql
```

For local debugging you can still port-forward:

```shell
kubectl port-forward svc/styrmin-server 8000:8000 -n styrmin &
```

From here on, every step uses [`styrminctl`](../installation/quickstart.md)
against the public URL. Export it once:

```shell
export STYRMIN_SERVER_ADDRESS=https://demo.styrmin.app
```

### 9. Create a Cluster record

Register the DOKS cluster with Styrmin. The `fqdn_suffix` is the wildcard
domain you configured in step 3c, and `standard_storage` selects the
DigitalOcean block-storage CSI driver as the default `StorageClass`:

```shell
uv run styrminctl clusters create do-demo \
  -c '{"fqdn_suffix": "styrmin.io", "standard_storage": {"storage_class": "do-block-storage"}}'
```

Record the returned `id` — referred to as `<CLUSTER_ID>` below.

### 10. Create an Environment

The environment carries the per-environment ingress configuration. The
`dedicated_ingress.service.annotations` block tells the per-environment
Traefik controller (which Styrmin provisions for you) to attach to the
**apps** load balancer from step 3b:

```shell
uv run styrminctl environments create demo <CLUSTER_ID> \
  -c '{"ip_whitelist": ["0.0.0.0/0"], "dedicated_ingress": {"service": {"annotations": {"kubernetes.digitalocean.com/load-balancer-id": "<APPS_LB_ID>"}}}}'
```

Record the returned `id` — referred to as `<ENVIRONMENT_ID>` below.

> **Tighten the IP whitelist before production.** `0.0.0.0/0` is open to
> the public internet — use a real allowlist for non-demo workloads.

### 11. Create a backup storage location

Register the Spaces bucket from step 2 as a backup storage location.
Substitute your Spaces credentials:

```shell
uv run styrminctl backup-locations create do-spaces \
  --endpoint https://ams3.digitaloceanspaces.com \
  --bucket styrmin-velero \
  --region ams3 \
  --access-key-id <DO_SPACES_ACCESS_KEY> \
  --secret-access-key <DO_SPACES_SECRET_KEY>
```

Record the returned `id` — referred to as `<BSL_ID>` below.

### 12. Assign the backup storage location to the environment

Link the BSL to the environment so every deployment in that environment
backs up to the same Spaces bucket:

```shell
uv run styrminctl backup-locations assign <ENVIRONMENT_ID> <BSL_ID>
```

### 13. Load application drivers

The bundled driver examples are baked into the Docker image at
`/styrmin/drivers/`. Load the ones you want to deploy:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

To load a driver from a git repository (public or private) instead, see
[Loading a Driver](../drivers/loading-drivers.md).

### 14. Deploy Infrahub

```shell
uv run styrminctl deployments create infrahub 1.6.0 <ENVIRONMENT_ID>
```

### 15. Deploy Semaphore

```shell
uv run styrminctl deployments create semaphore 2.16.47 <ENVIRONMENT_ID>
```

### 16. Monitor deployments

```shell
uv run styrminctl deployments get <DEPLOYMENT_ID>
```

You can also forward the Prefect UI for a richer view of async tasks:

```shell
kubectl port-forward svc/prefect-server 4200:4200 -n styrmin &
```

Then open [http://localhost:4200](http://localhost:4200).

### 17. Access applications via Ingress

Once the deployments are running, Styrmin's per-environment Traefik
controller publishes them via hostname-based routing through the apps
load balancer:

- Infrahub: `http://infrahub-<DEPLOYMENT_ID>.styrmin.io`
- Semaphore: `http://semaphore-<DEPLOYMENT_ID>.styrmin.io`

Because the apps load balancer is already wired to `*.styrmin.io`, no
extra DNS work is needed per deployment.

### Teardown

Both load balancers were created **outside** the Kubernetes lifecycle and
adopted by annotation, so it's safe to delete the cluster without
deleting them — but only if you tell DigitalOcean explicitly. The
`service.kubernetes.io/do-loadbalancer-disown` annotation does that:

```shell
# Disown the load balancers so they survive the cluster delete
kubectl annotate svc --all-namespaces -l app.kubernetes.io/name=traefik \
  service.kubernetes.io/do-loadbalancer-disown="true"
```

Once the LBs are disowned, delete the cluster:

```shell
doctl kubernetes cluster delete styrmin-demo
```

To fully clean up, also delete:

- the front and apps load balancers (`doctl compute load-balancer delete <id>`),
- the Spaces bucket and access keys,
- the DNS records.

### Troubleshooting

**Helm install hangs on Traefik.** The `<FRONT_LB_ID>` annotation must
match a load balancer that already exists in the same region as the
cluster. Run `doctl compute load-balancer list` to confirm.

**`do-block-storage` PVCs stay `Pending`.** Make sure the cluster has the
DigitalOcean block-storage CSI driver enabled (it is on by default for
DOKS ≥ 1.20). `kubectl get sc` should list `do-block-storage` as default.

**Applications return 404 from `*.styrmin.io`.** Confirm that DNS
resolution actually returns `<APPS_LB_IP>` (a stale `*.styrmin.io` record
will silently break routing) and that the per-environment Traefik
deployment is `Running` in the environment's namespace.

**Velero backups fail with `403 SignatureDoesNotMatch`.** Re-check the
endpoint (`https://<region>.digitaloceanspaces.com`), the region
(`ams3`, `nyc3`, …), and that the access key has `readwrite` on the
exact bucket name.

### Next steps

- [**Platform Overview**](../introduction/platform-overview.md) — how the
  pieces fit together once Styrmin is up.
- [**What is an Application Driver?**](../concepts-and-architecture/what-is-a-driver.md) —
  understand the unit you're deploying.
- [**Creating a Driver**](../drivers/creating-a-driver.md) — write your
  own driver and load it onto the cluster.
