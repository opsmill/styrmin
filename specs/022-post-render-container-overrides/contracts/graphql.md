# Contract: GraphQL and SDK Changes

**Feature**: [../spec.md](../spec.md) | Research D-008

Both changes are approved in the PRD's governance gates (spec "Governance Gates Crossed").

## Removed

```graphql
type ApplicationDriverVersion {
  # removed:
  containerOverrides: [DriverContainerOverrideDoc!]!
}

# removed type:
type DriverContainerOverrideDoc {
  component: String!
  description: String!
  container: String
  command: Boolean!
  args: Boolean!
}
```

A query that selects `containerOverrides` fails validation with the standard "Cannot query field" error. The frontend does not select it today. The SDK loses the `GetDriverContainerOverrideDocs` operation and its generated client method `get_driver_container_override_docs`.

## Added

```graphql
type ComponentContainerOverrides {
  component: String!
  command: [String!]
  args: [String!]
  isOrphaned: Boolean!
  """
  False when the override cannot reach a container: the component is orphaned
  (`isOrphaned`) or the driver declares no component container for it. The stored
  values are kept but not applied.
  """
  isApplicable: Boolean!
}
```

`isApplicable` = the component is not orphaned **and** the deployment's pinned driver version declares a component container for it. Same rule and wording as `ComponentEnvVars.isApplicable` and `ComponentImageOverride.isApplicable`.

The type description changes from "injected into rendered pods ... chart default flows through" wording tied to the values template to: "Applicable overrides are applied by a post-render patch to the component container the driver declares."

## Unchanged

- `UpdateDeploymentInput.components[].command` / `.args` and the `deploy` config JSON: same shape and validation. The write gains the `COMPONENT_CONTAINER_NOT_DECLARED` check ([errors.md](errors.md)).
- `Deployment.components[].container`: already exposed; the frontend reads it to gate the editors.

## Regeneration

1. `uv run styrmin export graphql-schema schema.graphql`
2. Delete `python_sdk/src/styrmin_sdk/graphql/get_driver_container_override_docs.graphql` and `backend/tests/functional/graphql/operations/get_driver_container_override_docs.graphql`.
3. Add `isApplicable` to `python_sdk/src/styrmin_sdk/graphql/get_deployment_component_container_overrides_full.graphql`.
4. `uv run invoke generate` (SDK Pydantic types and `frontend/src/generated/graphql.ts`), then `uv run invoke validate-graphql`.

## Propagation test

[`test_container_overrides_propagation.py`](../../../backend/tests/functional/graphql/test_container_overrides_propagation.py):

- `isApplicable: true` for a stored override on a component with a component container;
- `isApplicable: false, isOrphaned: false` for a component without a component container (seeded before the check existed, or by a driver version change);
- `isApplicable: false, isOrphaned: true` for an orphaned block;
- `test_driver_container_override_docs_projected` and `test_driver_container_overrides_empty_when_unset` are deleted.
