"""Resolver for per-component image overrides (018, research D-009).

Pure logic, no IO. Mirrors ``services/container_overrides/resolver.py``: component-scope only,
no layering. A stored block whose component the current driver no longer declares is preserved
and flagged ``is_orphaned=True``; the read surface lists it and the renderer skips it.
"""

from __future__ import annotations

from dataclasses import dataclass

from styrmin_backend.context.models.components import ResolvedComponentImageOverride
from styrmin_backend.context.models.config import ComponentConfigBlock


@dataclass(frozen=True)
class ResolvedImageOverrideEntry:
    """One :class:`ResolvedComponentImageOverride` plus its component name."""

    component_name: str
    resolved: ResolvedComponentImageOverride


class ImageOverridesResolver:
    """Pure-logic resolver for component-scope image overrides."""

    @staticmethod
    def resolve_for_deployment(
        component_overrides: dict[str, ComponentConfigBlock | None] | None,
        driver_components: list[str] | None,
    ) -> list[ResolvedImageOverrideEntry]:
        """Resolve image overrides for a deployment.

        Returns one **live** entry per driver-declared component that has a stored ``image``
        (driver order), followed by one **orphan** entry per stored block with an ``image``
        whose component the driver no longer declares (sorted by name). Components without an
        ``image`` yield no entry. Returns nothing when ``driver_components`` is ``None``.
        """
        if driver_components is None:
            return []

        blocks = component_overrides or {}
        known = set(driver_components)
        entries: list[ResolvedImageOverrideEntry] = []

        for name in driver_components:
            entry = _entry(name, blocks.get(name), is_orphaned=False)
            if entry is not None:
                entries.append(entry)

        for name in sorted(blocks):
            if name in known:
                continue
            entry = _entry(name, blocks[name], is_orphaned=True)
            if entry is not None:
                entries.append(entry)

        return entries


def _entry(
    name: str, block: ComponentConfigBlock | None, *, is_orphaned: bool
) -> ResolvedImageOverrideEntry | None:
    if block is None or block.image is None:
        return None
    return ResolvedImageOverrideEntry(
        component_name=name,
        resolved=ResolvedComponentImageOverride(
            reference=block.image, is_orphaned=is_orphaned
        ),
    )
