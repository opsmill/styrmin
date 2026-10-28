import shutil
from pathlib import Path

import pytest

from styrmin_backend import config
from styrmin_backend.services.driver.exceptions import MissingDriverSpecificationError
from styrmin_backend.services.driver.loaders import (
    DriverLoader,
    get_local_driver_loader,
)
from styrmin_backend.services.driver.provider import LocalDriverProvider


def test_get_local_driver_loader_returns_driver_loader(tmp_path: Path) -> None:
    loader = get_local_driver_loader(path=str(tmp_path))
    assert isinstance(loader, DriverLoader)
    assert isinstance(loader.provider, LocalDriverProvider)


def test_get_local_driver_loader_provider_path(tmp_path: Path) -> None:
    loader = get_local_driver_loader(path=str(tmp_path))
    source = loader.provider.get_source()
    assert source.type == "local"
    assert source.path == str(tmp_path)


def test_local_load_reads_the_spec_file_named_by_the_server_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file names still come from ``STYRMIN_DRIVER_*`` after the move to the SDK (FR-016)."""
    example = Path(__file__).parents[5] / "driver" / "examples" / "simple-app"
    shutil.copytree(example, tmp_path / "driver")
    (tmp_path / "driver" / "driver.styrmin.yml").rename(
        tmp_path / "driver" / "custom.styrmin.yml"
    )
    monkeypatch.setattr(config.SETTINGS.driver, "spec_file", "custom.styrmin.yml")

    driver = get_local_driver_loader(path=str(tmp_path / "driver")).load_driver()

    assert driver.driver_spec.metadata.name == "simple-app"


def test_local_load_ignores_the_default_spec_file_when_the_settings_name_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = Path(__file__).parents[5] / "driver" / "examples" / "simple-app"
    shutil.copytree(example, tmp_path / "driver")
    monkeypatch.setattr(config.SETTINGS.driver, "spec_file", "custom.styrmin.yml")

    with pytest.raises(MissingDriverSpecificationError, match="custom.styrmin.yml"):
        get_local_driver_loader(path=str(tmp_path / "driver")).load_driver()
