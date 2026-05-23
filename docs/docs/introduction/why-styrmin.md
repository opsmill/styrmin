---
title: Why Styrmin?
sidebar_position: 1
description: What Styrmin does, who it's for, and how it differs from Helm, ArgoCD, and Flux.
---

## Why Styrmin?

Styrmin is an **application platform that manages the full lifecycle of your
infrastructure automation stack** — Infrahub, Ansible, Grafana, Prometheus,
and the tooling around them — **as a single system**, not application by
application.

These tools don't actually run in isolation: they need to be deployed
together, backed up together, upgraded together, and tested together. Doing
that by hand means a Helm chart per application, a backup script per
application, a brittle upgrade runbook per application, and no realistic
way to rehearse a change before it hits production.

Styrmin gives you one system for all of it.

### The capabilities that nothing else provides

These three operations are what set Styrmin apart from every other tool in
the space. They're either impossible or extremely painful today — Styrmin
is designed to make them routine.

1. **Clone an entire environment.** Duplicate production — applications,
   configuration, and live data — to a test environment so upgrades and
   changes can be validated against real data before touching production.
   Cross-application connectivity is environment-aware: cloned environments
   talk to each other, not back to production.
2. **Back up the whole stack in a single operation.** Trigger backups
   across every application in an environment with one action. Each
   application's driver knows how to back it up correctly — Neo4j and
   Postgres need different procedures and the driver handles that.
3. **Upgrade reliably.** Run upgrades through driver-defined sequences
   that stop components in the right order, run migrations, restart, and
   verify. Complex upgrade processes are encoded **once** in the driver
   and run the same way every time, not improvised in production at 2am.

The unit that makes this work is the **driver**: a versioned, per-application
specification that captures everything Styrmin needs to deploy, configure,
back up, and upgrade that application correctly. See
[What is an Application Driver?](../drivers/what-is-a-driver.md).

### Who Styrmin is for

#### Primary persona: the engineer running their own stack

The person Styrmin is designed for first is **the infrastructure or network
engineer running their own application stack** — not a dedicated platform
team, not a Kubernetes expert, but responsible for keeping Infrahub,
Ansible, and surrounding tooling running in production. This is the person
who:

- Googles Helm values every time they touch a chart.
- Has upgraded in production without a tested rollback path.
- Doesn't have a staging environment because creating one is too hard.

Styrmin removes the parts of that job that require Kubernetes specialism
and replaces ad-hoc operational glue with driver-defined procedures.

#### Where Styrmin fits

Styrmin is initially aimed at **Infrahub operators without a large
platform team** — mid-size operators who need production-grade
infrastructure management but can't afford the operational overhead it
demands today.

From there it extends to anyone who wants to manage a group of
applications as one stack:

- **Platform teams** managing multiple application stacks across
  environments.
- **Managed Service Providers** building customer portals on top of a
  consistent stack.
- **Implementation and consulting partners** building a repeatable
  delivery practice — owning an internal library of drivers for the
  applications they deploy for clients, instead of rebuilding the
  deployment from scratch on every engagement.
- **Any operator currently stitching together multiple Helm charts
  manually.**

The longer-term goal is for teams running on Docker Compose to get the
benefits of a managed Kubernetes platform without having to learn
Kubernetes — Styrmin will eventually bundle a Kubernetes distribution so
users don't even need to install it themselves.

### How teams do this today, and why it hurts

#### Manual Helm chart deployment

The standard approach is to deploy each application individually using
its own Helm chart. The pain:

- Every chart uses a different configuration schema; teams have to learn
  each one.
- Cluster-specific details (storage classes, ingress class) must be known
  and set correctly for every application.
- There's no standardised way to know which Helm chart version maps to
  which application version.
- Each application is managed independently; there is no abstraction
  across them.

#### Manual backup and restore

Teams build their own backup scripts or use per-application tools. The
pain:

- Backup procedures differ per application (Neo4j ≠ Postgres) and have
  to be maintained per application.
- There's no unified backup across the stack — each application is
  backed up separately.
- Restoring is manual, error-prone, and rarely tested.
- Recreating a production environment for testing is extremely hard.

#### Manual upgrades

Teams run `helm upgrade` directly, often without process. The pain:

- Upgrading in production without a tested rollback path — what the
  field calls "YOLO upgrades".
- Multi-step upgrade processes (stop workers, migrate DB, restart) have
  to be executed manually in the right order.
- There is no safe way to test an upgrade against production data first.
- Breaking changes in a Helm chart require manual intervention with no
  structured guidance.

### How Styrmin compares to ArgoCD and Flux

ArgoCD and Flux are the tools most people reach for when they first see
Styrmin. The difference is **not feature-by-feature, it's conceptual**:

> **ArgoCD manages individual applications. Styrmin manages a group of
> applications as a single system with a shared lifecycle.**

A team using ArgoCD to manage Infrahub, Ansible, Grafana, and Prometheus
still has to build all the operational glue themselves — backup
procedures, upgrade sequences, environment cloning. Styrmin **is** that
glue.

The specifics:

| | ArgoCD / Flux | Styrmin |
|--|---------------|---------|
| **Scope of management** | Individual applications | A group of applications as one stack |
| **Driver / app-specific knowledge** | None — chart-agnostic | Encoded per app in a driver |
| **Backup / upgrade / restore actions** | Not provided | First-class user actions |
| **Environment cloning with data** | Not provided | Built-in |
| **Opinions on how apps should be operated** | Unopinionated by design | Opinionated; drivers encode best practice |
| **Best at** | GitOps delivery of K8s manifests | Lifecycle management of the application stack |

**These tools are complementary, not competing.** Use ArgoCD or Flux for
GitOps delivery of infrastructure changes; use Styrmin for the
application lifecycle on top of it.

### How Styrmin compares to Internal Developer Platforms

Internal Developer Platforms (Backstage-style portals, commercial IDPs)
exist but solve a different problem: helping **developers deploy their
own apps**. They aren't designed for:

- Managing a group of applications as one operational entity.
- Encoding application-specific operational knowledge (backups, upgrade
  sequences).
- Providing a production-grade management layer for infrastructure
  tooling specifically.

### What about Kubernetes itself?

Styrmin **runs on top of Kubernetes** — that's an implementation detail,
not the product. The goal is for teams to get the benefits of a managed
infrastructure experience without needing to think about Kubernetes at
all. In a future version, Styrmin will bundle a Kubernetes distribution
so users don't even know it's there.

You won't replace `kubectl`, Helm, or Argo by adopting Styrmin — Styrmin
uses Helm under the hood and you can keep your existing tooling. What
Styrmin replaces is the **manual operational glue** between your
applications.

### What Styrmin is and isn't

| Question | Answer |
|----------|--------|
| Is Styrmin a replacement for Kubernetes? | No. It runs on Kubernetes and uses it as the underlying infrastructure. |
| Is it a replacement for Helm? | No. Drivers use Helm under the hood; Styrmin abstracts the chart-configuration complexity. |
| Will my existing tools (Jenkins, monitoring, direct API access) keep working? | Yes. Styrmin manages deployment and lifecycle; it does not intercept or proxy application traffic. |
| Can I use it for applications other than Infrahub? | Yes. Anything with a driver. The driver system is the extensibility mechanism, and Styrmin itself is application-agnostic. |
| Can it manage applications not running on Kubernetes (VMs, SaaS)? | The first version is Kubernetes-only. SaaS (e.g. Kentik) and multi-cluster are on the roadmap; VM support comes later. |
| Is there a commercial offering? | Not in the short term. Styrmin is an independent open-source project so other vendors and application teams can build drivers and adopt it broadly. |

### Next steps

- [**Platform Overview**](./platform-overview.md) — the conceptual model behind
  driver, cluster, environment, deployment.
- [**Quickstart**](../installation/quickstart.md) — try the bundled demo end-to-end.
- [**What is an Application Driver?**](../drivers/what-is-a-driver.md) —
  understand the unit that makes the rest of Styrmin work.
