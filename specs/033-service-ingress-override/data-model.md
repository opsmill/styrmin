# Data Model: Service ingress override

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

There is no database change: no new table, no new column, no Alembic revision (research D-004). Everything below is the shape of the deployment's JSON config, of the template data and of the cluster objects.

## Stored: `DeploymentConfig.services`

```text
Deployment.config
└── services: dict[driver service name -> ServiceConfigBlock] | null
```

**ServiceConfigBlock** (`context/models/config.py`, `extra="forbid"`)

| Field | Type | Meaning |
|---|---|---|
| `ingress_class` | `str \| None` | Ingress class of this service. `None` means: use the resolved class. |
| `fqdn_suffix` | `str \| None` | FQDN suffix of this service. `None` means: use the resolved suffix. |

Rules:

- The key is the driver service name. It is not the resolved name, because a service name override changes the resolved name.
- A block with both fields `None` is not stored. Sending it is the same as clearing the override.
- `ingress_class` is a non-empty string. An empty string is rejected, because `""` already means "no class" in the cluster-level setting, and an override must name a class. Open point for the critique: whether an operator may want an empty class on one service.
- `fqdn_suffix` is a DNS name without a leading dot. The exact rule reuses the validation that the cluster and environment `fqdn_suffix` have today (to read in the first task).
- A config stored before this change has no `services` key and reads as `None`.
- A model serializer leaves `services` out of a dump when it is `None`, so the stored config of every existing deployment is unchanged, and the no-op check of a deployment update does not see a difference (same rule as `replicas` in ADR-070).

## Validation state transitions

| Event | Condition | Result |
|---|---|---|
| Set or change an override | Service not declared by the target driver version | `UNKNOWN_SERVICE_INGRESS_OVERRIDE` |
| Set or change an override | Service declared with `scope: internal` | `SERVICE_INGRESS_NOT_BUILT` |
| Set or change an override | Service declared `external` | Stored |
| Clear an override | Always | Removed, even if the service no longer exists |
| Change the driver version | An override is stored for a service that the target version removes, or declares `internal` | `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`, before any pod changes |
| Change the driver version | Every stored override targets a service that stays `external` | Allowed |

## Derived: effective address of a service (template data and GraphQL)

Computed at runtime by one function in `context/fqdn.py` (ADR-022). Nothing is persisted.

| Output | Without an override | With an override |
|---|---|---|
| `ingress_class` | Resolved class (deployment, else environment, else cluster) | Override class, else the resolved class |
| suffix used | Resolved `fqdn_suffix` | Override suffix, else the resolved suffix |
| `human_readable_fqdn` | `<resolved service name>-<environment name>.<resolved suffix>` | `<resolved service name>-<environment name>.<override suffix>` |
| `primary_fqdn` | `<app name>-<deployment id>.<resolved suffix>` | Unchanged (research D-003) |
| `overridden` | `false` | `true` when the service has a block with at least one field set |

`ServiceReference` (`context/models/services.py`) gains `ingress_class: str | None` and `overridden: bool`, both with defaults, so a driver template that does not read them is not affected.

`deployed_services` entries of the context gain `scope: str` and the effective `ingress_class` and suffix, so the Ingress builder reads one source.

## Derived: the Ingress that Styrmin builds

One Ingress for each service of the deployment that is `scope: external`, of `kind` `http` or `https` (research D-006).

| Part | Value |
|---|---|
| Namespace | The namespace of the deployment |
| Name | `styrmin-svc-<deployed service id>` (research D-005) |
| Labels | `app.kubernetes.io/managed-by`, `styrmin.io/utility-kind: ingress`, `styrmin.io/release-reference`, `styrmin.io/service-id` |
| Backend | The ClusterIP Service named by the resolved name, on the declared port |
| Rules | One rule per host, path `/`, `pathType: Prefix` |
| Hosts | The readable host; the application address when this is the first declared service and it has no override |
| `spec.ingressClassName` | Resolved class; none in an environment with a dedicated ingress controller; the override class when overridden |
| Annotations (no override) | Entry points, external-dns hostname, Cloudflare proxied, allow-list middleware when `ip_whitelist` is set, endpoints-type when set, `kubernetes.io/ingress.class` |
| Annotations (override) | `kubernetes.io/ingress.class` only |
| `spec.tls` | Never written (FR-007) |

Lifecycle: created, updated and deleted with the deployment's other utility resources. The operator restores it after drift and deletes it when the desired set no longer contains it.

## Entities from the spec

| Spec entity | Where it lives |
|---|---|
| Service | `ServiceDefinition` in the driver version, `DeployedService` row per deployment (existing, has `scope`) |
| Service ingress override | `Deployment.config["services"][<driver service name>]` |
| Ingress class, FQDN suffix | `ResolvedConfig` (existing) |
| Service name override | `DeployedService.resolved_name` (existing, unchanged) |
| Dedicated ingress controller | `ClusterConfig.dedicated_ingress` (existing) |
