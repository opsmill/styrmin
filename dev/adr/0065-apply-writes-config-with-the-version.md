# ADR-065: `apply` Writes the Config and the Version in One Mutation

**Status**: Accepted
**Date**: 2026-10-08
**Source**: [issue #388](https://github.com/opsmill/styrmin/issues/388)
**Narrows**: [ADR-048](0048-declarative-apply-client-side-orchestration.md) §4 ("config before
version, sequentially") and its accepted double reconcile.
**Resolves**: the `styrminctl apply` consequence of
[ADR-057](0057-post-render-component-overrides.md) ("validates its config write against the
pre-switch version").
**Related**: [ADR-054](0054-backend-authoritative-noop-detection.md) (no-op detection),
[ADR-058](0058-image-overrides-and-component-container-guard.md) (the image checks the config
write runs, and the upgrade-action race that #431 tracks).

## Context

`apply` sent `updateDeployment` (config and parameters) and then `updateDeploymentVersion`.
`updateDeployment` validates component-scoped config against the driver version the deployment
is bound to when it runs, which is the version the manifest moves away from. A manifest that is
valid for the version it declares could therefore fail, and one that is invalid could pass:

- env vars on a component that gains a component container in the new version were rejected
  with `COMPONENT_CONTAINER_NOT_DECLARED`, and the deployment stayed on the old version;
- env vars or container overrides on a component the new version adds were rejected as
  targeting an unknown component;
- env vars on a component that loses its container in the new version were accepted, then
  stored but never injected (`isApplicable: false`).

The only way through was two applies: upgrade first, then configure. ADR-048 rejected running
the version first, because the upgrade would reconcile against the stale config.

## Decision

1. **`updateDeploymentVersion` takes an optional `input: UpdateDeploymentInput`.** Its fields
   keep their `updateDeployment` semantics: the config fields replace the stored config,
   `name` renames the deployment, `parameters` merge on top of the `parameters` argument (or
   the stored parameters), and `serviceNameOverrides` replace the overrides in effect. Without
   `serviceNameOverrides`, the current overrides are kept, as before.
2. **The input is validated against the target versions.** The service resolves the target
   driver version first: the pinned one, or the newest loaded driver version whose specifier
   matches the application version. It then runs the config checks of `updateDeployment`
   against that driver version and the target application version (`_validate_config_write`
   in `services/deployment.py`), and the name, parameter and service name checks. The errors
   name the driver, driver version and application version that were checked. Every check
   runs before the ingress controller is ensured, so a rejected call writes nothing and starts
   no task and no flow run.
3. **One transaction, one task.** The config, name, parameters, version and driver binding
   are written together and one task reconciles them. The task is `UPGRADE_INSTANCE` with the
   deployment in `DEPLOYING` when the application version or the driver binding changes;
   otherwise it is `UPDATE_INSTANCE` with the deployment in `PENDING`, as on
   `updateDeployment`.
4. **Deployed services are recreated only when they change**, that is when the driver binding
   or a resolved service name changes, and before the instance is generated, so the instance
   context carries the target version's services and the renamed ones. A call that changes
   nothing leaves them as they are.
5. **No-op detection is unchanged.** When the new instance equals the current one, the call
   returns `null` and starts no task. A change the instance does not carry, such as a rename,
   is still written, as `updateDeployment` writes it.
6. **`apply` sends one `updateDeploymentVersion` per existing deployment**, with the manifest's
   config and parameters as `input`. It still sends it when the version is unchanged: the
   backend re-resolves the driver version and returns `null` on a no-op (`action="unchanged"`).
   A rejected call returns `action="failed"` with the server's error code, as the version
   step did before.
7. **The SDK sends `input` in its own operation.** `update_version()` without `input` sends
   the operation older servers accept. With `input`, an older server answers
   `Unknown argument 'input'`, and the SDK raises `IncompatibleServerError`, which says to
   upgrade the server.

### How `updateDeploymentVersion` differs from `updateDeployment`

The two mutations share `_validate_config_write`, `_validate_new_name` and
`split_update_deployment_input`, and keep separate service functions because they differ in
these ways:

| | `updateDeployment` | `updateDeploymentVersion` |
| --- | --- | --- |
| Driver version checked | The pinned one | The target one, resolved per call |
| Commit phases | Two: the input, then the instance and the task | One |
| Task and status | `UPDATE_INSTANCE`, `PENDING` | `UPGRADE_INSTANCE`, `DEPLOYING` on a version or binding change, else as `updateDeployment` |
| Services | Recreated when `serviceNameOverrides` is set | Recreated when the binding or a resolved name changes |
| `parameters` | `input.parameters` merge on the stored ones | The `parameters` argument replaces them, `input.parameters` merge on top |

## Consequences

- Component config that the declared version can apply is accepted in one apply. Config that
  it cannot apply is rejected, whatever version the deployment was on before. This includes
  unchanged env vars on a component the declared version removes or renames: the manifest
  must drop them in the same change that moves the version. The upgrade dialog and
  `update_version()` without `input` do not send the config, so they still accept that upgrade
  and leave the block orphaned.
- Unchanged env vars or an unchanged image override on a component that loses its component
  container pass validation, as on `updateDeployment`, and are stored but not applied. `apply`
  reads `isApplicable` back after the update and warns on stderr
  (`ApplyOutcome.inapplicable_components`).
- A rejected apply leaves the deployment unchanged. The partial state ADR-048 had to report
  ("config/parameters were updated; version upgrade failed") no longer occurs.
- The double reconcile ADR-048 accepted is gone: one task per apply.
- `updateDeployment` is unchanged and still validates against the pinned version; it never
  switches versions.
- `apply` no longer calls `updateDeployment`. A client that wants the old two-step behaviour
  can still call both mutations.
- On every version change, including the upgrade dialog, `update_version()` and driver
  actions, the services are now recreated before the instance is generated. Values templates
  that read the deployed services (`services[...]`) see the target version's services in the
  upgrade itself; before, the context lagged one reconcile behind.
- A `styrminctl` or SDK with this change needs a server with it for `apply` and for
  `update-version --config`. Upgrade the server before or together with the clients. An older
  SDK keeps working against a newer server, because it still sends the two mutations.
- One apply can set an image override and change the version, but the driver's upgrade action
  can still read the workload before the override renders (ADR-058). Setting the override in
  an earlier apply avoids that only when the current driver version accepts it; when only the
  target version declares the component or its container, there is no workaround yet (#431).
  *Resolved by #431: the action primitives take the image override and the env vars from the
  action's context, so the upgrade Job uses them in the same apply (ADR-058 §6 note).*

## Alternatives Considered

- **A validation-only `targetVersion` argument on `updateDeployment`.** Rejected: two
  mutations and two reconciles remain, the first reconcile runs the old version with config
  meant for the new one, and a failed version switch leaves that config stored.
- **Send the version first, then the config.** Rejected for the reason in ADR-048: the upgrade
  reconciles against the stale config, and a rejected config leaves the deployment upgraded
  without it.
- **A server-side `apply` mutation.** Rejected for the reasons in ADR-048. Extending the
  existing version mutation adds no new endpoint, batch semantics or rollback story.
- **One shared service function for both mutations.** Not done: the commit phases and the
  version resolution differ (table above), so the shared parts are the validators and the
  input split.
