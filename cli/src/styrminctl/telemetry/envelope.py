"""Telemetry wire envelope and checksum.

``build_envelope(data)`` wraps the scrubbed ``data`` with ``checksum``, ``kind``,
and ``payload_format``. The checksum is a CPython-compatible
``sha256(json.dumps(data))`` so the server can reproduce it (FR-005, FR-006).

The checksum uses CPython's :func:`json.dumps` defaults — separators
``(", ", ": ")``, ``ensure_ascii=True``, **insertion** key order, and **no**
``sort_keys``. Because ``data`` is built in a fixed insertion order (see
``event.build_event``), this serialization is deterministic and a server
reproducing ``pythonJsonStringify(data)`` + SHA-256 recomputes the identical
digest (SC-005).

See ``specs/015-styrminctl-telemetry/contracts/telemetry-wire-format.md`` and
``research.md`` (R10).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

#: Constant discriminator identifying the producing CLI.
ENVELOPE_KIND: Final[str] = "styrminctl"

#: Constant wire-format version (an opaque string to the server).
PAYLOAD_FORMAT: Final[str] = "1.0"


def checksum(data: dict[str, Any]) -> str:
    """Return the CPython-compatible SHA-256 hex digest of ``data``.

    Serializes ``data`` with :func:`json.dumps` defaults (insertion key order,
    no ``sort_keys``) so a server applying ``pythonJsonStringify`` + SHA-256
    reproduces the same digest.
    """
    serialized = json.dumps(data).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def build_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap the scrubbed ``data`` in the POST envelope.

    Returns ``{"data", "checksum", "kind", "payload_format"}`` with the constant
    ``kind``/``payload_format`` values and a checksum computed over ``data``.
    """
    return {
        "data": data,
        "checksum": checksum(data),
        "kind": ENVELOPE_KIND,
        "payload_format": PAYLOAD_FORMAT,
    }
