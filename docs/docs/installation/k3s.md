---
title: k3s
sidebar_position: 5
description: Install Styrmin on k3s, a lightweight Kubernetes distribution.
---

# Install Styrmin on k3s

k3s is the fastest way to get a Kubernetes cluster running. This guide walks you through installing k3s on a single Linux node and deploying Styrmin on top of it.

## Prerequisites

- A Linux host (x86_64 or arm64) with at least **4 CPU cores** and **8 GB of RAM**
- Root or `sudo` access
- `curl` installed
- Outbound internet access (to pull images and charts)

Ensure `helm` is installed on the host. See the [Prerequisites](./prerequisites.md) page for installation instructions.

## Install k3s

Install k3s as a single-node cluster. The command below disables the built-in Traefik ingress controller so we can install NGINX Ingress instead:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik" sh -
```

Wait a few seconds for k3s to start, then verify the node is ready:

```bash
sudo k3s kubectl get nodes
```

You should see your node with status `Ready`.

## Configure kubectl

k3s writes its kubeconfig to `/etc/rancher/k3s/k3s.yaml`. Export it so `kubectl` and `helm` can find it:

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
export KUBECONFIG=~/.kube/config
```

:::tip
Add the `export KUBECONFIG=~/.kube/config` line to your shell profile (`~/.bashrc` or `~/.zshrc`) so it persists across sessions.
:::

Verify the cluster is reachable:

```bash
kubectl cluster-info
kubectl get nodes
```

## Install an Ingress Controller

Since we disabled Traefik, install the NGINX Ingress Controller via Helm:

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer
```

Wait for the controller pod to become ready:

```bash
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

## Install Styrmin

Create a dedicated namespace and install the Styrmin Helm chart:

```bash
kubectl create namespace styrmin
```

Create a values file to configure the installation:

```bash
cat <<'EOF' > styrmin-values.yaml
global:
  host: styrmin.local

ingress:
  enabled: true
  className: nginx
EOF
```

Install the chart:

```bash
helm install styrmin oci://registry.opsmill.io/opsmill/chart/styrmin \
  --namespace styrmin \
  --values styrmin-values.yaml \
  --wait
```

:::info
Replace `styrmin.local` with your actual hostname or IP address. For local testing you can add an entry to `/etc/hosts` pointing `styrmin.local` to your node's IP.
:::

## Verify Installation

Check that all pods are running:

```bash
kubectl get pods -n styrmin
```

All pods should show `Running` status with all containers ready.

Check the services:

```bash
kubectl get svc -n styrmin
```

Verify the ingress resource was created:

```bash
kubectl get ingress -n styrmin
```

Once everything is healthy, open the Styrmin UI in your browser at `http://styrmin.local` (or whatever hostname you configured).

## Next Steps

- Learn about [Application Drivers](../drivers/what-is-a-driver.md) to deploy your first application
- Read the [Platform Overview](../getting-started/overview.md) for a deeper understanding of Styrmin's concepts
- Review the [Prerequisites](./prerequisites.md) page for ongoing cluster requirements
