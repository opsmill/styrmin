"""Guard the Velero subchart invariants in ``helm/styrmin/values.yaml``: fullname pinned to
``velero`` (the name Velero looks up to build its maintenance Job), PVC-patch ConfigMap name
matching the backend constant, and BSL reconcile cadences slower than Velero's 1m default."""

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

# Every committed values overlay for the platform chart; none may re-point the fullname.
VALUES_OVERLAYS = (
    "dev/local/demo-values.yaml",
    "demo/do-values.yaml",
    "backend/tests/e2e/fixtures/styrmin-values.yaml",
)

# The Deployment name Velero looks up; not configurable in Velero.
REQUIRED_VELERO_FULLNAME = "velero"

# `velero server`'s own default for both cadence flags.
VELERO_DEFAULT_CADENCE_SECONDS = 60

_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)([smh])")


def _load(relative_path: str) -> dict[str, Any]:
    path = REPO_ROOT / relative_path
    assert path.is_file(), f"{relative_path} not found -- update this test"
    return yaml.safe_load(path.read_text()) or {}


def _parse_duration_seconds(value: str) -> float:
    """Parse a Go-style duration (``5m``, ``1.5h``, ``1h30m``) into seconds."""
    matches = _DURATION_RE.findall(value)
    assert matches and "".join(f"{n}{u}" for n, u in matches) == value, (
        f"{value!r} is not a Go duration Velero can parse"
    )
    return sum(float(number) * _DURATION_UNITS[unit] for number, unit in matches)


def test_velero_deployment_name_is_maintainable() -> None:
    """The subchart fullname must be pinned to Velero's hardcoded lookup name."""
    velero = _load(PLATFORM_VALUES)["velero"]

    assert velero.get("fullnameOverride") == REQUIRED_VELERO_FULLNAME, (
        f"{PLATFORM_VALUES} must set velero.fullnameOverride to "
        f"{REQUIRED_VELERO_FULLNAME!r}: Velero resolves its own Deployment by that name to "
        "build the kopia maintenance Job, so any other fullname fails every prune."
    )


def test_restore_pvc_patch_configmap_name_matches_backend_constant() -> None:
    """``<fullname>-<key>`` must equal the name the restore builder references."""
    velero = _load(PLATFORM_VALUES)["velero"]
    config_maps = velero.get("configMaps") or {}

    rendered = {f"{velero['fullnameOverride']}-{key}" for key in config_maps}

    assert VELERO_RESTORE_PVC_PATCH_CONFIGMAP in rendered, (
        f"No ConfigMap in {PLATFORM_VALUES} renders as {VELERO_RESTORE_PVC_PATCH_CONFIGMAP!r} "
        f"(the chart names them `<fullname>-<key>`; it ships {sorted(rendered)}). Every "
        "Velero Restore points `spec.resourceModifier` at that name."
    )


@pytest.mark.parametrize("flag", ["backupSyncPeriod", "storeValidationFrequency"])
def test_velero_reconcile_cadence_is_slower_than_default(flag: str) -> None:
    """Both cadence flags must be set, and slower than Velero's 1m default."""
    configuration = _load(PLATFORM_VALUES)["velero"].get("configuration") or {}
    value = configuration.get(flag)

    assert value, (
        f"{PLATFORM_VALUES} must set velero.configuration.{flag}: Velero defaults it to 1m "
        "and each cycle logs a spurious plugin-teardown error (velero#7892)."
    )
    assert _parse_duration_seconds(str(value)) > VELERO_DEFAULT_CADENCE_SECONDS, (
        f"velero.configuration.{flag} is {value!r}, which is not slower than Velero's own "
        "1m default -- the setting then buys nothing."
    )


@pytest.mark.parametrize("relative_path", VALUES_OVERLAYS)
def test_overlays_do_not_rename_velero(relative_path: str) -> None:
    """No committed overlay may point the Velero fullname somewhere else."""
    velero = _load(relative_path).get("velero") or {}
    override = velero.get("fullnameOverride")

    assert override in (None, REQUIRED_VELERO_FULLNAME), (
        f"{relative_path} sets velero.fullnameOverride to {override!r}. Velero only "
        f"maintains a Deployment named {REQUIRED_VELERO_FULLNAME!r}."
    )
