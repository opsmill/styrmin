"""Telemetry integration hook.

``run(...)`` resolves ``(command, options, eligible)`` without raising, runs the
inner app under ``try/except/finally``, classifies the outcome, and -- when
eligible -- builds and dispatches a single event before re-raising the original
exception unchanged. The whole telemetry path is failure-isolated. Implemented
in T017.
"""
