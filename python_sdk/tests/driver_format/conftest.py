"""Fixtures shared by the tests of ``styrmin_sdk.driver_format``.

Every command of ``styrmin-driver`` must run with no network access (FR-013 of
specs/032-styrmin-driver-cli). The autouse fixture below makes any attempt to open
a connection fail, so a test that reaches the network fails instead of passing.
"""

import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import pytest
import yaml
from styrmin_sdk.driver_format.cli import main


def _refuse_network(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError("network access is not allowed in styrmin-driver tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse_network)
    monkeypatch.setattr(socket, "create_connection", _refuse_network)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPOSITORY_ROOT / "driver" / "examples"
EXAMPLE_NAMES = sorted(p.name for p in EXAMPLES.iterdir() if (p / "driver.styrmin.yml").is_file())


@dataclass(frozen=True)
class CliResult:
    code: int
    out: str
    err: str


@pytest.fixture
def run_cli(capsys: pytest.CaptureFixture[str]) -> Callable[..., CliResult]:
    """Run ``styrmin-driver`` in this process and return its exit code and output."""

    def run(*argv: str) -> CliResult:
        capsys.readouterr()
        code = main(list(argv))
        captured = capsys.readouterr()
        return CliResult(code=code, out=captured.out, err=captured.err)

    return run


@pytest.fixture
def example_copy(tmp_path: Path) -> Callable[[str], Path]:
    """Copy an example driver to a temporary directory and return its path."""

    def copy(name: str) -> Path:
        target = tmp_path / name
        shutil.copytree(EXAMPLES / name, target)
        return target

    return copy


def edit_spec(driver: Path, change: Callable[[dict], None]) -> None:
    """Load a driver's driver.styrmin.yml, apply ``change`` to the data, and write it back."""
    path = driver / "driver.styrmin.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
