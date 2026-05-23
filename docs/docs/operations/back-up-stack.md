---
title: Back up a stack
sidebar_position: 3
description: Trigger a backup across every application in an environment in a single operation, with each driver applying its own correct procedure.
---

## Back up a stack

:::info Stub page

This guide is a placeholder while the stack-wide backup flow stabilises
behind the GraphQL API. The capability exists today and is exercised by
the backup E2E scenarios in `backend/tests/e2e/`. This page will be
filled in once the user-facing CLI / SDK surface is final.

For now, see the E2E flows in
[`backend/tests/e2e/scenarios/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e)
for the authoritative sequence of API calls, and
[Concepts and Architecture → Backups and restores](../concepts-and-architecture/backups-and-restores.md)
for the runtime architecture.

:::

### What you'll be able to do here

Trigger a backup across every Deployment in an Environment in a single
operation. Each Deployment's Application Driver knows how to back up
its application correctly — Neo4j, Postgres, and stateless workloads
need different procedures, and the driver encodes that.

### Outline (to be filled in)

1. **Verify the Backup Storage Location.** Each Environment is bound
   to one Backup Storage Location (a Velero-compatible S3 endpoint).
   Confirm it's reachable and writable.
2. **Trigger the backup.** Single CLI / SDK / GraphQL call against
   the Environment.
3. **Inspect the result.** Each Deployment's backup record points at
   the artefacts in the Backup Storage Location, with status, size,
   and timestamps.

### Related

- [Concepts and Architecture → Backups and restores](../concepts-and-architecture/backups-and-restores.md)
  — the runtime view: Velero, Backup Storage Locations, per-driver
  procedures.
- [Restore a stack](./restore-stack.md) — the inverse operation.
- [Clone an environment](./clone-environment.md) — backup + restore
  into a new target.
