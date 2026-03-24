from pathlib import Path


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
