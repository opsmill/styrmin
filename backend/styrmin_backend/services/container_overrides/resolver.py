"""Resolver for component-scope container `command`/`args` overrides (014).

Pure logic, no IO. Mirrors the **orphan branch** of
``services/env_vars/resolver.py`` but deliberately NOT its merge: container
overrides are component-scope-only, so there is no ``environment → deployment
→ component`` layering (research.md D2). The resolved value for a component is
simply the stored block's ``command``/``args`` (or "unset").

Read-vs-write asymmetry (FR-005, mirrors the env-vars/ADR-013 design): a stored
block whose component is no longer declared by the current driver version is
**preserved**, flagged ``is_orphaned=True``, and skipped by the post-render
patch builder so no override reaches a container. The GraphQL read surface
still exposes it so the operator can audit and remove it. New typos are blocked
at the mutation boundary by :class:`UnknownComponentContainerOverrideError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from styrmin_backend.context.models.components import (
    ResolvedComponentContainerOverride,
)
from styrmin_backend.context.models.config import ComponentConfigBlock


@dataclass(frozen=True)
class ResolvedContainerOverrideEntry:
    """One :class:`ResolvedComponentContainerOverride` plus its component name.

    Live entries (``is_orphaned=False``) target a component the current driver
    still declares; their resolved value is the component block's
    ``command``/``args`` (or ``None``). Orphan entries (``is_orphaned=True``)
    target a component name no longer in the driver's component map (e.g. after
    a driver upgrade that renamed or removed the component); they remain
    queryable but the patch builder skips them.
    """

    component_name: str
    resolved: ResolvedComponentContainerOverride


class ContainerOverridesResolver:
    """Pure-logic resolver for component-scope container overrides (FR-001..FR-005)."""

    @staticmethod
    def resolve_for_deployment(
        component_overrides: dict[str, ComponentConfigBlock | None] | None,
        driver_components: list[str] | None,
    ) -> list[ResolvedContainerOverrideEntry]:
        """Resolve container overrides for a deployment.

        ``component_overrides`` is the stored per-component blocks keyed by
        component name (sourced from ``DeploymentConfig.components``).
        ``driver_components`` is the list of component names the deployment's
        current driver declares.

        Returns one **live** entry per driver-declared component (direct
        per-component lookup, no layering, ``is_orphaned=False``) followed by
        zero or more **orphan** entries (sorted by name) — one per stored block
        whose key is NOT in ``driver_components`` and that carries a non-empty
        ``command`` or ``args``. Blocks with neither slot set are dropped
        (nothing to surface).

        When ``driver_components`` is ``None`` the resolver emits nothing —
        used when the caller does not yet have the driver's component map.
        """
        entries: list[ResolvedContainerOverrideEntry] = []
        if driver_components is None:
            return entries

        blocks = component_overrides or {}
        known = set(driver_components)

        # Live entries — direct per-component lookup, no env/deployment merge.
        for name in driver_components:
            block = blocks.get(name)
            entries.append(
                ResolvedContainerOverrideEntry(
                    component_name=name,
                    resolved=ResolvedComponentContainerOverride(
                        command=block.command if block is not None else None,
                        args=block.args if block is not None else None,
                        is_orphaned=False,
                    ),
                )
            )

        # Orphan entries (FR-005, US5) — stored blocks for components the
        # driver no longer declares. Sorted for stable surface ordering;
        # empty blocks (neither slot set) are dropped.
        for name in sorted(blocks):
            if name in known:
                continue
            block = blocks.get(name)
            if block is None:
                continue
            if not block.command and not block.args:
                continue
            entries.append(
                ResolvedContainerOverrideEntry(
                    component_name=name,
                    resolved=ResolvedComponentContainerOverride(
                        command=block.command,
                        args=block.args,
                        is_orphaned=True,
                    ),
                )
            )

        return entries
