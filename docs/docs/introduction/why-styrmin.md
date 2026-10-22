---
title: Why Styrmin?
sidebar_position: 1
description: What Styrmin does, who it is for, and how it differs from Helm, Argo CD, and Flux.
---

## Why Styrmin?

Styrmin deploys, configures, backs up, and upgrades your infrastructure
automation stack on Kubernetes: Infrahub, Ansible, Grafana, Prometheus,
and the tools around them. You manage these applications as one stack,
with one lifecycle.

These applications depend on each other: you deploy, back up, upgrade,
and test them together. Without Styrmin, you need a Helm chart, a backup
script, and an upgrade runbook for each application, and you have no way
to test a change before you apply it to production.

Use Styrmin to run these operations for the whole stack.

### Environment cloning, stack backups, and driver-defined upgrades

Styrmin runs these three operations across every application in an
environment:

1. **Clone an environment.** Copy production (the applications, their
   configuration, and their data) to a test environment, and test an
   upgrade or a change on real data before you apply it to production.
   Applications in a cloned environment connect to each other, not to
   the production applications.
2. **Back up the whole stack in one operation.** Start a backup of every
   application in an environment with one action. Each application's
   driver defines its backup procedure, because Neo4j and PostgreSQL need
   different procedures.
3. **Upgrade with driver-defined steps.** The driver lists the upgrade
   steps in order: stop components, run migrations, restart, verify. You
   write a multi-step upgrade once in the driver, and Styrmin runs the
   same steps on every upgrade.

Each application has a **driver**: a versioned specification of how
Styrmin deploys, configures, backs up, and upgrades that application. See
[What is an application driver?](../concepts-and-architecture/what-is-a-driver.md).

### Who Styrmin is for

Styrmin is for you if you are an infrastructure or network engineer who
runs Infrahub, Ansible, and related tools in production, without a
dedicated platform team and without Kubernetes expertise. For example:

- You look up Helm values each time you change a chart.
- You have upgraded in production without a tested rollback.
- You have no staging environment, because it is hard to create one.

Drivers contain the Kubernetes and Helm settings and the backup and
upgrade procedures, so you do not write them for each application.

Styrmin is first aimed at mid-size Infrahub operators who run Infrahub
in production without a large platform team.

Styrmin is also for:

- **Platform teams** that run several application stacks across
  environments.
- **Managed service providers** that build customer portals on one
  stack.
- **Implementation and consulting partners** that keep a library of
  drivers for the applications they deploy for their clients, so they
  do not build each deployment again for each client.
- **Anyone who deploys several Helm charts manually.**

A later version of Styrmin will include a Kubernetes distribution. Teams
that run their applications with Docker Compose will then be able to use
Styrmin without installing or learning Kubernetes.

### Problems with managing each application separately

#### Manual Helm chart deployment

You deploy each application with its own Helm chart. Problems:

- Each chart has its own configuration schema, and you learn each one.
- You must know the cluster-specific settings (storage classes, ingress
  class) and set them for every application.
- No standard maps a Helm chart version to an application version.
- You manage each application separately; nothing applies to all of
  them.

#### Manual backup and restore

You write a backup script for each application, or use a tool for each
application. Problems:

- Backup procedures differ for each application (Neo4j and PostgreSQL
  are different), and you maintain each one.
- No backup covers the whole stack: you back up each application
  separately.
- Restoring is manual, error-prone, and rarely tested.
- Creating a copy of production for testing is very hard.

#### Manual upgrades

You run `helm upgrade` directly, with no defined sequence. Problems:

- You upgrade production without a tested rollback.
- You run multi-step upgrades (stop workers, migrate the database,
  restart) manually, in order.
- You cannot test an upgrade on production data first.
- A breaking change in a Helm chart needs manual steps, with no
  guidance.

### How Styrmin compares to Argo CD and Flux

Argo CD and Flux also deploy applications to Kubernetes. They manage
each application separately. Styrmin manages a group of applications
with one lifecycle.

If you manage Infrahub, Ansible, Grafana, and Prometheus with Argo CD,
you still write the backup procedures, the upgrade sequences, and the
environment cloning yourself. Styrmin runs them from each application's
driver.

| | Argo CD / Flux | Styrmin |
|--|---------------|---------|
| **Scope** | One application at a time | A group of applications as one stack |
| **Application-specific knowledge** | None (chart-agnostic) | Defined in each application's driver |
| **Backup, upgrade, and restore** | Not provided | Run from the UI, the CLI, and the API |
| **Environment cloning with data** | Not provided | Included |
| **How each application is operated** | Not defined | Defined in each application's driver |
| **Main use** | GitOps delivery of Kubernetes manifests | Lifecycle of the application stack |

Use Argo CD or Flux for GitOps delivery of infrastructure changes, and
Styrmin for the lifecycle of the applications that run on it.

### How Styrmin compares to internal developer platforms

Internal developer platforms (IDPs), such as Backstage-based portals and
commercial IDPs, help developers deploy their own applications. Styrmin
manages a group of infrastructure applications as one stack, and runs
the backup and upgrade procedures that each application's driver
defines.

### Styrmin and Kubernetes

Styrmin runs on Kubernetes. A later version will include a Kubernetes
distribution, so you will not need to install or operate Kubernetes
separately.

You keep `kubectl`, Helm, and Argo CD. Drivers deploy applications with
Helm charts. Styrmin replaces the manual steps between your
applications: the backup scripts, the upgrade runbooks, and the copies
of production for testing.

### Common questions

| Question | Answer |
|----------|--------|
| Does Styrmin replace Kubernetes? | No. It runs on Kubernetes. |
| Does it replace Helm? | No. Drivers deploy applications with Helm charts. You set driver parameters instead of each chart's values. |
| Do my existing tools (Jenkins, monitoring, direct API access) keep working? | Yes. Styrmin manages deployment and lifecycle. It does not intercept or proxy application traffic. |
| Can I use it for applications other than Infrahub? | Yes, for any application that has a driver. Styrmin does not depend on a specific application, and you add an application by writing its driver. |
| Can it manage applications that do not run on Kubernetes (VMs, SaaS)? | The first version supports Kubernetes only. SaaS applications (for example, Kentik) and several clusters are on the roadmap. VM support comes later. |
| Is there a commercial offering? | Not in the short term. Styrmin is an independent open-source project, so that other vendors and application teams can build drivers and use it. |

### Next steps

- [**Platform overview**](./platform-overview.md): the components of
  Styrmin and the terms driver, cluster, environment, and deployment.
- [**Quickstart**](../installation/quickstart.md): run the bundled demo
  on your laptop.
- [**What is an application driver?**](../concepts-and-architecture/what-is-a-driver.md):
  the specification Styrmin uses to deploy and operate each application.
