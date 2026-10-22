---
title: Concepts and architecture
sidebar_position: 1
description: The terms Styrmin uses and how its components work.
---

## Concepts and architecture

Read [Core concepts](./core-concepts.md) and
[What is an application driver?](./what-is-a-driver.md) first: they define
the terms that the other pages use. The [Glossary](./glossary.md) gives a
one-sentence definition of each term.

Each other page explains one internal mechanism. Read it when you need
it: for example, when Styrmin does something you did not expect, when
you connect Styrmin to another system, or when you write a driver and
need to know which lifecycle hook runs when.

### Pages in this section

| Page | Read it when you want to |
|------|--------------------------|
| [Architecture](./architecture.md) | Know the components (server, agent, database) and how they connect. |
| [Reconciliation](./reconciliation.md) | Know what happens between a change to a deployment and the cluster matching it. |
| [The operator and `StyrminDeployment`](./operator-and-crds.md) | Know what the operator and the `StyrminDeployment` custom resource do in the cluster. |
| [Ingress and networking](./ingress-and-networking.md) | Know how an application gets a URL after you deploy it. |
| [Backups and restores](./backups-and-restores.md) | Know what Styrmin does when you start a backup, and where it stores the data. |
| [Image overrides](./image-overrides.md) | Run a custom or patched build on one component of a deployment, without forking its driver. |
| [Replica overrides](./replica-overrides.md) | Change the number of pods of one component, or find where a component's pod count comes from. |
| [Node affinity](./node-affinity.md) | Run a deployment's pods only on nodes with a given label, or replace a removed `node_selector` value. |
| [Lifecycle hooks and actions](./hooks-and-actions.md) | Write a driver, or know which hook runs which driver code, and when. |
| [Status reporting](./status-reporting.md) | Know how the UI shows the state of the cluster. |

### Reading order

The pages below build on each other:

1. **Architecture**: the other pages refer to its components.
2. **Reconciliation**: the loop that Styrmin runs for each change.
3. **The operator and `StyrminDeployment`**: reconciliation inside the
   cluster, in the agent.

The other pages are independent. Read the one that answers your
question.
