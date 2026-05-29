"""Unit tests for :class:`ContainerOverridesResolver` (014).

US1 covers the **live** branch: one entry per driver-declared component, the
resolved value equal to the component block's ``command``/``args`` (NO layering
— research.md D2). The orphan branch (US5) is added by the US5 phase
(data-model.md §4).
"""

from __future__ import annotations

from styrmin_backend.context.models.config import ComponentConfigBlock
from styrmin_backend.services.container_overrides.resolver import (
    ContainerOverridesResolver,
)


def _resolve(blocks, driver_components):
    return ContainerOverridesResolver.resolve_for_deployment(
        component_overrides=blocks,
        driver_components=driver_components,
    )


def test_live_entry_equals_block_value() -> None:
    """A live entry carries exactly the component block's command/args."""
    blocks = {
        "server": ComponentConfigBlock(
            command=["uvicorn", "app"], args=["--port", "8000"]
        ),
    }
    entries = _resolve(blocks, ["server"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry.component_name == "server"
    assert entry.resolved.command == ["uvicorn", "app"]
    assert entry.resolved.args == ["--port", "8000"]
    assert entry.resolved.is_orphaned is False


def test_live_entry_none_when_no_block() -> None:
    """A driver-declared component with no stored block resolves to unset."""
    entries = _resolve({}, ["server"])
    assert len(entries) == 1
    assert entries[0].component_name == "server"
    assert entries[0].resolved.command is None
    assert entries[0].resolved.args is None
    assert entries[0].resolved.is_orphaned is False


def test_no_layering_value_is_component_scope_only() -> None:
    """There is no env/deployment layering — the resolved value is the
    component block's value, full stop (research.md D2).
    """
    blocks = {
        "server": ComponentConfigBlock(args=["--log-level", "debug"]),
        "worker": ComponentConfigBlock(command=["python", "-m", "worker"]),
    }
    entries = {e.component_name: e for e in _resolve(blocks, ["server", "worker"])}
    assert entries["server"].resolved.args == ["--log-level", "debug"]
    assert entries["server"].resolved.command is None
    assert entries["worker"].resolved.command == ["python", "-m", "worker"]
    assert entries["worker"].resolved.args is None


def test_one_live_entry_per_driver_component() -> None:
    """Every driver-declared component yields exactly one live entry, in
    declaration order.
    """
    entries = _resolve({"server": ComponentConfigBlock(args=["x"])}, ["server", "db"])
    assert [e.component_name for e in entries] == ["server", "db"]
    assert all(e.resolved.is_orphaned is False for e in entries)


def test_driver_components_none_returns_empty() -> None:
    """When the driver component map is unknown, the resolver emits nothing."""
    assert _resolve({"server": ComponentConfigBlock(args=["x"])}, None) == []


# ---------------------------------------------------------------------------
# US5 — orphan branch (data-model.md §4)
# ---------------------------------------------------------------------------


def test_orphan_entry_for_undeclared_component() -> None:
    """A stored block for a component the driver no longer declares surfaces
    as a single orphan entry with the stored values (FR-005)."""
    blocks = {
        "server": ComponentConfigBlock(args=["--port", "8000"]),
        "old": ComponentConfigBlock(command=["legacy"], args=["--flag"]),
    }
    entries = {e.component_name: e for e in _resolve(blocks, ["server"])}
    assert set(entries) == {"server", "old"}
    assert entries["server"].resolved.is_orphaned is False
    orphan = entries["old"]
    assert orphan.resolved.is_orphaned is True
    assert orphan.resolved.command == ["legacy"]
    assert orphan.resolved.args == ["--flag"]


def test_empty_orphan_block_dropped() -> None:
    """A stored block for an undeclared component that carries neither slot is
    dropped — there is nothing to surface."""
    blocks = {
        "server": ComponentConfigBlock(args=["x"]),
        "empty": ComponentConfigBlock(),
    }
    entries = {e.component_name: e for e in _resolve(blocks, ["server"])}
    assert set(entries) == {"server"}


def test_orphans_sorted_by_name() -> None:
    """Orphan entries are emitted in sorted order for a stable read surface."""
    blocks = {
        "server": ComponentConfigBlock(args=["x"]),
        "zeta": ComponentConfigBlock(args=["z"]),
        "alpha": ComponentConfigBlock(command=["a"]),
    }
    entries = _resolve(blocks, ["server"])
    orphan_names = [e.component_name for e in entries if e.resolved.is_orphaned]
    assert orphan_names == ["alpha", "zeta"]


def test_live_and_orphan_mix() -> None:
    """Live entries come first (driver order), orphans after (sorted)."""
    blocks = {
        "server": ComponentConfigBlock(command=["uvicorn"]),
        "ghost": ComponentConfigBlock(args=["--gone"]),
    }
    entries = _resolve(blocks, ["server", "db"])
    assert [e.component_name for e in entries] == ["server", "db", "ghost"]
    assert [e.resolved.is_orphaned for e in entries] == [False, False, True]
