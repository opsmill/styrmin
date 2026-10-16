---
title: Changing Driver Versions
sidebar_position: 5
description: What Styrmin checks when a deployment moves to another driver version, and how to fix a rejected change.
---

## Changing Driver Versions

A deployment moves to another driver version when you upgrade it, with the **Upgrade** button on
the deployment page, `styrminctl deployments update-version` or the `updateDeploymentVersion`
mutation, and when `styrminctl deployments apply` binds it to a newer loaded driver version.
[Loading a Driver](./loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)
explains which driver version Styrmin binds to.

Before any task starts, Styrmin checks the deployment's parameters and overrides against the
target driver version. When a check fails, Styrmin rejects the change: the deployment stays on its
current driver version and no pod changes.

### Parameters the target driver version no longer declares

A **retired parameter** is a parameter that the current driver version declares and the target
driver version does not. Styrmin checks each retired parameter that the deployment sets, in the
stored values together with the parameters sent in the same request:

- If the value equals the parameter's default in the current driver version, Styrmin drops the
  value and the change continues.
- Otherwise, Styrmin rejects the change with the error code `RETIRED_PARAMETER_VALUE`, so a value
  that you changed is never lost without a message.

A value must have the same type as the default to be equal: the string `"2"` does not equal the
integer default `2`. The error carries the parameter name (`parameter_name`), its value (`value`),
its default in the current driver version (`default`) and the target driver version
(`checked_against`). When several retired parameters hold a changed value, the error names the
first one by name.

The rule applies to every driver. The `infrahub` and `infrahub-enterprise` example drivers retire
their replica parameters; [Migrating Replica Parameters](./migrating-replica-parameters.md)
describes that case.

### Fix a rejected driver version change

Find out what the retired parameter did in the current driver version, from the driver's
documentation or its `values.j2.yml`. Then, in the same request as the driver version change or
before it:

1. Carry the setting over to what replaces it in the target driver version, if anything does. For
   example, a parameter that set a replica count becomes a
   [replica override](../concepts-and-architecture/replica-overrides.md) on the component.
2. Reset the parameter to its default.
3. Change the driver version again. Styrmin drops the parameter, because it now holds its
   default.

In the UI, the **Upgrade Deployment** dialog lists these steps when it shows the error. Make the
change on the **Settings** tab with **Update Settings**, then click **Upgrade** again. With the
API, the SDK and `styrminctl`, send the parameter at its default in `input.parameters` of
`updateDeploymentVersion`, or in `spec.parameters` of a manifest.

### A retired parameter that has no default

A parameter that declares no default cannot be reset to its default, so the steps above do not
apply. The only way to drop it is the top-level `parameters` argument of
`updateDeploymentVersion` in GraphQL, which replaces every stored parameter value: send every
parameter you keep, without the retired one. The UI, the SDK and `styrminctl` do not send this
argument.

### A request or manifest that still lists a retired parameter

After the deployment moves to the target driver version, the parameter is no longer declared. A
request or a manifest that still sets it fails with `OPERATION_FAILED` and the message
`Unknown parameter: '<name>'`, which links this page. Remove the parameter from the request or the
manifest.

### Overrides on components the target driver version changes

- An override stored on a component that the target driver version no longer declares stays
  stored and is not applied. The **Component Overrides** card on the **Settings** tab lists it as
  orphaned.
- A replica override above 1 on a component that the target driver version marks as singleton
  rejects the change with `SINGLETON_REPLICA_OVERRIDE`, until the same request lowers the override
  to 1 or clears it. See [Replica Overrides](../concepts-and-architecture/replica-overrides.md).

### Related pages

- [Loading a Driver](./loading-drivers.md): load a driver version and choose the one a deployment
  binds to.
- [Migrating Replica Parameters](./migrating-replica-parameters.md): the infrahub replica
  parameters.
- [`styrminctl` reference](../reference/styrminctl.md): `deployments update-version` and
  `deployments apply`.
