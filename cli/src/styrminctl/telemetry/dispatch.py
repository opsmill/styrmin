"""Best-effort, bounded telemetry dispatch.

``dispatch(envelope, endpoint, budget_ms)`` runs a sync ``httpx`` POST on a
daemon thread and joins with the latency budget; on timeout the thread is
abandoned. A top-level catch-all in the thread target swallows every error
(including at interpreter teardown) so dispatch never raises or prints. No
retry, batch, or spool. Implemented in T015.
"""
