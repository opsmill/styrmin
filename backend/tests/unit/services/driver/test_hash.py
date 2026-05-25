"""Unit tests for :func:`compute_driver_content_hash` (spec 013, T008).

Covers:
- Identity (same inputs -> same hash).
- Sensitivity to whitespace-only edits in any of the three files.
- ``actions_py=None`` (omitted) versus ``actions_py=b""`` (included as
  zero-length entry).
- Length-prefix framing collision-resistance (no boundary collisions).
- Output shape (64 lowercase hex chars).
"""

import re

from styrmin_backend.services.driver.hash import compute_driver_content_hash

# Sample bytes used across tests. Kept short and human-readable so failures
# print legibly.
SPEC = b"name: my-driver\nversion: 1.0.0\n"
VALUES = b"replicas: {{ .replicas }}\n"
ACTIONS = b"def hook():\n    return None\n"


def test_identical_inputs_produce_identical_hash() -> None:
    a = compute_driver_content_hash(SPEC, VALUES, ACTIONS)
    b = compute_driver_content_hash(SPEC, VALUES, ACTIONS)
    assert a == b


def test_identical_inputs_without_actions_produce_identical_hash() -> None:
    a = compute_driver_content_hash(SPEC, VALUES, None)
    b = compute_driver_content_hash(SPEC, VALUES, None)
    assert a == b


def test_whitespace_edit_to_driver_spec_changes_hash() -> None:
    base = compute_driver_content_hash(SPEC, VALUES, ACTIONS)
    # Add a single trailing newline -- semantically a no-op for YAML but the
    # hash MUST surface it as drift.
    edited = compute_driver_content_hash(SPEC + b"\n", VALUES, ACTIONS)
    assert base != edited


def test_whitespace_edit_to_values_template_changes_hash() -> None:
    base = compute_driver_content_hash(SPEC, VALUES, ACTIONS)
    edited = compute_driver_content_hash(SPEC, VALUES + b" ", ACTIONS)
    assert base != edited


def test_whitespace_edit_to_actions_py_changes_hash() -> None:
    base = compute_driver_content_hash(SPEC, VALUES, ACTIONS)
    edited = compute_driver_content_hash(SPEC, VALUES, ACTIONS + b"\n")
    assert base != edited


def test_actions_none_vs_empty_bytes_produce_different_hashes() -> None:
    """``None`` omits the third tuple; ``b""`` includes a zero-length tuple."""
    omitted = compute_driver_content_hash(SPEC, VALUES, None)
    empty = compute_driver_content_hash(SPEC, VALUES, b"")
    assert omitted != empty


def test_actions_none_omits_actions_entry_entirely() -> None:
    """When ``actions_py`` is None, the hash matches what we'd compute with a
    hand-rolled two-file framing -- proving the third entry is genuinely
    absent, not present-with-empty-body.
    """
    # Reconstruct expected framing manually for the two-file case.
    import hashlib

    out = bytearray()
    out += b"driver.styrmin.yml\x00" + len(SPEC).to_bytes(8, "big") + SPEC
    out += b"values_template\x00" + len(VALUES).to_bytes(8, "big") + VALUES
    expected = hashlib.sha256(bytes(out)).hexdigest()
    assert compute_driver_content_hash(SPEC, VALUES, None) == expected


def test_length_prefix_prevents_boundary_collisions() -> None:
    """Without length-prefix framing, ``("AB", "CD")`` and ``("A", "BCD")``
    and ``("ABC", "D")`` would all hash the same value. The framing MUST keep
    them distinct.
    """
    h_ab_cd = compute_driver_content_hash(b"AB", b"CD", None)
    h_a_bcd = compute_driver_content_hash(b"A", b"BCD", None)
    h_abc_d = compute_driver_content_hash(b"ABC", b"D", None)
    assert h_ab_cd != h_a_bcd
    assert h_ab_cd != h_abc_d
    assert h_a_bcd != h_abc_d


def test_reordering_the_three_files_would_change_hash() -> None:
    """Swapping driver_spec and values_template byte arguments must yield a
    different hash. This proves the name-prefix in the framing actually
    participates (i.e. the two slots are not symmetric).
    """
    normal = compute_driver_content_hash(SPEC, VALUES, None)
    swapped = compute_driver_content_hash(VALUES, SPEC, None)
    assert normal != swapped


def test_return_value_is_64_lowercase_hex_chars() -> None:
    digest = compute_driver_content_hash(SPEC, VALUES, ACTIONS)
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None


def test_deterministic_across_repeated_calls() -> None:
    """Hashing the same inputs many times in a row yields the same digest."""
    digests = {compute_driver_content_hash(SPEC, VALUES, ACTIONS) for _ in range(10)}
    assert len(digests) == 1
