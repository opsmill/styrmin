# ADR-050: Composite natural-key lookup on `deployment(name, environmentId)`

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/009-deployments-apply/research.md (D2), data-model.md
**Related**: [ADR-031](0031-dual-identifier-resolution-service-layer.md) — this is a
deliberate departure from that pattern; read both together.
[ADR-048](0048-declarative-apply-client-side-orchestration.md) is the consumer.

## Context

Client-side declarative apply
([ADR-048](0048-declarative-apply-client-side-orchestration.md)) needs to ask
"does a deployment named X exist in environment Y?" before deciding to create or
update. Nothing in the schema answered that: `deployment(deploymentId: UUID!)`
keyed on a surrogate ID the client does not have.

[ADR-031](0031-dual-identifier-resolution-service-layer.md) already established
the house pattern for name-based access: expose an optional
`<resource>Id` / `<resource>Name` pair, and have a service-layer
`resolve_<resource>` helper validate mutual exclusivity. That pattern assumes a
resource whose name is *globally* unique or scoped by one parent identifier.

A deployment's natural key is neither — it is the **composite**
`(name, environment_id)`, backed by the partial unique index from
[ADR-011](0011-scoped-tombstone-aware-name-uniqueness.md). `deploymentName`
alone is not a resolvable identifier, so ADR-031's single-name-argument shape
does not apply cleanly.

## Decision

**Extend the existing `deployment` query with a second, composite argument shape
rather than adding a sibling field.** The signature is:

```graphql
deployment(deploymentId: UUID = null, name: String = null, environmentId: UUID = null): Deployment
```

Two argument shapes, never mixed:

- `deployment(deploymentId:)` — existing behaviour, unchanged.
- `deployment(name:, environmentId:)` — the new natural-key lookup.

Because Strawberry cannot express "exactly one of these argument groups", all
three arguments are optional with a **runtime guard in the resolver**: exactly
one of `(deploymentId)` or `(name AND environmentId)` must be supplied, else a
`ServiceError` naming both valid shapes.

`get_deployment_by_name(name, environment_id, uow)` in
`services/deployment.py` owns the lookup, keeping the resolver thin — the
service-layer-owns-resolution half of ADR-031 is preserved even though the
argument shape differs.

**Not-found returns `null`, it does not raise**, matching the existing
`deployment(deploymentId)` convention. Apply's "if found → update, else →
create" branch depends on this.

**The internal-deployment guard is reused**: a lookup that lands on an
`internal=True` deployment returns `null` through either shape, so the new
argument shape cannot be used to enumerate platform-internal deployments.

### How this relates to ADR-031

ADR-031 remains the default for name-based access. This ADR is the carve-out for
resources whose natural key is composite:

| | ADR-031 | This ADR |
|---|---|---|
| Key shape | single name, optionally scoped | composite `(name, parentId)` |
| Argument shape | `<resource>Id?` / `<resource>Name?` pair | `<resource>Id?` / `(name?, parentId?)` groups |
| Mutual exclusivity | service-layer `resolve_<resource>` helper | resolver-level argument-group guard |
| Not found | `null` | `null` |
| Resolution owner | service layer | service layer |

A future resource with a composite natural key should copy this shape; one with
a single resolvable name should copy ADR-031.

## Consequences

- **Existing call sites are untouched.** Every caller passing only
  `deploymentId` keeps working; the field's return type is unchanged.
- **The unique constraint is doing the work.** `(name, environment_id)` is
  already unique per [ADR-011](0011-scoped-tombstone-aware-name-uniqueness.md),
  so the lookup is one indexed read with no ambiguity to resolve.
- **The "exactly one shape" rule is a runtime error, not a schema error.**
  Because all three arguments are nullable, a malformed call (all three, or
  `name` without `environmentId`) type-checks and fails at execution. This is
  the cost of expressing argument groups in a schema language that has no
  union-of-arguments construct; the guard's error message has to carry the whole
  contract.
- **It sets a precedent that needs bounding.** Overloading one field with more
  than two argument groups would become unreadable. Two is the limit; a third
  access pattern gets its own field.
- **Tombstoned and internal deployments stay invisible** through the new shape,
  so apply cannot resurrect or collide with either.

## Alternatives Considered

- **A sibling field (`deploymentByName`) or a `lookupDeployment` query.**
  Rejected: GraphQL convention is one well-named field per resource lookup, and
  a second field means two resolvers, two internal-guard implementations, and
  two places to keep in sync.
- **Follow ADR-031 literally with a `deploymentName` argument.** Rejected:
  `deploymentName` is not a resolvable identifier on its own — the environment
  is mandatory, not an optional disambiguator, so the pattern would mislead.
- **Make `deploymentId` optional on the existing query and infer intent.**
  Rejected as exactly what we did, but *without* the explicit guard — inference
  from which arguments happen to be present is how you get a lookup that
  silently ignores `name` when an ID is also supplied.
- **List all deployments in the environment and filter client-side.** Rejected:
  fetches every deployment for a single lookup, and pagination later turns it
  into a correctness bug.
