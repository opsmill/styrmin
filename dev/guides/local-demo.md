# Local Demo on vCluster

A turnkey local Styrmin environment — server, agent, Prefect, Postgres,
MinIO, Velero, and a Traefik ingress — running entirely inside a vCluster.
Four top-level invoke commands drive the full lifecycle.

## Prerequisites

| Tool | Used for |
|------|----------|
| `docker` | Runs the vCluster node and builds the Styrmin image |
| `vcluster` | Creates the virtual Kubernetes cluster |
| `helm` | Installs Styrmin, Traefik, Velero, and MinIO |
| `kubectl` | Waits for deployments and (on macOS) port-forwards Traefik |

DNS for the demo hostname `styrmin.local.styrmin.app` is provided by the
Cloudflare-hosted wildcard `*.local.styrmin.app` → `127.0.0.1`; no
`/etc/hosts` edit is needed.

## Commands

| Command | Description |
|---------|-------------|
| `uv run invoke build` | Build the `styrmin:latest` image and update Helm dependencies |
| `uv run invoke start` | Create the vCluster and deploy everything end-to-end |
| `uv run invoke stop` | Pause the environment (`vcluster pause`), preserving state |
| `uv run invoke destroy` | Delete the vCluster and all associated resources |
| `uv run invoke reset` | `destroy` + `start` — start fresh |

`start` auto-builds the image if it's missing. Pass `--build-image` to
force a rebuild.

## Access URLs

After `start` completes, the summary panel prints the demo URLs:

- **Linux**: `https://styrmin.local.styrmin.app`
- **macOS**: `https://styrmin.local.styrmin.app:4443`

The port difference is because macOS cannot bind privileged ports
(80/443) without root; `start` backgrounds a
`kubectl port-forward svc/traefik 8080:80 4443:443` instead, and `stop`
tears it down.

The GraphQL endpoint is the same base URL + `/graphql`.

The MinIO console is reachable on demand via:

```bash
kubectl port-forward svc/minio 9001:9001 -n styrmin
```

Credentials: `minioadmin / minioadmin`.

## Platform notes

- **Linux**: Traefik is installed with `service.type=LoadBalancer`.
  vCluster's embedded LB provider routes traffic from the host to the
  service — the browser can hit port 443 directly.
- **macOS** (and other non-Linux platforms): Traefik is installed with
  `service.type=ClusterIP` and a backgrounded `kubectl port-forward`
  exposes it on 8080/4443. The PID is recorded at
  `.vcluster/traefik.pid`.

## Troubleshooting

**`invoke start` hangs on "Waiting for the Styrmin server to be ready"**
— check `kubectl get pods -n styrmin` for pending/errored pods. Postgres
takes the longest on first start (it initializes the `prefect` database).

**Linux: Traefik service stays in `<pending>` external IP** — the vCluster
embedded LB provider did not pick up the service. Verify with
`vcluster list` that the cluster is `Running`, then
`kubectl describe svc traefik -n styrmin`.

**macOS: URL works briefly then stops responding** — the backgrounded
port-forward died. Check `/tmp/styrmin-traefik-portforward.log`, then
re-run `uv run invoke start` to restart it (safely idempotent).

**Bootstrap fails with "Cluster already exists"** — expected on a
re-run; `start` catches this and continues. The bootstrap records
(`local` cluster, `local` environment, `infrahub` driver) persist across
`stop`/`start` cycles because the Postgres PVC is preserved.

**Want to rebuild the image?** Use `uv run invoke start --build-image`
or `uv run invoke build` followed by `uv run invoke start`.
