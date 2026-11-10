# Contract: GraphQL, manifest and template data

**Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

Names are the plan's proposal. The final names follow the existing GraphQL naming in `backend/styrmin_backend/api/definitions/`, and `schema.graphql` is the authority after regeneration.

## GraphQL input

New input type, used on `deploy`, `updateDeployment` and `updateDeploymentVersion(input:)` through `DeploymentConfigInput`, as `components` is:

```graphql
input ServiceConfigInput {
  "Driver service name. Must be declared by the driver version the deployment is bound to after the write, with scope external."
  name: String!
  "Ingress class for this service only. Null or omitted: the resolved class applies."
  ingressClass: String
  "FQDN suffix for this service only. Null or omitted: the resolved suffix applies."
  fqdnSuffix: String
}

input DeploymentConfigInput {
  # existing fields unchanged
  services: [ServiceConfigInput!]
}
```

Semantics, as for `components`:

- Full replacement: a service that is not in the list has no override after the write. `null` or an omitted `services` clears every override. This is how an operator clears one (user story 1, scenario 2).
- A row with both `ingressClass` and `fqdnSuffix` null is treated as no override.

## GraphQL output

On the deployment config type (read back by the UI and the CLI): `services: [ServiceConfig!]` with `name`, `ingressClass`, `fqdnSuffix`.

On `DeployedService` (read by the Networking summary), new fields:

| Field | Type | Meaning |
|---|---|---|
| `ingressClass` | `String` | Effective ingress class. Null for a service that is not external. |
| `ingressClassOverridden` | `Boolean!` | `true` when the value comes from the override. |
| `fqdnSuffixOverridden` | `Boolean!` | `true` when the suffix of `humanReadableFqdn` comes from the override. |

`humanReadableFqdn` and `humanReadableUrl` (existing) use the override suffix when one is set (FR-006). `primaryFqdn` is unchanged (research D-003).

## Typed errors

| Code | When | Metadata |
|---|---|---|
| `UNKNOWN_SERVICE_INGRESS_OVERRIDE` | The override names a service that the target driver version does not declare. | `service_name`, `known_services`, `checked_against` |
| `SERVICE_INGRESS_NOT_BUILT` (FR-009) | The override names a service that is not `scope: external`. The message names the service and says Styrmin does not build its Ingress. | `service_name`, `scope`, `checked_against` |
| `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` (FR-010) | A driver version change removes the service or makes it internal while an override is stored. Raised before any pod changes. | `service_name`, `current_version`, `target_version`, `reason` (`removed` or `internal`) |

All three are `ServiceError` subclasses with `extensions.code`, like `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`.

## Manifest (`styrminctl deployments apply`)

A block in `spec.config`, keyed by driver service name:

```yaml
spec:
  config:
    services:
      task-manager:
        ingress_class: tailscale
        fqdn_suffix: tailnet.example.ts.net
```

- `apply` writes the config together with the version (ADR-065), so the validation order of FR-010 applies to `apply` too.
- A manifest without `services` clears the overrides, as it clears `components` overrides (full replacement). To be confirmed against the apply code in the first task.
- A key that is not `ingress_class` or `fqdn_suffix` under a service is an error, not ignored (the `extra="forbid"` of the model). The separate bug, where `apply` ignores unknown component keys, is out of scope ([#598](https://github.com/opsmill/styrmin/issues/598)); the new block must not be dropped by it, and a test applies a manifest and reads the override back.

## Driver template data

Available in `values.j2.yml` as `services.<driver service name>`:

| Key | Existing | Meaning |
|---|---|---|
| `host`, `port`, `kind`, `url` | yes | unchanged |
| `primary_fqdn` | yes | Application address, unchanged |
| `human_readable_fqdn` | yes | Uses the override suffix when set |
| `ingress_class` | new | Effective ingress class |
| `overridden` | new | `true` when the service has an override |

A driver that does not read the new keys is not affected.

## Driver format

`scope: external` on a service in `spec.services` now means: Styrmin builds one Ingress for it. A driver that declares `external` must not render an Ingress for that service (FR-014). No new driver key.
