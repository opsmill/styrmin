---
title: Prerequisites
sidebar_position: 1
description: Common prerequisites for installing Styrmin on any Kubernetes platform.
---

# Prerequisites

Before installing Styrmin, ensure your environment meets the following requirements.

## Required Tools

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| `kubectl` | v1.28+ | Kubernetes cluster management |
| `helm` | v3.12+ | Helm chart installation |
| Kubernetes cluster | v1.28+ | Target deployment platform |

### kubectl

Install `kubectl` following the [official Kubernetes documentation](https://kubernetes.io/docs/tasks/tools/).

Verify your installation:

```bash
kubectl version --client
```

### Helm

Install Helm v3 following the [official Helm documentation](https://helm.sh/docs/intro/install/).

Verify your installation:

```bash
helm version
```

## Cluster Requirements

### Minimum Resources

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 4 cores | 8 cores |
| Memory | 8 GB | 16 GB |
| Storage | 20 GB | 50 GB |

### Required Cluster Features

- **Ingress controller** — An ingress controller must be installed and configured (e.g., NGINX Ingress, Traefik, AWS ALB Controller)
- **Storage class** — At least one storage class must be available for persistent volumes
- **DNS resolution** — CoreDNS or equivalent must be running for in-cluster service discovery

### Network Access

The cluster must have outbound internet access to:

- Pull container images from container registries
- Download Helm charts from chart repositories
- Clone driver repositories from Git

## Cluster Access

You must have cluster-admin access or equivalent permissions to:

- Create namespaces
- Install Custom Resource Definitions (CRDs)
- Create ClusterRoles and ClusterRoleBindings
- Deploy workloads across namespaces

Verify your cluster access:

```bash
kubectl auth can-i create namespaces --all-namespaces
# Expected output: yes
```

## Next Steps

Once your prerequisites are met, follow the installation guide for your Kubernetes platform:

- [Google GKE](./gke.md)
- [k3s](./k3s.md)
- [kubeadm](./kubeadm.md)
