# ADR-064: StyrminDeployment Writes Ordered by a Per-Deployment Instance Sequence

**Status**: Accepted
**Date**: 2026-10-10
**Source**: [issue #386](https://github.com/opsmill/styrmin/issues/386) and the review of
[PR #414](https://github.com/opsmill/styrmin/pull/414).
**Related**: [ADR-060](0060-steps-and-derived-task-result.md) (remediation flows run without
database access; a newer task's write supersedes older rollouts),
[ADR-001](0001-alembic-database-migrations.md) (the revision this ships).

## Context

Each accepted change of a deployment schedules its own `apply_state` flow, and each starts a
remediation flow that writes the StyrminDeployment. Nothing ordered those writes, so when the
flow of an earlier change wrote last, the deployment ran the older configuration until the next
change (#386).

The remediation flow runs as a Kubernetes Job without database access (ADR-060), so it can
compare only what the StyrminDeployment and its own instance carry.

A first version of the fix compared `applicationinstance.created_on`. That value is the start of
the creating transaction, not its commit, so two overlapping changes could commit in the other
order. It also depends on the database clock, and SQLite stores it to the second.

## Decision

1. Each instance carries `sequence`, 1 for the deployment's first instance and one more for each
   new one. `deployment.last_instance_sequence` is the counter.
2. `SQLModelDeploymentRepository.save` assigns the sequence to a new active instance with an
   `UPDATE ... SET last_instance_sequence = last_instance_sequence + 1 ... RETURNING`. The row
   lock that the UPDATE takes lasts until commit, so the instance committed last holds the
   highest sequence and is the active instance. A unique constraint on
   `(deployment_id, sequence)` rejects a duplicate.
3. The StyrminDeployment records the sequence in the `styrmin.io/instance-sequence` annotation.
   A flow leaves a StyrminDeployment that holds a higher sequence unchanged, and writes with a
   JSON Patch that starts with a `test` of `metadata.resourceVersion`.

## Consequences

- For changes made one after another, the deployment runs the last change in whatever order
  the flows finish, and the task of the earlier change ends `superseded`.
- For changes made at the same time, the cluster and the deployment page agree on the change
  saved last. That change does not include the other one, because `updateDeployment` takes no
  lock when it reads the deployment.
- The flow of an earlier change still runs its driver hooks.
- Users must not edit the annotation. A value above every instance's sequence makes every later
  flow leave the StyrminDeployment unchanged until someone removes it.
- Every code path that inserts an instance row must go through the repository save, or set the
  sequence and the counter together.
