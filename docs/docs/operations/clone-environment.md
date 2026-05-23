---
title: Clone an environment
sidebar_position: 2
description: Duplicate an environment — applications, configuration, and live data — to a fresh target so changes can be validated against real data before they touch production.
---

## Clone an environment

:::info Stub page

This guide is a placeholder while the environment-clone flow stabilises
behind the GraphQL API. The capability exists today: it's exercised end
to end by the cloning E2E scenarios in `backend/tests/e2e/`. This page
will be filled in once the user-facing CLI / SDK surface is final.

For now, see the E2E flows in
[`backend/tests/e2e/scenarios/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e)
for the authoritative sequence of API calls.

:::

### What you'll be able to do here

Duplicate an Environment — every Deployment in it, plus the live
application data — into a fresh target Environment. Cross-application
connectivity is environment-aware, so the cloned Environment is
self-contained: applications in the clone talk to each other, not back
to the source.

This is the headline capability behind "test upgrades against real
data" and "rehearse a change without touching production".

### Outline (to be filled in)

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
- [Run an upgrade](./run-upgrade.md) — the most common reason to clone
  an Environment.
