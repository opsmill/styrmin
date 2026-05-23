---
title: Clone an environment
sidebar_position: 5
description: Duplicate an environment — applications, configuration, and live data — to a fresh target so changes can be validated against real data before they touch production.
---

## Clone an environment

:::warning Not yet available

Environment cloning is **not available yet**. It is a headline
Styrmin capability and will be delivered before the beta release.
This page describes the intended shape of the feature so the docs
match where the product is going; the CLI / SDK / GraphQL surface
will land alongside the feature itself.

:::

### What you'll be able to do here

Duplicate an Environment — every Deployment in it, plus the live
application data — into a fresh target Environment. Cross-application
connectivity is environment-aware, so the cloned Environment is
self-contained: applications in the clone talk to each other, not back
to the source.

This is the headline capability behind "test upgrades against real
data" and "rehearse a change without touching production".

### Outline (planned)

1. **Prepare the source.** Confirm the source Environment is healthy
   and that a recent backup exists in its Backup Storage Location.
2. **Create the target Environment.** Either an empty Environment in
   the same Cluster, or a fresh one in a different Cluster (when
   multi-cluster lands).
3. **Run the clone.** Trigger the clone operation via CLI / SDK /
   GraphQL. The clone applies the source's snapshots to the target's
   Deployments, then reconciles each one.
4. **Verify.** Confirm each Deployment in the target is `RUNNING` and
   that cross-application connectivity stays inside the target
   Environment.

### Related

- [Concepts and Architecture → Backups and restores](../concepts-and-architecture/backups-and-restores.md)
  — what Styrmin actually does on backup/restore and where the data
  ends up.
- [Upgrade an application / deployment](./upgrade-deployment.md) — the
  most common reason to clone an Environment.
