"""Canonical content-hash helper for driver provenance (spec 013).

This module exposes :func:`compute_driver_content_hash`, the single source of
truth for the ``content_hash`` column on ``ApplicationDriverVersion`` when a
driver is loaded from a local filesystem source.

Design notes
------------
- **Raw bytes intentionally**: we hash the files as they are on disk, with no
  YAML canonicalisation, comment stripping, or whitespace normalisation. This
  is deliberate so that whitespace/comment-only edits surface as drift and
  produce a new driver-version row. The fingerprint is a function of bytes,
  not of semantic equivalence.
- **Length-prefix framing**: every file body is preceded by its name (a
  literal byte-string terminated by ``\\x00``) and an 8-byte big-endian
  length. This prevents boundary-collision attacks where two different
  (driver_spec, values_template) pairs could otherwise hash to the same value
  by sliding bytes across the conceptual file boundary.
- **``actions.py`` inclusion**: the third file is included in the hash iff the
  caller passes a non-None ``actions_py`` argument. This mirrors the loader's
  behaviour of only reading ``actions.py`` when ``driver_spec.spec.actions``
  is non-empty. ``actions_py=b""`` (an empty actions.py) is *different* from
  ``actions_py=None`` (no actions.py): the former includes a zero-length
  framed entry, the latter omits the entry entirely.

See ``specs/013-driver-fingerprint/data-model.md`` for the authoritative
algorithm definition.
"""

import hashlib


def compute_driver_content_hash(
    driver_spec: bytes,
    values_template: bytes,
    actions_py: bytes | None,
) -> str:
    """Return the SHA-256 hex digest of the canonical driver byte concatenation.

    Args:
        driver_spec: Raw bytes of ``driver.styrmin.yml`` as read from disk.
        values_template: Raw bytes of the values template file declared in the
            driver's directory map.
        actions_py: Raw bytes of ``actions.py`` IF the driver spec declares any
            actions; otherwise ``None`` to omit the file from the hash.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.
    """
    parts: list[tuple[bytes, bytes]] = [
        (b"driver.styrmin.yml", driver_spec),
        (b"values_template", values_template),
    ]
    if actions_py is not None:
        parts.append((b"actions.py", actions_py))

    out = bytearray()
    for name, body in parts:
        out += name + b"\x00"
        out += len(body).to_bytes(8, "big")
        out += body
    return hashlib.sha256(bytes(out)).hexdigest()
