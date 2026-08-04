"""Enforce the 'no resource limits' rule for the Styrmin Helm charts.

``dev/guidelines/helm.md`` forbids shipping ``resources.limits`` in the
Styrmin-owned charts or in any values overlay committed to this repo:

* a CPU limit throttles bursty workloads (reconcile loops, Helm renders,
  Prefect flow-run subprocesses) instead of letting them burst above their
  request;
* a memory limit turns a transient spike into an OOM kill -- which is how a
  ``task-worker``/agent pod dies mid-flow and orphans a flow run (#312).

Operators remain free to set limits in their own values files; this test only
guards the defaults *we* ship.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

# Styrmin-owned charts plus every values overlay committed to this repo that
# targets them. Third-party chart values (e.g. `dev/local/traefik-values.yaml`)
# and driver example app charts are out of scope -- the rule is about the
# Styrmin platform chart and its agent subchart.
GUARDED_FILES = (
    "helm/styrmin/values.yaml",
    "helm/agent/values.yaml",
    "dev/local/demo-values.yaml",
    "demo/do-values.yaml",
    "backend/tests/e2e/fixtures/styrmin-values.yaml",
)

TEMPLATE_DIRS = (
    "helm/styrmin/templates",
    "helm/agent/templates",
)


def _find_limits(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Collect every ``limits`` mapping reachable from ``node``.

    Returns ``(dotted_path, value)`` pairs so a failure names the exact key.
    """
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key == "limits":
                found.append((child, value))
            found.extend(_find_limits(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_find_limits(value, f"{path}[{index}]"))
    return found


@pytest.mark.parametrize("relative_path", GUARDED_FILES)
def test_values_file_declares_no_resource_limits(relative_path: str) -> None:
    """No committed Styrmin values file may set a non-empty ``limits`` map.

    An explicitly empty ``limits: {}`` is allowed: that is how Bitnami
    subcharts are opted out of their ``resourcesPreset`` (which would
    otherwise inject limits of its own).
    """
    values_path = REPO_ROOT / relative_path
    assert values_path.is_file(), f"{relative_path} not found -- update GUARDED_FILES"

    document = yaml.safe_load(values_path.read_text()) or {}

    offenders = [(key, value) for key, value in _find_limits(document) if value]
    assert not offenders, (
        f"{relative_path} sets resource limits at "
        f"{', '.join(key for key, _ in offenders)}. "
        "Styrmin charts ship requests only -- see dev/guidelines/helm.md."
    )


@pytest.mark.parametrize("relative_path", TEMPLATE_DIRS)
def test_templates_do_not_hardcode_resource_limits(relative_path: str) -> None:
    """Templates must not hardcode a ``limits:`` block either."""
    template_dir = REPO_ROOT / relative_path
    assert template_dir.is_dir(), f"{relative_path} not found -- update TEMPLATE_DIRS"

    offenders = [
        f"{template.relative_to(REPO_ROOT)}:{number}"
        for template in sorted(template_dir.rglob("*.yaml"))
        for number, line in enumerate(template.read_text().splitlines(), start=1)
        if line.strip().startswith("limits:")
    ]
    assert not offenders, (
        f"Hardcoded resource limits in {', '.join(offenders)}. "
        "Styrmin charts ship requests only -- see dev/guidelines/helm.md."
    )
