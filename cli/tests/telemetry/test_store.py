"""Unit tests for :class:`styrminctl.telemetry.store.TelemetryStore`.

Prior art: ``cli/tests/auth/test_token_store.py``. Unlike ``TokenStore``, the
telemetry store is best-effort and must NEVER raise — an unwritable directory
degrades to an ephemeral in-memory install id.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from styrminctl.telemetry.store import TelemetryStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TelemetryStore:
    """Return a fresh store rooted at a tmp XDG_DATA_HOME (exercises resolution)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return TelemetryStore()


# -- default path resolution ------------------------------------------------


def test_default_path_under_xdg_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    s = TelemetryStore()
    assert s.path() == tmp_path / "styrminctl" / "telemetry.json"


# -- round-trip {install_id, enabled} ---------------------------------------


def test_round_trip_install_id_and_enabled(store: TelemetryStore) -> None:
    install_id = store.install_id()
    assert install_id  # non-empty
    assert store.is_enabled() is True  # default-on
    store.set_enabled(False)
    assert store.is_enabled() is False
    # On disk the file carries exactly the two keys.
    raw = json.loads(store.path().read_text())
    assert set(raw) == {"install_id", "enabled"}
    assert raw["install_id"] == install_id
    assert raw["enabled"] is False


def test_absent_file_means_enabled(store: TelemetryStore) -> None:
    assert not store.path().exists()
    assert store.is_enabled() is True


# -- install_id stability across loads --------------------------------------


def test_install_id_stable_across_two_loads(store: TelemetryStore) -> None:
    first = store.install_id()
    second = store.install_id()
    assert first == second
    # A brand-new store object reading the same file must see the same id.
    fresh = TelemetryStore(path=store.path())
    assert fresh.install_id() == first


def test_install_id_persists_when_disabled(store: TelemetryStore) -> None:
    original = store.install_id()
    store.set_enabled(False)
    assert store.is_enabled() is False
    # The id survives the disable and is identical on a fresh read.
    assert store.install_id() == original
    fresh = TelemetryStore(path=store.path())
    assert fresh.install_id() == original
    assert fresh.is_enabled() is False


# -- atomic write + strict permissions --------------------------------------


def test_file_mode_is_0600_after_save(store: TelemetryStore) -> None:
    store.install_id()  # triggers a persist
    mode = stat.S_IMODE(store.path().stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_parent_dir_mode_is_0700_after_save(store: TelemetryStore) -> None:
    store.install_id()
    mode = stat.S_IMODE(store.path().parent.stat().st_mode)
    assert mode == 0o700, f"expected 0700, got {oct(mode)}"


def test_save_is_atomic_no_partial_file_on_disk(tmp_path: Path) -> None:
    store = TelemetryStore(path=tmp_path / "styrminctl" / "telemetry.json")
    store.install_id()
    siblings = [p.name for p in store.path().parent.iterdir()]
    # Only the target file should remain; no .tmp.* leftover.
    assert siblings == [store.path().name]


# -- unwritable-dir ephemeral fallback (never raises) -----------------------


def test_unwritable_dir_falls_back_to_ephemeral_id(tmp_path: Path) -> None:
    """A read-only parent must not raise; the store yields an in-memory id."""
    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o500)  # read+execute only -> cannot create child dir
    try:
        store = TelemetryStore(path=blocked / "styrminctl" / "telemetry.json")
        first = store.install_id()  # must not raise
        assert first  # got a usable id
        # The file could not be written.
        assert not store.path().exists()
        # And the ephemeral id is stable across calls within this process.
        assert store.install_id() == first
        # is_enabled / set_enabled also never raise on an unwritable dir.
        assert store.is_enabled() is True
        assert store.set_enabled(False) is False
    finally:
        # Restore perms so pytest can clean up the tmp tree.
        blocked.chmod(0o700)


def test_corrupt_file_degrades_to_defaults(store: TelemetryStore) -> None:
    """A corrupt JSON file must not raise; the store re-mints state."""
    store.path().parent.mkdir(parents=True, exist_ok=True)
    store.path().write_text("{not valid json")
    # No raise: enabled defaults to True and a fresh id is minted + persisted.
    assert store.is_enabled() is True
    new_id = store.install_id()
    assert new_id
    assert json.loads(store.path().read_text())["install_id"] == new_id
