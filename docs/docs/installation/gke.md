---
title: Google GKE
sidebar_position: 3
description: Install Styrmin on Google Kubernetes Engine (GKE).
---

# Google GKE

This guide walks through installing Styrmin on a Google Kubernetes Engine (GKE) cluster.

Before you begin, ensure you have completed the [common prerequisites](./prerequisites.md).

## GKE-Specific Prerequisites

### Google Cloud CLI

Install the `gcloud` CLI following the [official documentation](https://cloud.google.com/sdk/docs/install).

Verify your installation and authenticate:

```bash
gcloud version
gcloud auth login
```

### GCP Project

You need a GCP project with billing enabled. Set your project:

```bash
gcloud config set project YOUR_PROJECT_ID
```

### Required APIs

Enable the necessary Google Cloud APIs:

```bash
gcloud services enable container.googleapis.com
gcloud services enable compute.googleapis.com
```

## Create a GKE Cluster

If you do not already have a GKE cluster, create one:

```bash
gcloud container clusters create styrmin-cluster \
  --zone us-central1-a \
  --num-nodes 3 \
  --machine-type e2-standard-4 \
  --disk-size 50 \
  --enable-ip-alias
```

This creates a 3-node cluster with 4 vCPUs and 16 GB of memory per node, which meets the recommended resource requirements.

Wait for the cluster to reach a `RUNNING` state:

```bash
gcloud container clusters describe styrmin-cluster \
  --zone us-central1-a \
  --format="value(status)"
```

## Configure kubectl

Fetch credentials for your GKE cluster so `kubectl` can connect to it:

```bash
gcloud container clusters get-credentials styrmin-cluster \
  --zone us-central1-a
```

Verify connectivity:

```bash
kubectl get nodes
```

You should see your three nodes in `Ready` status.

## Install an Ingress Controller

GKE provides a built-in ingress controller through the GCE Ingress. However, for consistency with Styrmin's defaults, NGINX Ingress is recommended.

### Option A: NGINX Ingress via Helm (Recommended)

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace
```

Wait for the controller to be ready and obtain its external IP:

```bash
kubectl get svc ingress-nginx-controller \
  --namespace ingress-nginx \
  --watch
```

Note the `EXTERNAL-IP` value -- you will need it to configure DNS or access Styrmin.

### Option B: GKE Built-in GCE Ingress

If you prefer the native GCE Ingress, no additional installation is needed. GKE automatically provisions a Google Cloud Load Balancer when you create an `Ingress` resource with the `kubernetes.io/ingress.class: gce` annotation. Adjust your Styrmin Helm values accordingly if you choose this option.

## Install Styrmin

### Create the Namespace

```bash
kubectl create namespace styrmin
```

### Prepare Helm Values

Create a `values.yaml` file with your configuration:

```yaml
global:
  host: styrmin.example.com

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
```

Replace `styrmin.example.com` with your actual domain. If you are not using TLS, remove the `tls` and `cert-manager` sections.

### Install the Chart

```bash
helm install styrmin oci://registry.opsmill.io/opsmill/chart/styrmin \
  --namespace styrmin \
  --values values.yaml \
  --wait
```

The `--wait` flag ensures the command blocks until all resources are ready.

## Verify Installation

### Check Pod Status

All pods should be in `Running` status:

```bash
kubectl get pods --namespace styrmin
```

Expected output (pod names will vary):

```
NAME                                READY   STATUS    RESTARTS   AGE
styrmin-backend-5d4f7b8c9-xk2lp    1/1     Running   0          2m
styrmin-frontend-7f6a9d3e1-mv8qr   1/1     Running   0          2m
styrmin-postgresql-0                1/1     Running   0          2m
```

### Check Services

```bash
kubectl get svc --namespace styrmin
```

### Check Ingress

Verify the ingress resource has been created and assigned an address:

```bash
kubectl get ingress --namespace styrmin
```

### Access the UI

If you configured a domain, point your DNS record to the ingress external IP and open your browser to:

```
https://styrmin.example.com
```

For quick local testing without DNS, use port-forwarding:

```bash
kubectl port-forward svc/styrmin-frontend 8080:80 --namespace styrmin
```

Then open [http://localhost:8080](http://localhost:8080) in your browser.

## Troubleshooting

### Pods Not Starting

Check pod events for errors:

```bash
kubectl describe pod -l app.kubernetes.io/instance=styrmin --namespace styrmin
```

### Ingress Not Getting an External IP

Verify the ingress controller is running:

```bash
kubectl get pods --namespace ingress-nginx
```

If using GCE Ingress, check that the backend services are healthy in the Google Cloud Console under **Network services > Load balancing**.

### Insufficient Permissions

If you encounter RBAC errors, ensure your GCP user has the `container.admin` role:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:your-email@example.com" \
  --role="roles/container.admin"
```

## Next Steps

- Learn about [Application Drivers](../drivers/what-is-a-driver.md) to deploy your first application
- Read the [Platform Overview](../getting-started/overview.md) for a deeper understanding of Styrmin's concepts
- Review the [Prerequisites](./prerequisites.md) page for ongoing cluster requirements
