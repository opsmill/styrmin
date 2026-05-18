# ADR-037: Environment capabilities computed independently from cluster

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-cluster-env-capabilities/research.md (R5)

## Context

Both `Cluster` and `Environment` carry a `capabilities` JSON column (see [[adr-035-capabilities-as-extensible-json-column]]). Environments live inside clusters and share several config knobs (storage class, ingress, fqdn_suffix). The naive approach would be: compute cluster capabilities once, then derive environment capabilities by copying and filtering the cluster's view.

That would have two failure modes:

1. **Hidden coupling**: any change to `compute_cluster_capabilities()` would silently change every environment's capabilities, even environments whose own config never moved.
2. **Wrong semantics**: an environment doesn't inherit every storage class the cluster knows about — it has its own resolved view of what storage it uses, which can be narrower (or, with overrides, different).

## Decision

Environment capabilities are computed **directly from the environment's own configuration and relationships**, not by transforming cluster capabilities. `compute_environment_capabilities(environment)` reads `environment.config` (its own typed config dict) and `environment.backup_storage_location` (its own FK relationship) and emits the environment-scoped capability set.

This means:

- The cluster and environment computations share **utility helpers** (e.g., the rule for deriving ingress capability from `ingress_class` + `fqdn_suffix`) but not the **flow**.
- An environment with no overrides will *typically* yield the same capabilities as its cluster for shared categories, but that's a consequence of the same inputs producing the same outputs — not a structural inheritance.
- Environment-scoped categories (notably `backup.velero` via `BackupStorageLocation`) live only on environment capabilities, because the underlying relationship lives only on `Environment`.

## Consequences

- Cluster-side capability logic can evolve without an opaque blast radius into environment-side behaviour. A refactor of `compute_cluster_capabilities` is a refactor of `compute_cluster_capabilities` — environments stay where they are.
- The "what does this environment actually offer?" question is answered by reading the environment's row, not by joining to the cluster and filtering. The UI and driver templates get the same answer through the same field.
- Some derivation rules (e.g., the ingress `ingress_class + fqdn_suffix → ingress.external` rule) are implemented twice — once in `compute_cluster_capabilities`, once in `compute_environment_capabilities`. This is intentional duplication: the rule is a one-liner, and the cost of factoring it out (an extra layer of indirection) outweighs the saved keystrokes. If the rule grows non-trivial, extract a shared helper — not a shared flow.
- Adding a category that exists only on the cluster level (or only on the environment level) requires updating only the relevant `compute_*` function, never both.

## Alternatives Considered

- **Copy cluster capabilities and filter**: rejected. Creates coupling that wasn't there before: a cluster-side change becomes an environment-side change without any environment-level signal. Also misrepresents the semantics — environments are not "subsets of clusters", they are entities with their own resolved configuration.
- **Compute cluster capabilities only, derive environment view on read**: rejected for the same persistence-correctness reason as [[adr-036-capabilities-recalculation-in-service-layer]]: we already decided capabilities are persisted, not computed-on-read. A hybrid "persist cluster, derive environment on read" splits the policy and creates exactly one new edge case where the derivation rule has to live (read path vs write path).
