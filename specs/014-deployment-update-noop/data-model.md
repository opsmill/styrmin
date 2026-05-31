# Data Model: Backend No-Op Detection for Deployment Updates

**No database schema change.** No new tables, columns, indexes, enums, or migrations. The feature *removes* writes (a no-op no longer inserts an `ApplicationInstance` or `Task` row); it adds none.

## Entities touched (all existing)

| Entity | Change |
|---|---|
| `Deployment` | None to the row shape. Behaviour: a no-op update leaves `status` and `active_application_instance_id` untouched (today they are bumped). |
| `ApplicationInstance` | None to the row shape. Behaviour: a no-op update creates **zero** rows (today it creates one throwaway row per update). |
| `Task` | None to the row shape. Behaviour: a no-op update creates **zero** rows (today it creates one reconcile task that the flow then no-ops). |

## Service-layer signature changes (not persisted state)

| Function | Before | After |
|---|---|---|
| `services/deployment.py::update_deployment` | `-> Task` | `-> Task \| None` (None = no-op) |
| `services/deployment.py::update_deployment_version` | `-> Task` | `-> Task \| None` (None = no-op) |

## SDK model

| Type | Change |
|---|---|
| `ApplyOutcome.action` | Literal `created \| updated \| unchanged \| failed` (the `unchanged` value is retained from the stopgap; now set from a `null` backend task, not a client-side diff). |
| `DeploymentResource.update` / `update_version` return | `... \| None` — a `null` GraphQL task payload maps to `None`. |

## GraphQL surface

Unchanged. `updateDeployment(deploymentId: UUID!, input: UpdateDeploymentInput!): Task` and `updateDeploymentVersion(deploymentId: UUID!, version: String!, parameters: JSON = null): Task` are already nullable; `null` is now a legitimate (no-op) return rather than only an error indicator. No regen.

## Removed behaviour

- The service-side guard `InvalidContextError("At least one of config, parameters, name, or serviceNameOverrides must be provided")` in `update_deployment` is removed. Validation errors for *malformed* input (invalid env-var name, duplicate component/parameter, malformed scheduling) are unaffected — they fire before instance generation.
