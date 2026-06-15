# ADR-002: Shared Async Event Loop for Kopf Operator and Prefect Agent

**Status**: Accepted
**Date**: 2026-04-06
**Source**: specs/archive/001-k8s-operator/research.md (R1, R2)

## Context

The Styrmin agent needs to run both a kopf-based Kubernetes operator and a Prefect worker in a single container. The two components must coexist without blocking each other and shut down gracefully together. The question was whether to run them in separate threads with separate event loops, or share a single async event loop.

## Decision

Run both components in a shared asyncio event loop using `asyncio.gather(kopf.operator(...), run_prefect_worker())`.

kopf's `operator()` coroutine snapshots all existing asyncio tasks at startup via `aiotasks.all_tasks()` and adds them to an `ignored` set. During shutdown, `run_tasks()` only cancels tasks kopf itself created, leaving pre-existing tasks (like the Prefect worker) untouched. This makes shared-loop embedding safe.

The Prefect worker runs its internals (`get_and_submit_flow_runs`, `sync_with_backend`) as an anyio task group, racing against a shutdown event. kopf's `@kopf.on.cleanup()` handler signals the shared `asyncio.Event` to trigger Prefect worker termination.

## Consequences

- Single container, single process, single event loop simplifies deployment and resource overhead.
- Both components start and stop together — no orphaned processes.
- kopf registers SIGTERM/SIGINT handlers in `spawn_tasks()` when running in the main thread, which overwrites any previously registered signal handlers.
- Prefect's anyio task groups are compatible with asyncio event loops.
- The agent's **status reporter** (`agent/status/reporter.py`) joins the same `asyncio.gather()` as a third tenant of this loop and shares the same shutdown `asyncio.Event`. See `dev/knowledge/agent/overview.md` → "Status Reporter".

## Alternatives Considered

- **Separate threads with separate event loops** (kopf's official embedding example): Adds thread-safety complexity and contradicts the requirement for a shared async event loop. Rejected.
- **Calling `worker.start()` directly**: Blocks the coroutine with no clean cancellation mechanism. Rejected.
- **Using `run_once=True` in a Prefect loop**: Adds polling overhead and loses Prefect's built-in heartbeat/backoff logic. Rejected.
