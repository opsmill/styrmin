---
title: Quickstart
sidebar_position: 2
description: Get Styrmin up and running in minutes using k3s.
---

# Quickstart

This guide gets you from zero to a running Styrmin instance as quickly as possible using [k3s](https://k3s.io/), a lightweight Kubernetes distribution.

For production deployments, see the platform-specific [Installation guides](../category/installation).

## Prerequisites

- A Linux machine (bare metal or VM) with at least 4 CPU cores and 8 GB RAM
- `curl` installed
- Root or sudo access

## 1. Install k3s

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -
```

This installs k3s with Traefik disabled (we'll use NGINX Ingress instead).

Configure kubectl:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
```

Verify the cluster is ready:

```bash
kubectl get nodes
# NAME       STATUS   ROLES                  AGE   VERSION
# my-host    Ready    control-plane,master   30s   v1.30.x+k3s1
```

## 2. Install Helm

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## 3. Install NGINX Ingress Controller

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace
```

Wait for the ingress controller to be ready:

```bash
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

## 4. Install Styrmin

Create a namespace and install Styrmin:

```bash
kubectl create namespace styrmin

helm install styrmin oci://registry.opsmill.io/opsmill/chart/styrmin \
  --namespace styrmin \
  --set ingress.className=nginx \
  --set ingress.host=styrmin.local
```

## 5. Verify Installation

Check that all pods are running:

```bash
kubectl get pods -n styrmin
```

All pods should show `Running` status with `READY` containers:

```
NAME                              READY   STATUS    RESTARTS   AGE
styrmin-server-xxxxxxxxx-xxxxx    1/1     Running   0          60s
styrmin-worker-xxxxxxxxx-xxxxx    1/1     Running   0          60s
styrmin-postgresql-0              1/1     Running   0          60s
```

Check the services:

```bash
kubectl get svc -n styrmin
```

Access the Styrmin UI by adding an entry to your hosts file:

```bash
echo "127.0.0.1 styrmin.local" | sudo tee -a /etc/hosts
```

Then open `http://styrmin.local` in your browser.

## Next Steps

- Learn about [Application Drivers](../drivers/what-is-a-driver.md) to deploy your first application
- Read the [Platform Overview](./overview.md) for a deeper understanding of Styrmin's architecture
- Explore the platform-specific [Installation guides](../category/installation) for production setups
