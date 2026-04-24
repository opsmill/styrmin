# Styrmin MVP

Styrmin is a deployment orchestration platform.

## Local Demo

### 0. Prerequisites

In order to run the demo, you must have the following tools installed locally

- [`kind`](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)
- [`helm`](https://helm.sh/docs/intro/install/)
- [Docker](https://docs.docker.com/get-docker/)
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)

### 1. Install the Python environment

```shell
uv sync --all-groups --all-packages
```

This installs all dependencies (including dev tools) and ensures the CLI and SDK workspace packages are available locally.

### 2. Set up the cluster and start services

```shell
uv run invoke cluster.create cluster.connect cluster.init   # Create a local kind cluster and Install required CRDs via Helm
uv run invoke cluster.minio                                 # Install MinIO for backup storage
uv run invoke dev.build dev.start                           # Build the Docker image and start all services
```

After `dev.start`, the following services are available:

| Service      | URL                                        |
|--------------|--------------------------------------------|
| Styrmin API  | `http://localhost:8000/graphql`            |
| Prefect UI   | `http://localhost:4200`                    |

### 3. Bootstrap Styrmin entities

```shell
uv run invoke dev.bootstrap
```

This creates the cluster record, environment, application driver, and loads the `infrahub` driver version.

### 4. Deploy

Open the Bruno collection in `api-collection/` and run **Deploy Infrahub** (seq 8).

You can monitor the deployment with **Get deployment** (seq 10) and track async tasks in the Prefect UI.

### Teardown

```shell
uv run invoke dev.stop dev.clean   # Stop and remove volumes
uv run invoke cluster.delete       # Delete the kind cluster
```

## DigitalOcean Demo

This section walks through deploying Styrmin on a DigitalOcean Kubernetes cluster, then using it to deploy **Infrahub** and **Semaphore** with ingress access.

### 0. Prerequisites

- [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/) — DigitalOcean CLI
- [`helm`](https://helm.sh/docs/intro/install/)
- [`kubectl`](https://kubernetes.io/docs/tasks/tools/)
- [Docker](https://docs.docker.com/get-docker/)

### 1. Authenticate with DigitalOcean

```shell
doctl auth init
```

### 2. Create a DO Spaces bucket for Velero backups

Velero stores backup data in an S3-compatible object store. Create a Spaces bucket in the same region as your cluster.

Create the bucket `styrmin-velero` on the DigitalOcean control panel.

Create Spaces access keys with `doctl`:

```shell
doctl spaces keys create styrmin-velero-key \
  --grants 'bucket=styrmin-velero;permission=readwrite'
```

Note the returned **Access Key** and **Secret Key** — you will use them in step 11 when creating the backup storage location via the Styrmin API.

### 3. One-time infrastructure setup

Create the load balancers and Kubernetes cluster (skip if already provisioned):

```shell
# Load balancer for the Styrmin front (server ingress)
doctl compute load-balancer create \
  --name ams3-load-balancer-styrmin-front \
  --region ams3 \
  --size lb-small \
  --forwarding-rules entry_protocol:tcp,entry_port:80,target_protocol:tcp,target_port:80 \
  --health-check protocol:http,port:80,path:/,check_interval_seconds:10,response_timeout_seconds:5,healthy_threshold:5,unhealthy_threshold:3
```

Note the returned **ID** and **IP** — referred to as `<FRONT_LB_ID>` and `<FRONT_LB_IP>` below.

```shell
# Load balancer for application ingress
doctl compute load-balancer create \
  --name ams3-load-balancer-styrmin-apps \
  --region ams3 \
  --size lb-small \
  --forwarding-rules entry_protocol:tcp,entry_port:80,target_protocol:tcp,target_port:80 \
  --health-check protocol:http,port:80,path:/,check_interval_seconds:10,response_timeout_seconds:5,healthy_threshold:5,unhealthy_threshold:3
```

Note the returned **ID** and **IP** — referred to as `<APPS_LB_ID>` and `<APPS_LB_IP>` below.

> **DNS:** Configure the following DNS records pointing to the load balancer IPs:
>
> | Record | Target |
> |--------|--------|
> | `demo.styrmin.app` | `<FRONT_LB_IP>` |
> | `*.styrmin.io` | `<APPS_LB_IP>` |

```shell
# Kubernetes cluster (2 nodes, 2 vCPU / 4 GB each)
doctl kubernetes cluster create styrmin-demo \
  --region ams3 \
  --version 1.35.1-do.0 \
  --node-pool "name=worker-pool;size=s-2vcpu-4gb;count=2"
```

### 4. Connect to the cluster

```shell
kubectl get nodes  # verify connectivity
```

### 5. Build and push the Styrmin image

```shell
docker buildx build --platform linux/amd64 -t 9r2s1098.c1.gra9.container-registry.ovh.net/opsmill/styrmin:latest -f docker/Dockerfile --push .
```

### 6. Install Traefik ingress controller

Install Traefik as the cluster-wide ingress controller, reusing the front load balancer:

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

### 8. Access the Styrmin API

The GraphQL API is available at `https://demo.styrmin.app/graphql` via ingress.

> **Tip:** For local debugging, you can still port-forward:
>
> ```shell
> kubectl port-forward svc/styrmin-server 8000:8000 -n styrmin &
> ```

### 9. Create a cluster record

```shell
export STYRMIN_SERVER_ADDRESS=https://demo.styrmin.app
uv run styrminctl clusters create do-demo \
  -c '{"fqdn_suffix": "styrmin.io", "standard_storage": {"storage_class": "do-block-storage"}}'
```

Note the returned `id` — you will need it in the next step.

### 10. Create an environment

Replace `<CLUSTER_ID>` and `<APPS_LB_ID>` with the values from earlier steps:

```shell
uv run styrminctl environments create demo <CLUSTER_ID> \
  -c '{"ip_whitelist": ["0.0.0.0/0"], "dedicated_ingress": {"service": {"annotations": {"kubernetes.digitalocean.com/load-balancer-id": "<APPS_LB_ID>"}}}}'
```

This configures the dedicated ingress controller (Traefik) to reuse the apps load balancer for application routing.

Note the returned `id`.

### 11. Create a backup storage location

Register the DO Spaces bucket created in step 2 as a backup storage location. Replace the placeholders with your Spaces credentials:

```shell
uv run styrminctl backup-locations create do-spaces \
  --endpoint https://ams3.digitaloceanspaces.com \
  --bucket styrmin-velero \
  --region ams3 \
  --access-key-id <DO_SPACES_ACCESS_KEY> \
  --secret-access-key <DO_SPACES_SECRET_KEY>
```

Note the returned `id` — referred to as `<BSL_ID>` below.

### 12. Assign the backup storage location to the environment

Link the BSL to the environment so that all deployments in this environment store backups in the DO Spaces bucket:

```shell
uv run styrminctl backup-locations assign <ENVIRONMENT_ID> <BSL_ID>
```

### 13. Load application drivers

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

> **Note:** The driver examples are baked into the Docker image at `/styrmin/drivers/`. Each subdirectory contains a complete driver specification.

### 14. Deploy Infrahub

```shell
uv run styrminctl deployments create infrahub 1.6.0 <ENVIRONMENT_ID>
```

### 15. Deploy Semaphore

```shell
uv run styrminctl deployments create semaphore 2.16.47 <ENVIRONMENT_ID>
```

### 16. Monitor deployments

Check deployment status (replace `<DEPLOYMENT_ID>` with the ID returned by the deploy command):

```shell
styrminctl deployments get <DEPLOYMENT_ID>
```

You can also forward the Prefect UI to monitor async tasks:

```shell
kubectl port-forward svc/prefect-server 4200:4200 -n styrmin &
```

Then open `http://localhost:4200` in your browser.

### 17. Access applications via Ingress

Once deployed, Styrmin automatically provisions a **dedicated Traefik ingress controller** per environment and configures ingress routes for each application.

The applications are accessible via hostname-based routing through the apps load balancer:

- Infrahub: `http://infrahub-<DEPLOYMENT_ID>.styrmin.io`
- Semaphore: `http://semaphore-<DEPLOYMENT_ID>.styrmin.io`

### Teardown

Before deleting the cluster, disown the load balancers so they are not destroyed along with it. The `service.kubernetes.io/do-loadbalancer-disown` annotation tells DigitalOcean to keep the LB when its owning Service is removed.

```shell
# Disown the load balancers
kubectl annotate svc --all-namespaces -l app.kubernetes.io/name=traefik\
  service.kubernetes.io/do-loadbalancer-disown="true"
```

Once the LBs are disowned, delete the cluster:

```shell
doctl kubernetes cluster delete styrmin-demo
```

## Local Drivers

Drivers in `driver/examples/` are mounted read-only at `/styrmin/drivers/` inside the containers. The `infrahub` driver is ready to use out of the box.

To add your own driver, place it in `driver/examples/<name>/` and load it via:

```graphql
mutation {
  loadLocalApplicationDriverVersion(path: "/styrmin/drivers/<name>") {
    id
    version
  }
}
```

## Using a Private GitHub Repository (Optional)

To import drivers from a private GitHub repository, set the following environment variables (e.g. in a `.env` file at the project root):

```shell
STYRMIN_DRIVER_TOKEN=<github-token>           # Token for the driver repository
STYRMIN_AGENT_SOURCE_TOKEN=<github-token>     # Token for the agent code repository
STYRMIN_AGENT_SOURCE_BRANCH=develop           # Branch to use (default: develop)
STYRMIN_AGENT_SOURCE_REPOSITORY=https://github.com/your-org/styrmin-mvp.git
```

Then use the **Load application driver from Github** Bruno request instead of the local driver loader.

## Terminology

| Term | Description |
|------|-------------|
| **Application Driver** | Versioned deployment spec defining how an application is deployed (Helm chart, components, actions) |
| **Driver Version** | A specific version of a driver, sourced from a git repository or a local directory |
| **Cluster** | A Kubernetes cluster registered in Styrmin |
| **Environment** | A logical deployment target bound to a cluster |
| **Deployment** | A desired state declaration for an application on an environment |
| **Task Worker** | Prefect worker that executes async backend tasks on behalf of the server |
| **K8s Agent** | Prefect worker running inside the Kubernetes cluster, executing in-cluster actions |
