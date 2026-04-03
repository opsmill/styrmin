---
title: kubeadm
sidebar_position: 6
description: Install Styrmin on a cluster provisioned with kubeadm.
---

# Install Styrmin on kubeadm

This guide covers what you need to install Styrmin on an existing cluster bootstrapped with kubeadm. It assumes you already have a working multi-node (or single-node) kubeadm cluster.

## Prerequisites

- A running kubeadm cluster (v1.28+) with at least one control-plane and one worker node
- A **CNI plugin** installed and operational (Calico, Flannel, Cilium, etc.)
- A **storage provisioner** that provides at least one StorageClass (or follow the section below to install one)
- `kubectl` configured with cluster-admin access
- `helm` v3.12+ installed locally

See the [Prerequisites](./prerequisites.md) page for tool installation instructions and minimum resource requirements.

## Verify Cluster Readiness

Before proceeding, confirm the cluster components are healthy.

### Nodes

```bash
kubectl get nodes
```

All nodes should show `Ready` status. If any node is `NotReady`, check that the kubelet is running and that your CNI plugin is installed.

### CNI Plugin

Verify that CoreDNS pods are running. A functional CNI is required for pod networking and DNS:

```bash
kubectl get pods -n kube-system -l k8s-app=kube-dns
```

Both pods should show `Running` with all containers ready. If they are stuck in `Pending` or `CrashLoopBackOff`, your CNI plugin is not installed or misconfigured.

### Storage Class

Check that at least one StorageClass is available:

```bash
kubectl get storageclass
```

If no StorageClass is listed, see [Install a Storage Provisioner](#install-a-storage-provisioner-if-needed) below.

## Install an Ingress Controller

kubeadm does not ship with an ingress controller. Install the NGINX Ingress Controller via Helm:

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=NodePort
```

:::tip
On bare-metal or on-premises clusters, `NodePort` is typically more practical than `LoadBalancer` since there is no cloud load-balancer integration. If you have MetalLB or another bare-metal LB solution, you can use `--set controller.service.type=LoadBalancer` instead.
:::

Wait for the controller pod to become ready:

```bash
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

Note the NodePort assigned to the ingress controller for later use:

```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller
```

## Install a Storage Provisioner (if needed)

If your cluster has no StorageClass, install the [local-path-provisioner](https://github.com/rancher/local-path-provisioner) as a lightweight option:

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.30/deploy/local-path-storage.yaml
```

Verify the StorageClass was created and mark it as default:

```bash
kubectl get storageclass

kubectl patch storageclass local-path \
  -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
```

:::note
`local-path-provisioner` stores data on the node's local filesystem. This is suitable for development and testing. For production, consider a distributed storage solution such as Longhorn, Rook-Ceph, or OpenEBS.
:::

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
Replace `styrmin.local` with your actual hostname or IP address. For local testing you can add an entry to `/etc/hosts` pointing `styrmin.local` to your control-plane node's IP.
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

Once everything is healthy, open the Styrmin UI in your browser. If you are using NodePort, access it at `http://<node-ip>:<node-port>`. If you configured a hostname, navigate to `http://styrmin.local`.

## Next Steps

- Learn about [Application Drivers](../drivers/what-is-a-driver.md) to deploy your first application
- Read the [Platform Overview](../getting-started/overview.md) for a deeper understanding of Styrmin's concepts
- Review the [Prerequisites](./prerequisites.md) page for ongoing cluster requirements
