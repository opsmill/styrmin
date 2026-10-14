"""No driver in the repository wires container ``command``/``args`` overrides (022 T021, SC-002).

Styrmin applies these overrides by post-render patch to the declared component container, so
no ``values.j2.yml`` calls the retired ``component_command``/``component_args`` filters and no
``driver.styrmin.yml`` carries the removed ``spec.container_overrides`` block. Only ``driver/``
is scanned: the pre-migration templates under ``backend/tests/integration/fixtures/`` call the
filters on purpose, for the SC-005 parity test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DRIVER_ROOT = Path(__file__).resolve().parents[3] / "driver"
FORBIDDEN = ("component_command", "component_args", "container_overrides")
DRIVER_FILES = sorted(
    path
    for path in DRIVER_ROOT.rglob("*")
    if path.is_file() and "__pycache__" not in path.parts
)


def test_driver_tree_is_scanned() -> None:
    assert any(path.name == "values.j2.yml" for path in DRIVER_FILES)
    assert any(path.name == "driver.styrmin.yml" for path in DRIVER_FILES)


@pytest.mark.parametrize(
    "path", DRIVER_FILES, ids=lambda p: str(p.relative_to(DRIVER_ROOT))
)
def test_driver_file_has_no_container_override_wiring(path: Path) -> None:
    content = path.read_bytes()

    found = [word for word in FORBIDDEN if word.encode() in content]

    assert not found, f"{path.relative_to(DRIVER_ROOT.parent)} contains {found}"
