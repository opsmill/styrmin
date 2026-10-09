# ADR-061: `apply` Writes the Config and the Version in One Mutation

**Status**: Accepted
**Date**: 2026-10-08
**Source**: [issue #388](https://github.com/opsmill/styrmin/issues/388)
**Narrows**: [ADR-048](0048-declarative-apply-client-side-orchestration.md) §4 ("config before
version, sequentially") and its accepted double reconcile.
**Resolves**: the `styrminctl apply` consequence of
[ADR-057](0057-post-render-component-overrides.md) ("validates its config write against the
pre-switch version").
**Related**: [ADR-054](0054-backend-authoritative-noop-detection.md) (no-op detection, unchanged),
[ADR-058](0058-image-overrides-and-component-container-guard.md) (the image checks the config
write runs).

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
   driver version first, then runs the same config checks as `updateDeployment` against that
   driver version and the target application version (`_validate_config_write` in
   `services/deployment.py`). Nothing is written and no task is started when a check fails.
3. **One transaction, one task.** The config, name, parameters, version and driver binding
   are written together and one `UPGRADE_INSTANCE` task reconciles them. The deployed services
   are recreated before the instance is generated, so the instance context carries the target
   version's services and the renamed ones.
4. **`apply` sends one `updateDeploymentVersion` per existing deployment**, with the manifest's
   config and parameters as `input`. It still sends it when the version is unchanged: the
   backend re-resolves the driver version and returns `null` on a no-op (`action="unchanged"`).

## Consequences

- A manifest valid for the version it declares is accepted in one apply; component config the
  declared version cannot apply is rejected, whatever version the deployment was on before.
- A rejected apply leaves the deployment unchanged. The partial state ADR-048 had to report
  ("config/parameters were updated; version upgrade failed") no longer occurs.
- The double reconcile ADR-048 accepted is gone: one task per apply.
- `updateDeployment` is unchanged and still validates against the pinned version; it never
  switches versions.
- `apply` no longer calls `updateDeployment`. A client that wants the old two-step behaviour
  can still call both mutations.
- An upgrade that adds a service now carries it in the upgraded instance's context. Before,
  the services were recreated after the instance was generated, so the context lagged one
  reconcile behind.

## Alternatives Considered

- **A validation-only `targetVersion` argument on `updateDeployment`.** Rejected: two
  mutations and two reconciles remain, the first reconcile runs the old version with config
  meant for the new one, and a failed version switch leaves that config stored.
- **Send the version first, then the config.** Rejected for the reason in ADR-048: the upgrade
  reconciles against the stale config, and a rejected config leaves the deployment upgraded
  without it.
- **A server-side `apply` mutation.** Rejected for the reasons in ADR-048. Extending the
  existing version mutation adds no new endpoint, batch semantics or rollback story.
