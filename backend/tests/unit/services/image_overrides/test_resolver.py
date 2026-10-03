"""Unit tests for :class:`ImageOverridesResolver` (018, T004).

Mirrors ``test_container_overrides_resolver.py``, except that a component without a stored
``image`` yields no entry: the read surface lists only components with an override.
"""

from __future__ import annotations

from styrmin_backend.context.models.config import ComponentConfigBlock
from styrmin_backend.services.image_overrides.resolver import (
    ImageOverridesResolver,
    ResolvedImageOverrideEntry,
)

_PATCHED = "registry.example/acme/simple-app-patched:0.1.0"
_TOKEN = "registry.example/acme/simple-app-patched:{{ app.version }}"


def _resolve(
    blocks: dict[str, ComponentConfigBlock | None] | None,
    driver_components: list[str] | None,
) -> list[ResolvedImageOverrideEntry]:
    return ImageOverridesResolver.resolve_for_deployment(
        component_overrides=blocks,
        driver_components=driver_components,
    )


def test_live_entry_carries_stored_reference_unsubstituted() -> None:
    entries = _resolve({"server": ComponentConfigBlock(image=_TOKEN)}, ["server"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry.component_name == "server"
    assert entry.resolved.reference == _TOKEN
    assert entry.resolved.is_orphaned is False


def test_live_entries_follow_driver_order() -> None:
    blocks = {
        "worker": ComponentConfigBlock(image="worker:2"),
        "server": ComponentConfigBlock(image=_PATCHED),
    }
    entries = _resolve(blocks, ["server", "db", "worker"])
    assert [e.component_name for e in entries] == ["server", "worker"]
    assert [e.resolved.reference for e in entries] == [_PATCHED, "worker:2"]
    assert all(e.resolved.is_orphaned is False for e in entries)


def test_live_component_without_image_is_dropped() -> None:
    blocks = {
        "server": ComponentConfigBlock(env_vars={"X": "1"}, command=["serve"]),
        "worker": None,
    }
    assert _resolve(blocks, ["server", "worker", "db"]) == []


def test_orphan_entry_for_undeclared_component() -> None:
    blocks = {
        "server": ComponentConfigBlock(image=_PATCHED),
        "old": ComponentConfigBlock(image="old:1"),
    }
    entries = {e.component_name: e for e in _resolve(blocks, ["server"])}
    assert set(entries) == {"server", "old"}
    assert entries["server"].resolved.is_orphaned is False
    assert entries["old"].resolved.reference == "old:1"
    assert entries["old"].resolved.is_orphaned is True


def test_orphan_block_without_image_is_dropped() -> None:
    blocks = {
        "server": ComponentConfigBlock(image=_PATCHED),
        "empty": ComponentConfigBlock(),
        "envonly": ComponentConfigBlock(env_vars={"X": "1"}),
        "none": None,
    }
    assert [e.component_name for e in _resolve(blocks, ["server"])] == ["server"]


def test_orphans_sorted_by_name_after_live_entries() -> None:
    blocks = {
        "zeta": ComponentConfigBlock(image="zeta:1"),
        "server": ComponentConfigBlock(image=_PATCHED),
        "alpha": ComponentConfigBlock(image="alpha:1"),
    }
    entries = _resolve(blocks, ["db", "server"])
    assert [e.component_name for e in entries] == ["server", "alpha", "zeta"]
    assert [e.resolved.is_orphaned for e in entries] == [False, True, True]


def test_driver_components_none_returns_empty() -> None:
    assert _resolve({"server": ComponentConfigBlock(image=_PATCHED)}, None) == []


def test_no_stored_blocks_returns_empty() -> None:
    assert _resolve(None, ["server"]) == []
    assert _resolve({}, ["server"]) == []
