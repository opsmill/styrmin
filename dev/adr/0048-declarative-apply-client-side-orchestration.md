# ADR-048: Declarative apply is orchestrated client-side in the SDK

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/009-deployments-apply/research.md (D1, D8, and the D2 race follow-up)
**Related**: [ADR-049](0049-styrmin-v1-manifest-contract.md) (the manifest contract this
orchestrates), [ADR-050](0050-composite-natural-key-deployment-lookup.md) (the lookup
that makes the upsert possible), [ADR-054](0054-backend-authoritative-noop-detection.md)
(what makes a re-apply idempotent), [ADR-037](0037-sdk-typed-bindings-outer-wrapper-and-facade.md)
(the SDK layering this sits on).

## Context

`styrminctl deployments apply -f <path>` has to take a set of declarative
manifests and converge each one: create the deployment if it does not exist,
update it if it does, keep going when one manifest fails, and report a
per-manifest summary at the end.

The platform already exposed three separate write mutations for the pieces —
`deploy`, `updateDeployment`, and `updateDeploymentVersion`. The design question
was where the create-or-update decision, the batch semantics, and the override
resolution should live: behind a new server-side `apply` mutation, or in the
client.

## Decision

**The upsert is orchestrated client-side, in `DeploymentResource.apply()` /
`apply_files()` in the SDK, composed out of the existing mutations. No
server-side `apply` mutation exists.**

`apply()` per manifest:

1. Resolve `(environment, cluster)` to a unique `environment_id`, raising
   `EnvironmentAmbiguityError` when the environment name collides across
   clusters and no cluster was supplied.
2. Look up an existing non-internal deployment by `(name, environment_id)`
   (see [ADR-050](0050-composite-natural-key-deployment-lookup.md)).
3. **Absent** → dispatch `deploy()`, return `action="created"`.
4. **Present** → verify the manifest's driver matches the deployment's
   (`DriverMismatchError` otherwise — driver changes are not in-place
   upgrades), then dispatch `updateDeployment` for config/parameters and, only
   if the version differs, `updateDeploymentVersion`.

**Config before version, sequentially — never in parallel.** Running the
version upgrade first would let the new version reconcile briefly against the
old config; running both concurrently would race two writers against the same
`Deployment` row.

**The non-atomic lookup is handled by one retry, not a lock.** Two concurrent
`apply` runs against the same `(name, environment)` can both observe "not
found" and both call `deploy()`; the database's unique constraint rejects the
loser. `apply()` catches `ResourceAlreadyExistsError` exactly once, re-runs the
lookup, and pivots to the update path. Anything else propagates verbatim.

Batch concerns — continue-on-error, the per-manifest result line, the
`created / updated / failed` summary, the non-zero exit on any failure — live
entirely in the SDK and CLI. `apply_files()` is the entry point for non-CLI
consumers, so the YAML parsing lives in the SDK rather than the CLI.

## Consequences

- **No new server write surface, no new transaction semantics.** The three
  existing mutations keep their contracts and their validation; `apply` adds no
  compound endpoint whose partial-failure rollback would have to be defined.
- **Idempotence is the backend's job, not the client's.** Re-applying an
  unchanged manifest is a no-op because `updateDeployment` returns `null` when
  the regenerated instance resolves to the current one
  ([ADR-054](0054-backend-authoritative-noop-detection.md)) — the client does
  not diff anything to decide whether to call.
- **Every SDK consumer gets apply for free.** Other CLIs, scripts, and future
  agents call `apply_files()` rather than re-implementing upsert.
- **Orchestration is testable without a backend.** The create/update branch,
  the driver-mismatch guard, and the race retry are unit-testable against a
  stubbed transport.
- **The double reconcile when both config and version change is accepted.**
  Two mutations means two reconciles; collapsing them would need the compound
  mutation this ADR declines to add. Recorded as a known cost, not a defect.
- **Batch atomicity is explicitly not offered.** A batch is N independent
  upserts. There is no "all or nothing" mode, and a mid-batch failure leaves
  earlier manifests applied.

## Alternatives Considered

- **A server-side `apply` mutation.** Rejected: duplicates validation that
  already exists on three mutations, needs its own rollback story for partial
  failures, and pulls batch-level concerns (continue-on-error, summary counts,
  override precedence) into a transaction-bearing resolver where they do not
  belong.
- **CLI does the orchestration directly, no SDK method.** Rejected: any other
  SDK consumer would have to re-implement the same upsert, and the YAML/manifest
  handling would be unreachable outside the CLI process.
- **Version upgrade before config update.** Rejected: the new version briefly
  reconciles against the stale config.
- **A lock or advisory transaction around lookup-then-create.** Rejected as
  disproportionate: the unique constraint already makes the race safe, and one
  re-lookup turns a correct-but-ugly error into the right outcome.
