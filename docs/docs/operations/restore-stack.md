---
title: Restore a stack
sidebar_position: 4
description: Restore an environment from a previous backup, applied across every deployment in that environment with each driver running its own restore procedure.
---

## Restore a stack

:::info Stub page

This guide is a placeholder while the stack-wide restore flow
stabilises behind the GraphQL API. The capability exists today and is
exercised by the restore E2E scenarios in `backend/tests/e2e/`. This
page will be filled in once the user-facing CLI / SDK surface is
final.

For now, see the E2E flows in
[`backend/tests/e2e/scenarios/`](https://github.com/opsmill/styrmin/tree/develop/backend/tests/e2e)
for the authoritative sequence of API calls.

:::

### What you'll be able to do here

Restore an Environment from a previous backup — every Deployment in
the Environment is restored from the matching backup artefact, with
each Application Driver running its own restore procedure.

### Outline (to be filled in)

1. **Pick a backup.** List backups for the Environment; pick the one
   you want to restore.
2. **Trigger the restore.** Single CLI / SDK / GraphQL call against
   the Environment, referencing the backup.
3. **Watch the rollout.** Each Deployment transitions through
   `RESTORING` and back to `RUNNING`; the operator and FluxCD do the
   reconciliation, the driver-defined restore action does the
   application-specific glue.
4. **Verify.** Each Deployment is `RUNNING` and the application data
   matches the restored point in time.

### Related

- [Back up a stack](./back-up-stack.md) — the producing operation.
- [Concepts and Architecture → Backups and restores](../concepts-and-architecture/backups-and-restores.md)
  — runtime architecture, including how Velero is used under the
  hood.
- [Clone an environment](./clone-environment.md) — restore into a
  different Environment instead of overwriting the source.
