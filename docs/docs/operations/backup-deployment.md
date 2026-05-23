---
title: Backup an existing Deployment
sidebar_position: 3
description: Trigger a backup of one existing Deployment via its driver's backup procedure, with artefacts stored in the Environment's Backup Storage Location.
---

## Backup an existing Deployment

:::info Stub page

This guide is a placeholder while the backup flow stabilises behind
the GraphQL API. The capability exists today and is exercised by the
backup E2E scenarios in `backend/tests/e2e/`. This page will be filled
in once the user-facing CLI / SDK / UI surface is final.

For now, see the E2E flows in
[`backend/tests/e2e/scenarios/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e)
for the authoritative sequence of API calls, and
[Concepts and Architecture → Backups and restores](../concepts-and-architecture/backups-and-restores.md)
for the runtime architecture.

:::

### What you'll be able to do here

Trigger a backup of one existing Deployment. The Application Driver
knows how to back the application up correctly — Neo4j, Postgres, and
stateless workloads each need different procedures, and the driver
encodes that. Backup artefacts go to the Environment's Backup Storage
Location.

### Outline (to be filled in)

1. **Verify the Backup Storage Location.** Each Environment is bound
   to one Backup Storage Location (a Velero-compatible S3 endpoint).
   Confirm it's reachable and writable.
2. **Trigger the backup.** Single CLI / SDK / GraphQL call against the
   Deployment.
3. **Inspect the result.** The Deployment's backup record points at
   the artefacts in the Backup Storage Location, with status, size,
   and timestamps.

### Related

- [Concepts and Architecture → Backups and restores](../concepts-and-architecture/backups-and-restores.md)
  — the runtime view: Velero, Backup Storage Locations, per-driver
  procedures.
- [Upgrade a deployment](./upgrade-deployment.md) — running a backup
  before an upgrade is the recommended pattern.
- [Clone an environment](./clone-environment.md) — backups are the
  foundation of cloning.
