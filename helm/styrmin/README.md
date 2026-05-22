# Styrmin Helm Chart

Helm chart for deploying Styrmin - a deployment orchestration platform for Kubernetes.

## Prerequisites

- Kubernetes 1.23+
- Helm 3.8+
- PV provisioner support in the underlying infrastructure (for PostgreSQL persistence)

## Installation

### Add Helm Repository Dependencies

```bash
# Add Prefect Helm repository
helm repo add prefect https://prefecthq.github.io/prefect-helm

# Add Bitnami Helm repository (for PostgreSQL)
helm repo add bitnami https://charts.bitnami.com/bitnami

# Update repositories
helm repo update
```

### Install the Chart

```bash
# Update chart dependencies
helm dependency update ./helm/styrmin

# Install with default values
helm install styrmin ./helm/styrmin -n styrmin --create-namespace

# Install with custom values
helm install styrmin ./helm/styrmin -n styrmin --create-namespace -f my-values.yaml
```

### Minimal Production Configuration

Create a `values-production.yaml` file:

```yaml
# Image configuration
image:
  registry: your-registry.io
  repository: styrmin
  tag: "0.1.0"

imagePullSecrets:
  - name: registry-credentials

# Enable ingress
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: styrmin.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: styrmin-tls
      hosts:
        - styrmin.example.com

# Prefect UI ingress
prefectIngress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: prefect.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: prefect-tls
      hosts:
        - prefect.example.com

# Styrmin configuration
styrmin:
  logLevel: INFO
  driver:
    token: "your-driver-token"
  agentSource:
    repository: "https://github.com/opsmill/styrmin.git"
    branch: "stable"
    token: "your-github-token"

# PostgreSQL configuration
postgresql:
  auth:
    postgresPassword: "secure-admin-password"
    password: "secure-styrmin-password"
    prefectPassword: "secure-prefect-password"
  primary:
    persistence:
      size: 50Gi
```

Install with production values:

```bash
helm install styrmin ./helm/styrmin -n styrmin --create-namespace -f values-production.yaml
```

## Configuration

### Global Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of styrmin-server replicas | `1` |
| `agentReplicaCount` | Number of agent replicas | `1` |
| `nameOverride` | Override chart name | `""` |
| `fullnameOverride` | Override full name | `""` |

### Image Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.imageRegistry` | Override registry for the styrmin chart **and** the `styrmin-agent` subchart. Wins over the per-chart `image.registry` when non-empty. | `""` |
| `image.registry` | Image registry. Set to `""` to consume a locally-built image. | `registry.opsmill.io/opsmill` |
| `image.repository` | Image repository | `styrmin` |
| `image.tag` | Image tag | `appVersion` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `imagePullSecrets` | Image pull secrets | `[]` |

The agent subchart exposes the same `image.registry` / `image.repository` /
`image.tag` / `image.pullPolicy` surface under the `styrmin-agent` key.
Setting `global.imageRegistry` overrides the registry for both charts at
once; per-chart overrides remain available for asymmetric setups.

### Running against a locally-built image

For local dev (kind, k3d, minikube, vcluster) or air-gapped clusters that
do not have a pull-through cache for `registry.opsmill.io`, point the
chart at a locally-built `styrmin:<tag>` sitting in the cluster's image
store. Build the image (e.g. `docker compose build`, then `kind load
docker-image styrmin:dev` / `minikube image load styrmin:dev` / a
vcluster-equivalent) and install with an overrides file:

```yaml
# local-image-values.yaml
image:
  registry: ""
  repository: styrmin
  tag: dev          # whatever tag you built
  pullPolicy: IfNotPresent
styrmin-agent:
  image:
    registry: ""
    repository: styrmin
    tag: dev
    pullPolicy: IfNotPresent
```

```bash
helm install styrmin ./helm/styrmin -f local-image-values.yaml
```

The E2E suite uses this exact pattern — see
`backend/tests/e2e/fixtures/styrmin-values.yaml`.

### Styrmin Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `styrmin.logLevel` | Log level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `styrmin.url.internalApi` | Internal API URL (auto-generated) | `""` |
| `styrmin.url.internalApiK8s` | Internal API URL for K8s (auto-generated) | `""` |
| `styrmin.kubernetes.defaultResourcePrefix` | Resource prefix | `styrmin` |
| `styrmin.agentSource.repository` | Git repository URL | `https://github.com/opsmill/styrmin.git` |
| `styrmin.agentSource.branch` | Git branch | `develop` |
| `styrmin.agentSource.token` | Git token (use existingSecret) | `""` |
| `styrmin.driver.token` | Driver token (use existingSecret) | `""` |
| `styrmin.database.type` | Database type | `postgres` |
| `styrmin.database.name` | Database name | `styrmin` |
| `styrmin.database.host` | Database host (auto-configured) | `""` |
| `styrmin.database.port` | Database port | `5432` |
| `styrmin.database.username` | Database username | `styrmin` |
| `styrmin.database.password` | Database password | `""` |
| `styrmin.workflow.enable` | Enable Prefect | `true` |
| `styrmin.workflow.address` | Prefect address (auto-configured) | `""` |
| `styrmin.workflow.port` | Prefect port | `4200` |
| `styrmin.workflow.tlsEnabled` | Enable TLS for Prefect | `false` |

### Secrets Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.existingSecret` | Use existing secret | `""` |
| `secrets.annotations` | Secret annotations | `{}` |

### Service Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Service port | `8000` |

### Ingress Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress for styrmin-server | `false` |
| `ingress.className` | Ingress class name | `""` |
| `ingress.annotations` | Ingress annotations | `{}` |
| `ingress.hosts` | Ingress hosts | `[{host: styrmin.local, paths: [{path: /, pathType: Prefix}]}]` |
| `ingress.tls` | Ingress TLS configuration | `[]` |

### Prefect Ingress Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `prefectIngress.enabled` | Enable ingress for Prefect UI | `false` |
| `prefectIngress.className` | Ingress class name | `""` |
| `prefectIngress.annotations` | Ingress annotations | `{}` |
| `prefectIngress.hosts` | Ingress hosts | `[{host: prefect.local, paths: [{path: /, pathType: Prefix}]}]` |
| `prefectIngress.tls` | Ingress TLS configuration | `[]` |

### PostgreSQL Configuration (Bitnami subchart)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postgresql.enabled` | Enable PostgreSQL subchart | `true` |
| `postgresql.auth.postgresPassword` | Admin password | `""` |
| `postgresql.auth.username` | Styrmin username | `styrmin` |
| `postgresql.auth.password` | Styrmin password | `""` |
| `postgresql.auth.database` | Styrmin database | `styrmin` |
| `postgresql.auth.prefectPassword` | Prefect password | `""` |
| `postgresql.primary.persistence.enabled` | Enable persistence | `true` |
| `postgresql.primary.persistence.size` | PVC size | `10Gi` |

### Prefect Server Configuration (Prefect subchart)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `prefect-server.enabled` | Enable Prefect server | `true` |
| `prefect-server.postgresql.enabled` | Enable Prefect's built-in PostgreSQL | `false` |

## Using External Secrets

For production deployments, it's recommended to use external secrets:

```yaml
secrets:
  existingSecret: "my-styrmin-secrets"
```

The secret should contain these keys:

- `driver-token`: Styrmin driver authentication token
- `agent-source-token`: GitHub token for private repository access
- `db-username`: PostgreSQL username for Styrmin
- `db-password`: PostgreSQL password for Styrmin
- `prefect-db-username`: PostgreSQL username for Prefect
- `prefect-db-password`: PostgreSQL password for Prefect

## Upgrading

```bash
helm upgrade styrmin ./helm/styrmin -n styrmin -f my-values.yaml
```

## Uninstalling

```bash
helm uninstall styrmin -n styrmin
```

**Note:** PostgreSQL PVCs are not automatically deleted. To fully remove all data:

```bash
kubectl delete pvc -l app.kubernetes.io/instance=styrmin -n styrmin
```

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                       │
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │   Ingress    │     │   Ingress    │     │              │    │
│  │  (styrmin)   │     │  (prefect)   │     │              │    │
│  └──────┬───────┘     └──────┬───────┘     │              │    │
│         │                    │             │  PostgreSQL  │    │
│  ┌──────▼───────┐     ┌──────▼───────┐     │              │    │
│  │   Styrmin    │────▶│   Prefect    │────▶│  - styrmin   │    │
│  │   Server     │     │   Server     │     │  - prefect   │    │
│  └──────────────┘     └──────────────┘     │              │    │
│         ▲                    ▲             │              │    │
│         │                    │             └──────────────┘    │
│  ┌──────┴───────┐            │                                 │
│  │   Styrmin    │────────────┘                                 │
│  │   Agent      │                                              │
│  │  (Worker)    │                                              │
│  └──────────────┘                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Check pod status

```bash
kubectl get pods -n styrmin -l app.kubernetes.io/instance=styrmin
```

### Check logs

```bash
# Styrmin server logs
kubectl logs -n styrmin -l app.kubernetes.io/component=server -f

# Styrmin agent logs
kubectl logs -n styrmin -l app.kubernetes.io/component=agent -f

# Prefect server logs
kubectl logs -n styrmin -l app.kubernetes.io/name=prefect-server -f
```

### Database connectivity

```bash
# Test PostgreSQL connection
kubectl run -it --rm --image=postgres:16-alpine psql-client -n styrmin -- \
  psql -h styrmin-postgresql -U styrmin -d styrmin -c '\dt'
```

## License

Copyright © 2026 OpsMill
