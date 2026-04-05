# Quickstart: Kubernetes Operator for Deployment Reconciliation

**Branch**: `001-k8s-operator` | **Date**: 2026-04-05

## Prerequisites

- Python 3.14 with uv
- Access to a Kubernetes cluster (Kind for local dev, or staging cluster)
- FluxCD installed in the cluster (for HelmRelease CRD)
- Styrmin backend running and accessible
- Prefect server running

## Install Dependencies

```bash
# From repo root
uv add kopf
uv sync --all-groups --all-packages
```

## Deploy Kopf Peering CRD

The operator uses kopf's peering mechanism for leader election. Deploy the CRD:

```bash
kubectl apply -f - <<EOF
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: clusterkopfpeerings.kopf.dev
spec:
  group: kopf.dev
  names:
    kind: ClusterKopfPeering
    plural: clusterkopfpeerings
    singular: clusterkopfpeering
  scope: Cluster
  versions:
    - name: v1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            status:
              type: object
              x-kubernetes-preserve-unknown-fields: true
EOF
```

Create the peering object:

```bash
kubectl apply -f - <<EOF
apiVersion: kopf.dev/v1
kind: ClusterKopfPeering
metadata:
  name: styrmin-operator
EOF
```

## Run Locally (Development)

```bash
# Ensure KUBECONFIG is set and Styrmin backend is reachable
export STYRMIN_URL_API="http://localhost:8000"
export PREFECT_API_URL="http://localhost:4200/api"

# Run the combined operator + Prefect worker
uv run python -m styrmin_backend.entrypoint.combined \
  --work-pool styrmin-work-pool \
  --clusterwide
```

## Run in Docker Compose

The `docker-compose.yml` entry for the combined agent/operator replaces the separate `task-worker` and `k8s-agent` services:

```yaml
agent-operator:
  image: styrmin:latest
  command:
    - python
    - -m
    - styrmin_backend.entrypoint.combined
    - --work-pool
    - styrmin-work-pool
    - --clusterwide
  environment:
    - STYRMIN_URL_API=http://server:8000
    - PREFECT_API_URL=http://task-manager:4200/api
  network_mode: host
  volumes:
    - ~/.kube:/home/styrmin/.kube:ro
```

## Run in Kubernetes

The Helm chart deploys the combined process as a single Deployment (replaces the separate task-worker deployment):

```yaml
# helm/styrmin/templates/styrmin-server/agent-operator-deployment.yaml
spec:
  replicas: 2  # Multiple replicas OK - kopf peering handles leader election
  terminationGracePeriodSeconds: 60
  template:
    spec:
      serviceAccountName: styrmin-service-account
      containers:
        - name: agent-operator
          command:
            - python
            - -m
            - styrmin_backend.entrypoint.combined
            - --work-pool
            - styrmin-work-pool
            - --clusterwide
          env:
            - name: STYRMIN_URL_API
              value: "http://styrmin-server:8000"
```

## Verify It Works

1. **Check operator is running**:
   ```bash
   # Logs should show both kopf and Prefect startup
   kubectl logs -l app.kubernetes.io/component=agent-operator -f
   ```

2. **Create a new deployment** via the Styrmin UI or API. The operator should:
   - Detect the new HelmRelease
   - Create NetworkPolicies
   - Emit `ReconcileSucceeded` event

3. **Verify NetworkPolicies created**:
   ```bash
   kubectl get networkpolicies -n <deployment-namespace> \
     -l styrmin.io/operator-managed=true
   ```

4. **Test drift correction** - delete a NetworkPolicy and watch it get recreated:
   ```bash
   kubectl delete networkpolicy <ref>-default-deny-egress -n <namespace>
   # Wait up to 60 seconds
   kubectl get networkpolicies -n <namespace>
   ```

5. **Check events**:
   ```bash
   kubectl describe helmrelease <name> -n <namespace>
   # Look for ReconcileSucceeded, DriftDetected events
   ```

## Running Tests

```bash
# Unit tests for operator handlers and reconciler
uv run pytest tests/unit/operator/ -v

# Integration tests (requires running cluster)
uv run pytest tests/integration/operator/ -v

# All tests
uv run invoke test
```

## Troubleshooting

- **Operator not detecting HelmReleases**: Check RBAC permissions. The service account needs `get`, `list`, `watch` on `helmreleases.helm.toolkit.fluxcd.io`.
- **NetworkPolicies not created**: Check that the HelmRelease has label `styrmin.io/operator-managed: "true"`. Pre-existing deployments are not adopted.
- **Operator and Prefect conflicting**: Check for `styrmin.io/deployment-in-progress: "true"` annotation on the HelmRelease. The operator defers when this is present.
- **Leader election not working**: Verify the `ClusterKopfPeering` CRD and `styrmin-operator` peering object exist.
