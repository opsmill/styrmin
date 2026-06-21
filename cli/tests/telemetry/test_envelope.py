"""Unit tests for the telemetry envelope and its checksum (T009).

Covers the envelope shape (``data``/``checksum``/``kind``/``payload_format``),
the constant ``kind``/``payload_format`` values, the CPython-default
``sha256(json.dumps(data))`` checksum (insertion order, no ``sort_keys``), and a
fixed round-trip vector from ``contracts/telemetry-wire-format.md`` (SC-005).
"""

from __future__ import annotations

import hashlib
import json

from styrminctl.telemetry.envelope import build_envelope


def _sample_data() -> dict[str, object]:
    """Return the pinned contract ``data`` vector in exact insertion order."""
    return {
        "event_id": "a1b2c3d4-deployments_update",
        "install_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        "command": "deployments update",
        "options": ["--config", "--wait"],
        "outcome": "success",
        "error_category": None,
        "styrminctl_version": "0.1.0",
        "python_version": "3.14.0",
        "os_family": "Linux",
    }


def test_envelope_keys_and_constants() -> None:
    envelope = build_envelope(_sample_data())
    assert set(envelope) == {"data", "checksum", "kind", "payload_format"}
    assert envelope["kind"] == "styrminctl"
    assert envelope["payload_format"] == "1.0"


def test_envelope_data_is_the_passed_object() -> None:
    data = _sample_data()
    envelope = build_envelope(data)
    assert envelope["data"] == data


def test_checksum_matches_cpython_default_json_dumps() -> None:
    data = _sample_data()
    envelope = build_envelope(data)
    expected = hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()
    assert envelope["checksum"] == expected


def test_checksum_uses_insertion_order_not_sorted() -> None:
    # A sorted-keys serialization would differ from the insertion-order one,
    # so the checksum must NOT equal the sort_keys variant.
    data = _sample_data()
    envelope = build_envelope(data)
    sorted_digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    assert envelope["checksum"] != sorted_digest


def test_fixed_round_trip_vector_pinned_digest() -> None:
    # SC-005: the contract vector reproduces a server-recomputable digest.
    data = _sample_data()
    serialized = json.dumps(data)
    # CPython default separators are ", " / ": " and ensure_ascii=True.
    assert serialized == (
        '{"event_id": "a1b2c3d4-deployments_update", '
        '"install_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", '
        '"command": "deployments update", '
        '"options": ["--config", "--wait"], '
        '"outcome": "success", '
        '"error_category": null, '
        '"styrminctl_version": "0.1.0", '
        '"python_version": "3.14.0", '
        '"os_family": "Linux"}'
    )
    pinned = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    envelope = build_envelope(data)
    assert envelope["checksum"] == pinned
    # Reproduce the digest the way a server would (pythonJsonStringify + sha256).
    assert pinned == hashlib.sha256(json.dumps(envelope["data"]).encode("utf-8")).hexdigest()
