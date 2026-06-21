# Contract: `updateDeployment` / `updateDeploymentVersion` no-op behaviour

**No schema change.** Both mutations keep their current signatures and nullable `Task` return. This contract pins the *behavioural* change and the propagation tests that enforce it.

## `updateDeployment(deploymentId: UUID!, input: UpdateDeploymentInput!): Task`

| Scenario | Before | After (this feature) |
|---|---|---|
| Input resolves to a real change vs current instance | new `Instance` + reconcile `Task`; returns the `Task` | unchanged — new `Instance` + reconcile `Task`; returns the `Task` |
| Input resolves to **no change** (incl. empty/no-op input) | **error** `INVALID_CONTEXT` ("At least one of config…") *or* a throwaway `Instance` + `Task` that the flow then no-ops | **`null`** — no `Instance`, no `Task`, deployment `status` untouched |
| Input is malformed (invalid env-var name, duplicate component/parameter, malformed scheduling) | typed error (`INVALID_ENV_VAR_NAME`, `DUPLICATE_COMPONENT_NAME`, …) | unchanged — same typed error, raised before generation |
| Targeted deployment is internal | internal-deployment guard error | unchanged |

## `updateDeploymentVersion(deploymentId: UUID!, version: String!, parameters: JSON = null): Task`

| Scenario | After |
|---|---|
| `version` differs from the deployment's current version | upgrade dispatched; returns the `Task` |
| `version` equals the current version (no other change) | **`null`** — no `Instance`, no `Task`, status untouched |

## Propagation tests (Constitution §V — these mutations change behaviour)

1. **`updateDeployment` no-op → null, DB unchanged**: seed a deployment with a known active instance; call `updateDeployment` with an input equal to current state; assert the response `updateDeployment` is `null`, and that the instance count and the deployment's `active_application_instance_id` + `status` are unchanged in the DB.
2. **`updateDeployment` real change → task + new instance**: call with a changed config; assert a non-null `Task` and exactly one new `ApplicationInstance`.
3. **`updateDeployment` empty input → null (not error)**: call with an effectively-empty input; assert `null`, no `INVALID_CONTEXT` error (the removed guard).
4. **`updateDeploymentVersion` same version → null**: assert `null`, no new instance/task.
5. **`updateDeploymentVersion` new version → task**: assert non-null `Task`, upgrade dispatched.

## CLI / SDK rendering contract

- SDK: `null` task → `ApplyOutcome(action="unchanged", task_id=None)`; non-null → `created`/`updated` with `task_id`.
- CLI: `unchanged <name>` line; summary `"N created, M updated, K unchanged, J failed"`; a no-op-only run exits 0.
