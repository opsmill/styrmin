"""Anonymous, opt-out telemetry for ``styrminctl``.

This package emits a single scrubbed, fire-and-forget event per eligible CLI
invocation after the command's outcome is known. Dispatch is best-effort and
hard-capped at a small latency budget so the telemetry side-channel never
changes a command's output, exit code, or perceptible speed.

Modules:
    config: Endpoint resolution and the latency-budget constant.
    store: ``TelemetryStore`` -- persistent ``{install_id, enabled}`` state.
    eligibility: ``should_emit()`` -- the eligibility ladder.
    event: ``build_event()`` plus command/option extraction and ``event_id``.
    errors: ``categorize_error()`` -- exception type to (outcome, category).
    envelope: ``build_envelope()`` plus the CPython-compatible checksum.
    dispatch: Bounded best-effort POST on a daemon thread.
    runtime: The integration hook wiring resolve -> run -> classify -> dispatch.
"""
