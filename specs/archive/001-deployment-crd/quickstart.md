# Quickstart: StyrminDeployment CRD

**Branch**: `001-deployment-crd` | **Date**: 2026-04-05

## Prerequisites

- Styrmin operator running (from 001-k8s-operator: `styrmin agent start`)
- FluxCD installed in the cluster
- Styrmin backend running and accessible

## Deploy the CRD

```bash
kubectl apply -f helm/styrmin/templates/operator/styrmin-deployment-crd.yaml
```

## Create a Deployment (via API)

The standard Styrmin API workflow triggers the Prefect flow, which now creates a StyrminDeployment CRD:

```bash
# Via styrminctl (unchanged user experience)
styrminctl deployments create --environment prod --driver infrahub --version 1.7.2
```

## Verify Deployment Progress

```bash
# Watch the StyrminDeployment status
kubectl get styrmindeployments -A
# Output:
# NAMESPACE       NAME            PHASE                    APP        VERSION   AGE
# deploy-abc123   infrahub-prod   CreatingPrerequisites    infrahub   1.7.2     5s

# Wait for Ready
kubectl get styrmindeployments -A -w

# Detailed status
kubectl describe styrmindeployment infrahub-prod -n deploy-abc123
```

## Verify Resource Ordering

```bash
# Check NetworkPolicies were created first
kubectl get networkpolicies -n deploy-abc123 -l styrmin.io/resource-phase=prerequisites

# Check HelmRelease was created after NetworkPolicies
kubectl get helmrelease -n deploy-abc123

# Check Services were created after HelmRelease
kubectl get services -n deploy-abc123 -l styrmin.io/resource-phase=services
```

## Test Drift Correction

```bash
# Delete a NetworkPolicy
kubectl delete networkpolicy abc123def-default-deny-egress -n deploy-abc123

# Wait up to 60 seconds, verify it's recreated
kubectl get networkpolicies -n deploy-abc123

# Modify a Service
kubectl patch service my-svc -n deploy-abc123 -p '{"spec":{"ports":[{"port":9999}]}}'

# Verify it's corrected
kubectl get service my-svc -n deploy-abc123 -o jsonpath='{.spec.ports}'
```

## Delete a Deployment

```bash
# Via styrminctl
styrminctl deployments delete --name infrahub-prod

# Or directly delete the CRD
kubectl delete styrmindeployment infrahub-prod -n deploy-abc123

# Verify reverse-order cleanup:
# 1. Services/Middlewares deleted first
# 2. HelmRelease deleted and terminated
# 3. NetworkPolicies/Secrets deleted last
```

## Running Tests

```bash
uv run pytest tests/unit/operator/ -v
uv run invoke test
```
