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

- Full replacement: a service that is not in the list has no override after the write. `null` or an omitted `services` clears every override when the write carries at least one other config field, because the whole stored config is replaced; a write with no config field at all keeps the stored config (research D-009). Sending the list without the service is how an operator clears one override (user story 1, scenario 2).
- A row with both `ingressClass` and `fqdnSuffix` null is treated as no override.

## GraphQL output

On `Deployment` (`Deployment.config` is untyped JSON, so the typed output has no other home): `serviceIngressOverrides: [ServiceIngressOverride!]!` with `name`, `ingressClass`, `fqdnSuffix`, sorted by service name. The stored block is also in `Deployment.config["services"]`, which the CLI reads. The final names are in `schema.graphql` (T028).

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
| `SERVICE_INGRESS_NOT_BUILT` (FR-009) | The override names a service that Styrmin builds no Ingress for: a service that is not `scope: external`, or an external service of kind `tcp` or `udp`. The message names the service and says Styrmin does not build its Ingress. | `service_name`, `scope`, `kind`, `checked_against` |
| `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` (FR-010) | A driver version change removes the service, makes it internal, or makes its kind `tcp` or `udp` while an override is stored. Raised before any pod changes. | `service_name`, `current_version`, `target_version`, `reason` (`removed`, `internal` or `not_http_or_https`), and `target_kind` when the reason is `not_http_or_https` |

All three are `ServiceError` subclasses with `extensions.code`, like `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`.

## Manifest (`styrminctl deployments apply`)

A list in `spec.config`, one row for each service, as `components` is (verified in T003, see [research.md](../research.md) D-009):

```yaml
spec:
  config:
    services:
      - name: task-manager
        ingress_class: tailscale
        fqdn_suffix: tailnet.example.ts.net
```

- `apply` writes the config together with the version (ADR-065), so the validation order of FR-010 applies to `apply` too.
- The SDK manifest model needs no hand-written change: `spec.config` is a free-form dict, validated against the generated `UpdateDeploymentInput` and `DeploymentConfigInput`. The `services` field appears in them after `uv run invoke generate`. Before that, the generated models ignore a `services` key without an error.
- A manifest whose `spec.config` has at least one key and no `services` clears the overrides, as it clears `components` overrides (full replacement of the stored config). A manifest with an empty or absent `spec.config` keeps the stored config, overrides included.
- A key that is not `name`, `ingress_class` or `fqdn_suffix` in a row is ignored by the generated SDK models, because they do not forbid extra fields. The separate bug, where `apply` ignores unknown component keys, is out of scope ([#598](https://github.com/opsmill/styrmin/issues/598)); the new block must not be dropped by it, and a test applies a manifest and reads the override back. The server stores the typed block with `extra="forbid"`, so an unknown key that reaches it is an error.
- `DeploymentResource.scale` sent only `components` and the update replaces the whole config, so it cleared a stored `services` block (reproduced in T030a). It now resends the stored `services`. It still clears every other config key that is not `components` (for example `ip_whitelist`, `env_vars`): not changed by this feature.

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
