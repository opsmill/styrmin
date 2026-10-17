# ADR-034: Affinity-by-deployment-reference resolves to `styrmin/deployment_id` pod label

**Status**: Accepted — amended 2026-10-16 (#508): a stored deployment reference gives the deployment's id, so a reconcile looks up no name ([ADR-075](0075-deployment-references-stored-by-id.md))
**Date**: 2026-05-17
**Source**: specs/archive/001-pod-scheduling-config/research.md (Decision 6)

## Context

Operators want to express affinity rules like "schedule this deployment's pods near pods of *that other deployment*" using the platform's own identity for the target — not by knowing the target's driver-specific labels. For example, "co-locate the API tier of `ansible` with the database tier of `ansible-db`", referenced by deployment platform-id, not by `infrahub/service: api` or whatever driver-internal label exists.

The pod-template post-renderer already stamps a `styrmin/environment_id: <uuid>` label onto every pod-template-bearing resource it manages, via the `TemplateLabelPatch` pipeline (`agent/service/kubernetes/resources/blocks/patches.py`). Pod labels are the right primitive — they are exactly what `podAffinityTerm.labelSelector` looks at — but environment-scoped is too coarse for cross-deployment rules.

The original design considered introducing a `styrmin.io/app` label as a new platform identifier. The spec clarification (Q5) explicitly rejected this — the platform should not invent new identity labels when its existing identity (`deployment_id`) is sufficient. Driver-owned labels like `infrahub/service` vary between drivers and aren't usable for cross-driver targeting.

## Decision

Add `deployment_id` to the existing `context.labels` mapping in `services/context.py`. The existing `TemplateLabelPatch` pipeline picks up every key in that mapping and stamps it onto every pod-template-bearing resource, so the change costs one line in context generation and zero changes in the patch builder.

Effective per-pod labels (managed by the platform, on every workload pod):

| Label | Source | Use |
|-------|--------|-----|
| `styrmin/environment_id` | Existing | Environment-scoped affinity targets |
| `styrmin/deployment_id` | **New** | Deployment-scoped affinity targets (this ADR) |

Scheduling rules that reference a deployment by platform-id are expanded at resolve time into a `labelSelector: { matchLabels: { styrmin/deployment_id: <target-uuid> } }`. The expansion happens for the **referencing** deployment's namespace/environment by default (matching FR-001d's visibility rule). Raw `labelSelector`-based affinity rules remain supported as the escape hatch for targeting pods the platform did not render (driver-owned pods that arrived through some other path).

The reference is re-expanded on every reconcile, so a target deployment's UUID is always current — no stale selectors.

Amended 2026-10-16 ([#508](https://github.com/opsmill/styrmin/issues/508)): a reference that gave a name was stored as written and looked up again at every reconcile, so a rename of the named deployment made the term fail ([#492](https://github.com/opsmill/styrmin/issues/492)). Every write that stores a config now replaces a name with the id of the named deployment, and a reconcile resolves ids only. A reference to a tombstoned deployment is refused instead of giving a selector that matches no pod. See [ADR-075](0075-deployment-references-stored-by-id.md).

## Consequences

- Affinity-by-deployment-reference is expressible without inventing a new identity label or coupling to driver-internal labels. The platform's existing identity is the API.
- The label set on every platform-managed pod becomes a stable, documented, cross-driver primitive: `(styrmin/environment_id, styrmin/deployment_id)` together identify any workload pod the platform manages. Future scheduling primitives (e.g., "spread across deployments within an environment") can build on the same labels.
- `TemplateLabelPatch` continues to be the single application point — there is no second labelling pipeline to keep in sync.
- Cross-namespace affinity (referencing a deployment in a different environment) is **not** supported in v1; rules operate within the referencing deployment's environment by default. `podAffinityTerm.namespaceSelector` remains available in the raw-`labelSelector` escape hatch for future cross-namespace cases.
- The labels are observable to operators inspecting cluster state, which is itself useful for incident response (`kubectl get pods -l styrmin/deployment_id=<uuid>`).

## Alternatives Considered

- **Introduce a new `styrmin.io/app` identifier label**: explicitly rejected by the spec clarification. The platform's existing identity (deployment UUID) is the right reference for cross-deployment rules; inventing a parallel identifier creates two truths.
- **Use the driver's component-identifier label** (`infrahub/service`, etc.): rejected. These labels are driver-owned, vary between drivers, and cannot be used to target "another deployment's pods" across drivers. They also don't survive when an operator switches drivers for a deployment.
- **Use `podAffinityTerm.namespaceSelector` as the primary cross-deployment mechanism**: rejected for v1. Cross-namespace affinity is not in the v1 scope; same-environment targeting (where namespaces match) is the dominant case.
