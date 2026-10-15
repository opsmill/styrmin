# Contract: Error Codes

**Feature**: [../spec.md](../spec.md) | Research: [D-005](../research.md#d-005-write-checks-for-a-replica-override), [D-007](../research.md#d-007-rule-for-parameters-the-target-driver-version-no-longer-declares-fr-010)

Each error is a `ServiceError` subclass with `error_code`, `default_message` and `error_metadata`. `StructuredErrorExtension` returns `extensions = {"code": <error_code>, **metadata}`. Every new error is raised before any task, flow run or ingress change, and the stored row is unchanged.

## `INVALID_REPLICA_COUNT` (new)

`InvalidReplicaCountError` in `services/replicas/exceptions.py`. Raised by the `ComponentConfigBlock.replicas` validator on create, update and `updateDeploymentVersion` (which covers `styrminctl deployments apply`).

| Metadata | Value |
|----------|-------|
| `component_name` | the component |
| `requested_replicas` | the submitted value, as given |

Trigger: a value below 1 or above 2147483647 (Kubernetes `int32`), a `bool`, or a value that is not an integer (a JSON `config` map can carry any type; the GraphQL `Int` input already rejects non-integers).

Message: "Replica count for component '`<name>`' must be an integer from 1 to 2147483647, got `<value>`. To run no pods, stop the component instead."

## `UNKNOWN_COMPONENT_REPLICA_OVERRIDE` (new)

`UnknownComponentReplicaOverrideError` in `services/replicas/exceptions.py`.

| Metadata | Value |
|----------|-------|
| `component_name` | the component |
| `known_components` | sorted names the driver version declares |
| `checked_against` | the driver version label checked against (the bound one, or the target one on a version change) |

Trigger: a write adds or changes a replica override on a component that the driver version does not declare. Not raised for a removal or for the stored value sent again (an orphaned override is kept, FR-009).

Message: "Replica override targets component '`<name>`', which `<checked against>` does not declare. Known components: [...]".

## `SINGLETON_REPLICA_OVERRIDE` (new)

`SingletonReplicaOverrideError` in `services/replicas/exceptions.py`.

| Metadata | Value |
|----------|-------|
| `component_name` | the component |
| `requested_replicas` | the override (submitted or stored) |
| `checked_against` | the driver version label |

Trigger: an override greater than 1 on a component that the driver version marks `singleton: true`, on create, update, `updateDeploymentVersion` and `styrminctl deployments apply`. Raised for a stored value sent again too, because the stored count breaks the rule of the version the deployment is bound to after the write. An override of exactly 1 is accepted (FR-008).

Message: "Component '`<name>`' is a singleton component in `<checked against>` and runs exactly 1 replica; the requested count is `<N>`. Set the override to 1 or clear it."

## `RETIRED_PARAMETER_VALUE` (new)

`RetiredParameterValueError` in `services/parameters/exceptions.py`. Raised by `updateDeploymentVersion` (the UI upgrade dialog, the SDK, `styrminctl deployments apply` and driver action primitives use it).

| Metadata | Value |
|----------|-------|
| `parameter_name` | the parameter the target driver version no longer declares |
| `value` | the stored or submitted value |
| `default` | the parameter's default in the current driver version |
| `checked_against` | the target driver version label |

Trigger: on a driver version change, a parameter that the current version declares and the target version does not, with a value that is not equal (same type and value) to the current version's default. A value equal to the default is dropped with no error.

Message (FR-010a): "Parameter '`<name>`' is not declared by `<target>`, and this deployment sets it to `<value>` (default `<default>`). Remove the parameter or reset it to its default, then change the driver version again. If it set a replica count, carry the value over as a replica override on the component first. See https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters".

## Driver load error (existing code, new trigger)

`DriverLoadingError` (`VALIDATION_ERROR`), raised when a driver version is loaded:

| Trigger | Field path in the message |
|---------|---------------------------|
| `singleton: true` with `replicas` greater than 1 | `spec.components.<name>` |
| `replicas` below 1 or above 2147483647, a string, a float or a `bool` | `spec.components.<name>.replicas` |
| `singleton` not a `bool` | `spec.components.<name>.singleton` |

No driver version row is stored.

## Unchanged

- `COMPONENT_CONTAINER_NOT_DECLARED` does not apply to `replicas`: the replica patch needs no component container (FR-003). Its `override` metadata keeps the values `env_vars`, `image`, `command`, `args`.
- A parameter that neither the current nor the target driver version declares is still rejected by `validate_parameter_values` with `OPERATION_FAILED` "Unknown parameter".
