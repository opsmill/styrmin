"""The ``data`` object of the daily telemetry report (spec 020, FR-006, research D2)."""

from __future__ import annotations

import platform
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

import styrmin_backend

if TYPE_CHECKING:
    from collections.abc import Iterable

    from styrmin_backend.repository.application_driver_version import (
        DriverVersionUsage,
    )
    from styrmin_backend.services.unit_of_work import UnitOfWork

# The release workflow bumps only the workspace root pyproject.toml (research D6).
ROOT_PYPROJECT_PATH = (
    Path(styrmin_backend.__file__).resolve().parents[2] / "pyproject.toml"
)
ROOT_PROJECT_NAME = "styrmin-mvp"
UNKNOWN_VERSION = "unknown"


def styrmin_version() -> str:
    """Return the Styrmin release version, or ``"unknown"`` when it cannot be read."""
    try:
        with ROOT_PYPROJECT_PATH.open("rb") as file:
            project = tomllib.load(file).get("project")
    except (OSError, tomllib.TOMLDecodeError) as error:
        logger.debug(
            "Styrmin version is unknown: cannot read {}: {}", ROOT_PYPROJECT_PATH, error
        )
        return UNKNOWN_VERSION
    if not isinstance(project, dict):
        project = {}
    version = project.get("version")
    if project.get("name") != ROOT_PROJECT_NAME or not isinstance(version, str):
        logger.debug(
            "Styrmin version is unknown: {} is not the {} project",
            ROOT_PYPROJECT_PATH,
            ROOT_PROJECT_NAME,
        )
        return UNKNOWN_VERSION
    return version


def _merge_driver_usage(rows: Iterable[DriverVersionUsage]) -> list[dict[str, Any]]:
    """One entry per (name, version, source_type), counts added, sorted (research D9)."""
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        counts[(row.name, row.version, row.source_type)] += row.deployment_count
    return [
        {
            "name": name,
            "version": version,
            "source_type": source_type,
            "deployment_count": deployment_count,
        }
        for (name, version, source_type), deployment_count in sorted(counts.items())
    ]


async def build_report_data(uow: UnitOfWork) -> dict[str, Any]:
    """Build the report data. The caller commits, because the install ID may be created here."""
    install_id = await uow.installation.get_or_create_install_id()
    return {
        "install_id": str(install_id),
        "styrmin_version": styrmin_version(),
        "python_version": platform.python_version(),
        "os_family": platform.system(),
        "arch": platform.machine(),
        "cluster_count": await uow.clusters.count(),
        "environment_count": await uow.environments.count(),
        "deployment_count": await uow.deployments.count_live(),
        "drivers": _merge_driver_usage(
            await uow.application_driver_versions.list_usage()
        ),
    }
