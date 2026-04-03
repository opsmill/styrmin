---
title: Platform Overview
sidebar_position: 1
description: Learn what Styrmin is, the problems it solves, and its core concepts.
---

# Platform Overview

**Styrmin** is a deployment orchestration platform that manages application deployments on Kubernetes clusters. It provides a declarative approach to deploying applications through **Application Drivers** — versioned deployment specifications that define how applications should be deployed, configured, and managed.

## The Problem

Deploying and managing applications across Kubernetes clusters involves significant operational complexity:

- **Configuration drift** — Helm values differ between environments and clusters, leading to inconsistencies
- **Manual upgrade procedures** — Upgrades require coordinating component restarts, database migrations, and rollback plans
- **No single source of truth** — Deployment state is scattered across Helm releases, CI/CD pipelines, and operator knowledge
- **Version compatibility** — Tracking which application versions are compatible with which Helm chart versions is error-prone

## How Styrmin Solves This

Styrmin introduces a **declarative, driver-based model** for deployment management:

1. **Application Drivers** package all deployment logic — Helm charts, configuration templates, and lifecycle actions — into versioned, reusable units
2. **State reconciliation** automatically computes the difference between desired state and current state, then generates the operations needed to converge
3. **Multi-cluster management** lets you manage deployments across many clusters and environments from a single platform

## Core Concepts

### Clusters

A **Cluster** represents a Kubernetes cluster managed by Styrmin. Each cluster has its own configuration (storage class, ingress class, node selectors) that drivers use to generate environment-appropriate Helm values.

### Environments

An **Environment** is a logical grouping within a cluster (e.g., "production", "staging", "development"). Environments carry their own configuration that overlays the cluster configuration, allowing the same application to be deployed differently across environments.

### Services

A **Service** represents a deployed application instance within an environment. Services are created by associating an Application Driver with a specific application version in a target environment.

### Application Drivers

An **Application Driver** is a versioned package that defines how to deploy, configure, and manage an application. Drivers contain:

- **Helm chart reference** — Which chart to install and its version
- **Values template** — A Jinja2 template that generates Helm values from cluster, environment, and deployment context
- **Components** — The independently manageable parts of the application (server, database, worker, etc.)
- **Actions** — Custom lifecycle logic for setup and upgrade workflows

### Deployments

A **Deployment** is the intent to run a specific version of an application in an environment. Styrmin compares each deployment's desired state against the actual state (the **Instance**) and performs reconciliation to converge them.

## Architecture at a Glance

```
                    ┌──────────────┐
                    │   Styrmin    │
                    │   Platform   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼───┐ ┌─────▼─────┐
        │ Cluster A  │ │  ...  │ │ Cluster N  │
        └─────┬──────┘ └───────┘ └─────┬──────┘
              │                        │
     ┌────────┼────────┐       ┌───────┼───────┐
     │        │        │       │       │       │
   ┌─▼──┐  ┌─▼──┐  ┌──▼┐   ┌─▼──┐  ┌─▼──┐  ┌▼───┐
   │prod│  │stg │  │dev│   │prod│  │stg │  │dev │
   └─┬──┘  └─┬──┘  └──┬┘   └─┬──┘  └─┬──┘  └┬───┘
     │       │        │      │       │       │
   [apps]  [apps]   [apps] [apps]  [apps]  [apps]
```

Each application in each environment is managed by an Application Driver that knows how to deploy, configure, and upgrade it.

## Who is Styrmin For?

- **Platform engineers** who manage Kubernetes infrastructure and need a consistent way to deploy applications across clusters
- **DevOps teams** who want to reduce the manual effort of managing Helm releases, upgrades, and rollbacks
- **Application teams** who want self-service deployment capabilities with guardrails and best practices built in

## Next Steps

- [Quickstart](./quickstart.md) — Get Styrmin running in minutes
- [Installation guides](../category/installation) — Deploy on your Kubernetes platform
- [What is an Application Driver?](../drivers/what-is-a-driver.md) — Deep dive into the core concept
