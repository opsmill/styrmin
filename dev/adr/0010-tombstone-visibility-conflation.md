# ADR-010: Tombstoned-record visibility — NOT_FOUND conflation + opt-in `includeDeleted` filter

**Status**: Accepted
**Date**: 2026-05-02
**Source**: specs/archive/008-deployment-deletion/research.md (R5, R6)

## Context

Soft-deleted (tombstoned) deployment rows live in the same table as active ones. The GraphQL surface has to make two policy decisions:

1. **Write-side**: what should `deleteDeployment(id)` return when the caller asks to delete a deployment that's already tombstoned, vs an id that never existed? Automation cares about whether to retry, surface the error, or silently treat it as success.
2. **Read-side**: what does the default deployment list return — only active rows, or all rows? Tombstoned rows would clutter day-to-day views, but operators need a way to find retired deployments for forensics.

Inconsistent answers across destructive mutations (some return distinct error codes, some don't; some include tombstones in default lists, some don't) would force every client to special-case each call.

## Decision

Establish two paired conventions for the deployment-deletion API surface, and treat them as the project pattern for any future soft-deleted resource:

**Write-side (NOT_FOUND conflation)**: A `deleteDeployment(id)` call against an already-tombstoned deployment surfaces `ResourceNotFoundError` with `extensions.code = "NOT_FOUND"` — the same code returned for an unknown id. Clients should treat both as "this id refers to nothing the platform can act on" and continue without retry. Distinguishing the two cases is intentionally NOT supported; if a caller cares about the distinction, that's a hint they should be reading `Deployment.deletedAt` directly rather than driving from the mutation's error.

**Read-side (opt-in `includeDeleted` filter)**:

- `Environment.deployments(includeDeleted: Boolean = false)`: default `false`, applies `WHERE deleted_at IS NULL`. `DELETING` rows have `deleted_at IS NULL` until terminal, so they remain visible during teardown.
- `deployment(id)` (single-record lookup): unfiltered with respect to `deleted_at`. Direct id navigation always works — tombstoned detail pages remain reachable forever.

These two patterns paired make the contract symmetric: lists hide tombstones unless asked; direct lookups always succeed; destructive writes against gone rows look identical to writes against unknown ids.

## Consequences

- **Easier**: scripts that delete-by-id can be a single try/except on `ResourceNotFoundError` regardless of the deployment's prior state. No state-machine inside the client.
- **Easier**: list resolvers stay clean — a single boolean argument toggles the filter, and the urql/relay cache key already includes the variable so toggling doesn't require swapping queries.
- **Easier**: detail-page routes stay stable forever. A bookmark from before a deployment was deleted still resolves; the page renders with a banner instead of a 404.
- **Harder**: clients that genuinely need the difference between "never existed" and "deleted" must read `Deployment.deletedAt` via a `deployment(id)` query instead of inferring from mutation errors. This is a deliberate API contract — the mutation is destructive-with-best-effort, not a state probe.
- **Convention to replicate**: any future soft-deleted resource should apply both halves (NOT_FOUND conflation + `includeDeleted` arg on list queries + unfiltered direct lookup) to keep the surface consistent.

## Alternatives Considered

- **Distinct error codes** (`ALREADY_DELETED` vs `NOT_FOUND`): Forces every client to handle two codes for what is operationally the same outcome ("nothing to do"). The PRD explicitly stated automation should be able to treat both identically.
- **Separate `listDeletedDeployments` query**: Would force the frontend toggle to swap queries (and break the urql cache reuse). The argument-on-existing-query approach is simpler and easier to extend.
- **Default `includeDeleted: true`**: Would clutter day-to-day views with retired records. Rejected as the wrong default for the common case.
- **`deployment(id)` filtered by default**: Would 404 a tombstoned deployment's bookmarked URL — exactly the forensic interface the spec required to keep alive.
