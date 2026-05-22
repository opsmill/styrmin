---
title: How It Works
sidebar_position: 1
description: Optional deep dives into how Styrmin actually works — pick the topic you want.
---

## How It Works

You don't need this section to use Styrmin. If you can deploy an
application and run a backup, the rest is implementation detail you can
safely ignore.

These pages exist for the moment when you _want_ to understand what's
happening under the hood — usually because something surprised you,
because you're integrating Styrmin into a larger system, or because
you're about to write a driver and want to know which lifecycle hook
runs when.

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
| [Lifecycle hooks and actions](./hooks-and-actions.md) | You're about to write a driver, or you want to know how Styrmin runs the right code at the right moment. |
| [Status reporting](./status-reporting.md) | You're wondering how the UI stays up-to-date with what's actually running in the cluster. |

### Suggested reading order

If you read top-to-bottom, the pages build on each other:

1. **Architecture** first — everything else slots into the picture it
   draws.
2. **Reconciliation** — the core loop Styrmin runs over and over.
3. **The operator and `StyrminDeployment`** — what reconciliation looks
   like once the agent is involved.
4. The remaining four are independent — read whichever solves your
   current problem.

If you just want one specific answer, jump straight to that page from
the table above.
