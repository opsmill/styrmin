# ADR-034: Affinity-by-deployment-reference resolves to `styrmin/deployment_id` pod label

**Status**: Accepted — amended 2026-10-16 (#492): a rename of a deployment writes its new name into the affinity rules that name it
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

Amended 2026-10-16 ([#492](https://github.com/opsmill/styrmin/issues/492)): a `deployment_ref`
can also name its target by `deployment_name`. Styrmin stores the name as written and looks it up
in the environment on every reconcile. A rename left the old name in the rules, so the next
reconcile of a deployment with such a rule raised `UnresolvableAffinityReferenceError`. When a
rule of the environment or of the renamed deployment named it, `updateDeployment` saved the new
name and then returned that error.

A rename through `updateDeployment` or `updateDeploymentVersion` now replaces the old name with
the new one in the `pod_affinity` and `pod_anti_affinity` rules of the environment and of every
deployment in it, in the same transaction as the rename (`services/scheduling/references.py`).
The other deployments get a write of their `config` column only, so the rename does not overwrite
their status or active instance. The rendered rules do not change, because they select the
deployment's id.

Two other options were considered:

- Store the deployment's id when a rule is saved with a name. An environment clone copies the
  configs of the source deployments unchanged (`workflows/templates/clone.py`), so a stored id
  would name a deployment of the source environment, and the clone's rules could not be resolved.
  A name resolves to the clone's own deployment.
- Refuse a rename while a rule names the deployment. The rules would not break, but the user would
  have to edit each rule before the rename.

## Consequences

- Affinity-by-deployment-reference is expressible without inventing a new identity label or coupling to driver-internal labels. The platform's existing identity is the API.
- The label set on every platform-managed pod becomes a stable, documented, cross-driver primitive: `(styrmin/environment_id, styrmin/deployment_id)` together identify any workload pod the platform manages. Future scheduling primitives (e.g., "spread across deployments within an environment") can build on the same labels.
- `TemplateLabelPatch` continues to be the single application point — there is no second labelling pipeline to keep in sync.
- Cross-namespace affinity (referencing a deployment in a different environment) is **not** supported in v1; rules operate within the referencing deployment's environment by default. `podAffinityTerm.namespaceSelector` remains available in the raw-`labelSelector` escape hatch for future cross-namespace cases.
- The labels are observable to operators inspecting cluster state, which is itself useful for incident response (`kubectl get pods -l styrmin/deployment_id=<uuid>`).
- An environment restore sets the environment's config back to the config in the backup (`services/backup/environment.py`). When a deployment was renamed after the backup, a rule of the restored config that names it still has the old name and cannot be resolved (#492).

## Alternatives Considered

- **Introduce a new `styrmin.io/app` identifier label**: explicitly rejected by the spec clarification. The platform's existing identity (deployment UUID) is the right reference for cross-deployment rules; inventing a parallel identifier creates two truths.
- **Use the driver's component-identifier label** (`infrahub/service`, etc.): rejected. These labels are driver-owned, vary between drivers, and cannot be used to target "another deployment's pods" across drivers. They also don't survive when an operator switches drivers for a deployment.
- **Use `podAffinityTerm.namespaceSelector` as the primary cross-deployment mechanism**: rejected for v1. Cross-namespace affinity is not in the v1 scope; same-environment targeting (where namespaces match) is the dominant case.
