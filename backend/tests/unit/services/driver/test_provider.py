from pathlib import Path

import pytest

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.models.structure.source import LocalSource
from styrmin_backend.services.driver.provider import LocalDriverProvider


def test_local_driver_provider_yields_given_path(tmp_path: Path) -> None:
    provider = LocalDriverProvider(path=str(tmp_path))
    with provider.provide() as provided_path:
        assert provided_path == tmp_path


def test_local_driver_provider_get_source_returns_local_source(tmp_path: Path) -> None:
    provider = LocalDriverProvider(path=str(tmp_path))
    source = provider.get_source()
    assert isinstance(source, LocalSource)
    assert source.type == "local"
    assert source.path == str(tmp_path)


def test_local_driver_provider_raises_on_nonexistent_path() -> None:
    with pytest.raises(DriverLoadingError, match="does not exist"):
        LocalDriverProvider(path="/nonexistent/path/to/driver")


def test_local_driver_provider_raises_on_file_path(tmp_path: Path) -> None:
    driver_file = tmp_path / "driver.yaml"
    driver_file.write_text("name: test")
    with pytest.raises(DriverLoadingError, match="not a directory"):
        LocalDriverProvider(path=str(driver_file))
