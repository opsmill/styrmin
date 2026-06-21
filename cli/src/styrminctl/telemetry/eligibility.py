"""Telemetry eligibility ladder.

``should_emit()`` is a pure resolver over the FR-014/FR-015 rungs (command
eligibility, env opt-out, persisted flag, CI, non-TTY). Built incrementally
across T016 (command rung), T021 (env/persisted rungs), and T025 (CI/TTY rungs).
"""
