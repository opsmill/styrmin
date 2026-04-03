---
title: What is an Application Driver?
sidebar_position: 1
description: Understand Application Drivers and their role in Styrmin deployments.
---

# What is an Application Driver?

An **Application Driver** is a versioned deployment specification that tells Styrmin everything it needs to know to deploy, configure, and manage an application on Kubernetes.

## The Problem Drivers Solve

Deploying applications on Kubernetes typically requires:

- Writing and maintaining Helm values for different environments
- Managing upgrade procedures with zero-downtime migrations
- Coordinating component restarts during upgrades
- Tracking which versions are compatible with each other

Application Drivers solve these problems by packaging all deployment logic into a single, versioned, reusable unit.

## What's Inside a Driver

A driver is a directory containing these files:

| File | Required | Purpose |
|------|----------|---------|
| `styrmin_driver.yaml` | Yes | Main specification — metadata, Helm chart location, components |
| `chart_values.j2.yaml` | Yes | Jinja2 template that generates Helm values dynamically |
| `actions.yaml` | No | Lifecycle action definitions (setup, upgrade hooks) |
| `actions.py` | No* | Python implementation of custom actions |

> \* Required if `actions.yaml` is present.

## How Drivers Work

When you deploy an application through Styrmin, the driver:

1. **Locates the Helm chart** — The driver specifies which Helm chart to use and its version
2. **Generates configuration** — The `chart_values.j2.yaml` template produces Helm values using context from the cluster, environment, and deployment settings
3. **Manages components** — Components define the independently manageable parts of the application (e.g., server, database, worker)
4. **Executes lifecycle actions** — Optional hooks run custom logic during setup and upgrade workflows (e.g., database migrations, component restarts)

## Key Concepts

### Declarative Specification

Drivers are declarative — you define _what_ should be deployed, and Styrmin figures out _how_. The platform compares desired state (from the driver) with current state (in the cluster) and reconciles any differences.

### Version Compatibility

Each driver declares which application versions it supports using semver ranges (e.g., `>=1.1.5,<=1.2.0`). This ensures that a driver is only used with compatible application versions.

### Dynamic Configuration

The Helm values template has access to rich context including cluster configuration, environment settings, and deployment overrides. This means the same driver can deploy an application differently across environments without duplication.

### Component Management

Components define the parts of an application that can be independently started, stopped, or scaled. During upgrades, Styrmin can stop specific components, run migrations, and restart them — all orchestrated by the driver's actions.

## Next Steps

- [Create a new driver](./creating-a-driver.md) — Step-by-step guide to building your first driver
- [Specification reference](./specification.md) — Complete reference for all driver fields
- [Example walkthrough](./example-walkthrough.md) — A complete driver explained line by line
