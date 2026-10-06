# ADR-059: Short-Lived API Tokens for Driver Actions

**Status**: Accepted
**Date**: 2026-10-05
**Source**: [issue #381](https://github.com/opsmill/styrmin/issues/381)
**Related**: [ADR-016](0016-authentication-and-sessions.md) (session rows and bearer tokens),
[ADR-017](0017-authorization-model.md) (the default-deny gate, the allow-list and `RequiresRole`).
Follow-up for the callers that are still allow-listed:
[issue #396](https://github.com/opsmill/styrmin/issues/396).
Extended by [ADR-060](0060-steps-and-derived-task-result.md): `run_job` tasks, backups and restores
also create an action token, and flows use it to record steps.

## Context

Driver actions call three primitives that use the GraphQL API: `stop_components`,
`start_components` and `upgrade_deployment_version`. Each calls a mutation that requires the
`READ_WRITE` role, then polls `Query.task`, which requires authentication. The primitives sent no
credentials, so after the default-deny gate (ADR-017) every call failed with
`Authentication is required`. Every bundled driver's `upgrade` action calls at least one of them.

A reconcile runs in three processes:

1. `apply_state` runs on `styrmin-work-pool`, in the task worker pod, which has database access.
2. It starts the remediation flow (`create_instance_crd` or `upgrade_instance_crd`) as a Kubernetes
   Job on `user-work-pool`. The Job has no database access and no credentials.
3. The remediation flow starts each driver action as a separate Job on `user-work-pool`.

## Decision

1. **A built-in user for driver actions.** `ensure_actions_service_account` creates the user
   `styrmin-actions` with the `READ_WRITE` role the first time a reconcile needs it, with
   `INSERT … ON CONFLICT DO NOTHING`. Its password hash is not an Argon2 hash, so `login` rejects
   every password. An existing row is used as it is, so an admin who deactivates the user or
   changes its role keeps that change.
2. **One session per reconcile.** `apply_state` creates an ordinary `Session` row for that user
   before it applies the remediation, and deletes the row when the remediation returns or raises.
   The row expires after 24 hours instead of 30 days; the expiry only matters when the task worker
   dies before it deletes the row.
3. **The token travels in `STYRMIN_TOKEN`.** `apply_state` passes it to the remediation flow's Job
   as a Prefect flow-run job variable (`env`). The remediation flow passes its own value to each
   action's Job the same way (`run_driver_action_or_fail`). Prefect adds a flow run's `env` to the
   work pool's default `env` (`STYRMIN_URL_API` stays set). The SDK reads the same variable, so an
   action that uses the SDK is authenticated as well.
4. **The primitives send `Authorization: Bearer <STYRMIN_TOKEN>`.**
5. The allow-list, the GraphQL schema and the database tables do not change.

## Alternatives considered

- **Allow-list the three mutations and `Query.task`.** Anyone who can reach the API could stop,
  start or change the version of any deployment. Rejected.
- **A long-lived token from a Helm-managed Secret.** The token never rotates, Prefect stores it in
  the user work pool's base job template, and existing installs need a chart change. Rejected.
- **The identity of the user who started the reconcile.** `Task` has no initiator column, so this
  needs a migration, and reconciles that Styrmin starts itself (the environment configuration
  fan-out) have no user. Rejected for now.
- **A token limited to one deployment.** Needs a scope column on `Session` and a scope check next
  to `RequiresRole`. Deferred.

## Consequences

- While its token is valid, an action can call any `READ_WRITE` field on any deployment, not only
  its own deployment.
- Anyone who can read Prefect flow runs, or the Job specs in the deployment namespace, can read the
  token. Deleting the session at the end of the reconcile limits how long the token is usable.
- An action that runs longer than 24 hours loses access to the API.
- `styrmin-actions` appears in the user list. Deactivating it, or setting its role to `READ_ONLY`,
  stops actions from calling the API. Resetting its password makes it a user someone can log in as.
  See [Users and Groups](../guides/users-and-groups.md#driver-actions-user-styrmin-actions).
- Every reconcile writes and deletes one `Session` row.
- The agent status reporter, the flow-run state callback and `GET /deployments/{id}/context` still
  accept calls without credentials. Issue #396 tracks them.
