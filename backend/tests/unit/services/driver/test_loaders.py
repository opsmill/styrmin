from pathlib import Path

import pytest

from styrmin_backend.services.driver.exceptions import (
    AmbiguousDriverFormatError,
    DeprecatedDriverFormatError,
)
from styrmin_backend.services.driver.loaders import (
    DriverLoader,
    _check_driver_format,
    get_local_driver_loader,
)
from styrmin_backend.services.driver.models.structure.directory import DriverDirectory
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


def test_check_driver_format_raises_deprecated_error(tmp_path: Path) -> None:
    """Old filenames without new ones should raise DeprecatedDriverFormatError."""
    (tmp_path / "styrmin_driver.yaml").write_text("---")
    (tmp_path / "actions.yaml").write_text("---")
    directory_map = DriverDirectory(root_path=tmp_path)
    with pytest.raises(DeprecatedDriverFormatError) as exc_info:
        _check_driver_format(tmp_path, directory_map)
    assert "styrmin_driver.yaml" in str(exc_info.value)
    assert "actions.yaml" in str(exc_info.value)


def test_check_driver_format_raises_ambiguous_error(tmp_path: Path) -> None:
    """Both old and new filenames should raise AmbiguousDriverFormatError."""
    (tmp_path / "driver.styrmin.yml").write_text("---")
    (tmp_path / "styrmin_driver.yaml").write_text("---")
    directory_map = DriverDirectory(root_path=tmp_path)
    with pytest.raises(AmbiguousDriverFormatError) as exc_info:
        _check_driver_format(tmp_path, directory_map)
    assert "styrmin_driver.yaml" in str(exc_info.value)


def test_check_driver_format_passes_with_new_format_only(tmp_path: Path) -> None:
    """New filenames only should not raise."""
    (tmp_path / "driver.styrmin.yml").write_text("---")
    directory_map = DriverDirectory(root_path=tmp_path)
    # Should not raise
    _check_driver_format(tmp_path, directory_map)


def test_check_driver_format_passes_with_no_files(tmp_path: Path) -> None:
    """No files at all should not raise (loading will fail later)."""
    directory_map = DriverDirectory(root_path=tmp_path)
    # Should not raise - missing file detection is handled by ResourceFileLoader
    _check_driver_format(tmp_path, directory_map)
