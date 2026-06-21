"""Telemetry event construction and scrubbing.

``build_event()`` assembles the ordered, closed-set ``data`` payload from the
resolved command route, canonical option names, outcome, error category, and
coarse environment facts, and composes the ``event_id``. Option/command
extraction is token-scan plus Cyclopts metadata only -- values are never read
or converted. Implemented in T012.
"""
