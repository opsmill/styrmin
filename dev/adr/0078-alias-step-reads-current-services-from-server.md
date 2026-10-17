# ADR-078: The Alias Step Reads the Other Deployments' Services From the Server When It Runs

**Status**: Accepted
**Date**: 2026-10-17
**Decision-makers**: Fatih Acar
**Source**: specs/archive/026-delete-service-aliases/research.md (R-012, R-005 note);
[issue #503](https://github.com/opsmill/styrmin/issues/503); [PR #516](https://github.com/opsmill/styrmin/pull/516),
CI run [39030125607](https://github.com/opsmill/styrmin/actions/runs/39030125607)
**Related**: [ADR-077](0077-alias-flow-reads-deletion-state-at-write-time.md) (the alias flow skips
a missing namespace), [ADR-059](0059-driver-action-api-tokens.md) (action tokens of flows)

## Context

The alias flow no longer creates a namespace: it skips the aliases written into or pointing into a
namespace that does not exist (ADR-077). That assumed that a missing namespace belongs to a
deployment whose own flow writes both sets of aliases later, its peers' into its namespace and its
own into theirs.

That holds only when the other deployment's flow knows about the deployment that skipped. The
server builds a flow's context in `apply_state` when the change is requested. A deployment's
`DeployedService` rows exist from its request on, so a context lists every deployment requested
before it and none requested after it. When B is requested just after A, only B's context lists
A. When B's alias step runs before A's flow has created A's namespace, B skips the aliases between
the two, and A's flow, with its context alone, never writes them. CI run 39030125607 of PR #516
failed the three tests of `test_service_discovery.py` in this way.

## Decision drivers

- Of two deployments requested one after the other, both sets of aliases between them get written.
- The flow never creates another deployment's namespace (ADR-077).
- What driver templates see does not change.
- No GraphQL schema change.

## Considered options

1. Before it computes the aliases, the alias step reads the environment's services from the
   server, and takes the other deployments' services from that list.
2. Wait up to 60 seconds for a missing namespace (commit `c4fd1534`).
3. Count a missing namespace as not departing.
4. Create the missing namespace, as before #503.

## Decision

We chose option 1. Before it computes the aliases and the stale aliases, `_apply_service_aliases_step`
calls `with_current_peer_services` (`agent/tasks/service_aliases.py`):

- It reads the services of the environment with the `environmentServices` query
  (`read_environment_services` in `agent/tasks/environment_services.py`), sent with the flow's
  action token. The environment id comes from the context's `labels.environment_id`.
- It replaces the other deployments' entries of `deployed_services` with the server's list, and
  keeps the deployment's own entries as the context lists them, because those are the Services
  that this flow deploys.
- When the token is missing, the context names no environment, or the read fails, it logs a
  warning and uses the context's list.

Each flow creates its own namespace before its alias step. Of two alias steps, the one that runs
last finds both namespaces and, with the server's list, knows both deployments, so it writes both
sets.

The context that driver templates render with does not change: only the alias step reads the
server's list.

Option 2 covers the CI case only when the peer's flow creates its namespace within the wait, not a
peer with a long setup pre-hook or a queued flow, and it adds the full wait to each flow whose
context lists a deployment whose namespace was deleted. Option 3 writes only one direction of the
pair, and a flow whose context was built before a peer reached `DELETED` would write that peer's
aliases again after its namespace is gone, which is the defect of #503. Option 4 brings the
namespace of a deleted deployment back.

## Consequences

- Good, because the alias step that runs last writes the aliases between two deployments requested
  one after the other, without a wait.
- Good, because the server's list no longer holds a deployment that reached `DELETED`, so the step
  no longer computes aliases for it. A `DELETING` deployment is still listed, and the cluster read
  of ADR-077 skips it.
- Bad, because the alias step now depends on the GraphQL API. When the server cannot be read, the
  step falls back to the context's list, and the case of two deployments requested one after the
  other can again lose the aliases between them.
- Bad, because a deployment created or changed while a peer is being restored skips the aliases
  between the two: the restored deployment's namespace is terminating or missing, and no flow runs
  when the restore ends. The two cannot reach each other by short name until a later change of
  either deployment runs a create, update or upgrade flow. The maintainer chose to document this
  case and its recovery instead of changing the code.

## Confirmation

- `backend/tests/unit/agent/test_service_aliases.py`: `test_adds_a_peer_requested_after_the_context`
  and `test_drops_a_peer_that_the_server_no_longer_lists`.
- `backend/tests/unit/agent/test_environment_services.py` covers the read and its errors.
- The E2E tests of `backend/tests/e2e/test_service_discovery.py` create two deployments one after
  the other and check the aliases in both namespaces.

## More information

The user documentation of restores,
[Backups and restores](../../docs/docs/concepts-and-architecture/backups-and-restores.md#what-happens-when-you-restore),
describes the restore case and its recovery.
