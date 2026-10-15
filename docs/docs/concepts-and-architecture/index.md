---
title: Concepts and Architecture
sidebar_position: 1
description: The mental model and the under-the-hood architecture — pick the depth you need.
---

## Concepts and Architecture

This section serves two purposes:

- **The first few pages give you the mental model** you need to use
  Styrmin — driver, cluster, environment, deployment, reconciliation,
  context. Read these.
- **The remaining pages are optional under-the-hood detail.** Read them
  when you want to understand what's happening internally — usually
  because something surprised you, because you're integrating Styrmin
  into a larger system, or because you're about to write a driver and
  want to know which lifecycle hook runs when.

Each page is **short, educational, and assumes you are not a Kubernetes
expert.** We explain the moving parts in plain English and link out to
the deeper internal docs when you want more.

### What's in here

| Page | Read it when… |
|------|---------------|
| [Architecture](./architecture.md) | You want the big picture: server, agent, database, and how they talk to each other. |
| [Reconciliation](./reconciliation.md) | You're wondering what actually happens between "I changed this deployment" and "the cluster matches". |
| [The operator and `StyrminDeployment`](./operator-and-crds.md) | You've heard the word "CRD" or "operator" and want to know what Styrmin is doing with them. |
| [Ingress and networking](./ingress-and-networking.md) | You want to understand how an application becomes reachable on a URL after you deploy it. |
| [Backups and restores](./backups-and-restores.md) | You want to know what Styrmin actually does when you click "backup", and where the data ends up. |
| [Image overrides](./image-overrides.md) | You want one component of a deployment to run a custom or patched build without forking its driver. |
| [Replica overrides](./replica-overrides.md) | You want one component of a deployment to run more or fewer pods, or you want to know where a component's pod count comes from. |
| [Lifecycle hooks and actions](./hooks-and-actions.md) | You're about to write a driver, or you want to know how Styrmin runs the right code at the right moment. |
| [Status reporting](./status-reporting.md) | You're wondering how the UI stays up-to-date with what's actually running in the cluster. |

### Suggested reading order

If you read top-to-bottom, the pages build on each other:

1. **Architecture** first — everything else slots into the picture it
   draws.
2. **Reconciliation** — the core loop Styrmin runs over and over.
3. **The operator and `StyrminDeployment`** — what reconciliation looks
   like once the agent is involved.
4. The remaining pages are independent — read whichever solves your
   current problem.

If you just want one specific answer, jump straight to that page from
the table above.
