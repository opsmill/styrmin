"""Telemetry wire envelope and checksum.

``build_envelope(data)`` wraps the scrubbed ``data`` with ``checksum``, ``kind``,
and ``payload_format``. The checksum is a CPython-compatible
``sha256(json.dumps(data))`` so the server can reproduce it. Implemented in T014.
"""
