"""Guard the Velero subchart naming and log-cadence invariants.

Two things about the ``velero`` subchart section of ``helm/styrmin/values.yaml``
are load-bearing and invisible from the Python side:

* **The Velero Deployment must be named exactly ``velero``.** Velero's
  repository-maintenance controller resolves its own Deployment by that
  hardcoded name (``pkg/repository/manager/manager.go``,
  ``buildMaintenanceJob``) to copy the image, env, volumes, and service account
  into the kopia maintenance Job. The subchart's default fullname is
  ``<release>-velero``, which makes every maintenance cycle fail with
  ``error pruning repository ... Deployment.apps "velero" not found`` — kopia
  never prunes and the backup repository grows without bound in object storage.

* **The rendered ConfigMap name must match the backend constant.** Every Velero
  Restore Styrmin builds points ``spec.resourceModifier`` at the PVC-patch
  ConfigMap by name. The chart renders it as ``<fullname>-<key>``, so a rename
  on either side silently makes Velero reject every restore.

The cadence assertions cover the third piece: ``velero server`` defaults
``--backup-sync-period`` and ``--store-validation-frequency`` to 1m, and each
cycle spawns then kills an object-store plugin process whose teardown logs a
spurious error (velero#7892). Styrmin names the BSL on every Backup and tracks
backup state in its own database, so it gains nothing from the 1m default.

See ``dev/guidelines/helm.md`` ("Velero subchart naming").
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.builders.backup import (
    VELERO_RESTORE_PVC_PATCH_CONFIGMAP,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PLATFORM_VALUES = "helm/styrmin/values.yaml"

# Every values overlay committed to this repo that targets the platform chart.
# An overlay that re-pointed `velero.fullnameOverride` would reintroduce the bug
# for exactly the install it configures.
VALUES_OVERLAYS = (
    "dev/local/demo-values.yaml",
    "demo/do-values.yaml",
    "backend/tests/e2e/fixtures/styrmin-values.yaml",
)

# The name Velero itself looks for. Not configurable in Velero.
REQUIRED_VELERO_FULLNAME = "velero"

# `velero server`'s own default for both cadence flags.
VELERO_DEFAULT_CADENCE_SECONDS = 60

_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}
_DURATION_RE = re.compile(r"(\d+)([smh])")


def _load(relative_path: str) -> dict[str, Any]:
    path = REPO_ROOT / relative_path
    assert path.is_file(), f"{relative_path} not found -- update this test"
    return yaml.safe_load(path.read_text()) or {}


def _parse_duration_seconds(value: str) -> int:
    """Parse a Go-style duration (``5m``, ``1h30m``) into seconds."""
    matches = _DURATION_RE.findall(value)
    assert matches, f"{value!r} is not a Go duration Velero can parse"
    assert "".join(f"{n}{u}" for n, u in matches) == value, (
        f"{value!r} is not a Go duration Velero can parse"
    )
    return sum(int(number) * _DURATION_UNITS[unit] for number, unit in matches)


def test_velero_deployment_name_is_maintainable() -> None:
    """The subchart fullname must be pinned to Velero's hardcoded lookup name."""
    velero = _load(PLATFORM_VALUES)["velero"]

    assert velero.get("fullnameOverride") == REQUIRED_VELERO_FULLNAME, (
        f"{PLATFORM_VALUES} must set velero.fullnameOverride to "
        f"{REQUIRED_VELERO_FULLNAME!r}. Velero resolves its own Deployment by "
        "that hardcoded name to build the kopia maintenance Job; any other "
        'fullname fails every prune with `Deployment.apps "velero" not found` '
        "and the backup repository is never garbage collected."
    )


def test_restore_pvc_patch_configmap_name_matches_backend_constant() -> None:
    """``<fullname>-<key>`` must equal the name the restore builder references."""
    velero = _load(PLATFORM_VALUES)["velero"]
    config_maps = velero.get("configMaps") or {}

    rendered = {f"{velero['fullnameOverride']}-{key}" for key in config_maps}

    assert VELERO_RESTORE_PVC_PATCH_CONFIGMAP in rendered, (
        f"No ConfigMap in {PLATFORM_VALUES} renders as "
        f"{VELERO_RESTORE_PVC_PATCH_CONFIGMAP!r} (the chart names them "
        f"`<fullname>-<key>`; it currently ships {sorted(rendered)}). Every "
        "Velero Restore points `spec.resourceModifier` at that name, so a "
        "mismatch makes Velero reject every restore."
    )


@pytest.mark.parametrize("flag", ["backupSyncPeriod", "storeValidationFrequency"])
def test_velero_reconcile_cadence_is_slower_than_default(flag: str) -> None:
    """Both cadence flags must be set, and slower than Velero's 1m default."""
    configuration = _load(PLATFORM_VALUES)["velero"].get("configuration") or {}
    value = configuration.get(flag)

    assert value, (
        f"{PLATFORM_VALUES} must set velero.configuration.{flag}. Velero "
        "defaults it to 1m, and each cycle spawns and kills a plugin process "
        "whose teardown logs a spurious error (velero#7892)."
    )
    assert _parse_duration_seconds(str(value)) > VELERO_DEFAULT_CADENCE_SECONDS, (
        f"velero.configuration.{flag} is {value!r}, which is not slower than "
        "Velero's own 1m default -- the setting then buys nothing."
    )


@pytest.mark.parametrize("relative_path", VALUES_OVERLAYS)
def test_overlays_do_not_rename_velero(relative_path: str) -> None:
    """No committed overlay may point the Velero fullname somewhere else."""
    velero = _load(relative_path).get("velero") or {}
    override = velero.get("fullnameOverride")

    assert override in (None, REQUIRED_VELERO_FULLNAME), (
        f"{relative_path} sets velero.fullnameOverride to {override!r}. Velero "
        f"only maintains a Deployment named {REQUIRED_VELERO_FULLNAME!r}."
    )
