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
| `kubectl` | Waits for deployments and port-forwards Traefik |

DNS for the demo hostname `styrmin.local.styrmin.io` is provided by the
Cloudflare-hosted wildcard `*.local.styrmin.io` → `127.0.0.1`; no
`/etc/hosts` edit is needed.

## Commands

| Command | Description |
|---------|-------------|
| `uv run invoke build` | Build the `registry.opsmill.io/opsmill/styrmin:latest` image and update Helm dependencies |
| `uv run invoke start` | Create the vCluster and deploy everything end-to-end |
| `uv run invoke stop` | Pause the environment (`vcluster pause`), preserving state |
| `uv run invoke destroy` | Delete the vCluster and all associated resources |
| `uv run invoke reset` | `destroy` + `start` — start fresh |

`start` auto-builds the image if it's missing. Pass `--build-image` to
force a rebuild.

## Access URLs

After `start` completes, the summary panel prints the demo URL:

```
http://styrmin.local.styrmin.io:8080
```

`start` backgrounds a `kubectl port-forward svc/traefik 8080:80` (PID
recorded at `.vcluster/traefik.pid`) and `stop` tears it down. The
non-privileged port is needed on macOS, and we use it on Linux too so
the flow is identical across platforms.

The GraphQL endpoint is the same base URL + `/graphql`.

The MinIO console is reachable on demand via:

```bash
kubectl port-forward svc/minio 9001:9001 -n styrmin
```

Credentials: `minioadmin / minioadmin`.

## Platform notes

- **Traefik exposure**: Installed with `service.type=ClusterIP` on every
  platform and reached via a backgrounded `kubectl port-forward
  svc/traefik 8080:80`. We avoid `service.type=LoadBalancer` (and
  vCluster's embedded LB provider) on Linux for parity with macOS — one
  code path, one access URL, no host-network surprises.
- **Single shared ingress**: The demo cluster is bootstrapped with
  `ingress_class=traefik` only — `dedicated_ingress` is intentionally
  omitted so every deployment's Ingress is served by the one front-door
  Traefik. The per-environment dedicated-Traefik path exists for
  multi-environment isolation in production and would not be reachable
  through the single port-forward.

## Troubleshooting

**`invoke start` hangs on "Waiting for the Styrmin server to be ready"**
— check `kubectl get pods -n styrmin` for pending/errored pods. Postgres
takes the longest on first start (it initializes the `prefect` database).

**URL works briefly then stops responding** — the backgrounded
port-forward died. Check `/tmp/styrmin-traefik-portforward.log`, then
re-run `uv run invoke start` to restart it (safely idempotent).

**Bootstrap fails with "Cluster already exists"** — expected on a
re-run; `start` catches this and continues. The bootstrap records
(`local` cluster, `local` environment, `infrahub` driver) persist across
`stop`/`start` cycles because the Postgres PVC is preserved.

**Want to rebuild the image?** Use `uv run invoke start --build-image`
or `uv run invoke build` followed by `uv run invoke start`.
