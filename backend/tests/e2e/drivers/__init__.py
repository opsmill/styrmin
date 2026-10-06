"""Drivers for the dual-entrypoint E2E suite.

This package re-exports the :class:`ScenarioDriver` protocol, the
driver-neutral ref types, and the error classes so that scenarios can do

    from tests.e2e.drivers import ScenarioDriver, DeploymentRef
"""

from __future__ import annotations

from tests.e2e.drivers.errors import ResourceNotFound, ScenarioActionError
from tests.e2e.drivers.protocol import ScenarioDriver
from tests.e2e.drivers.refs import (
    BackupRef,
    BSLRef,
    ClusterRef,
    DeploymentRef,
    DriverVersionRef,
    EnvironmentBackupConstituentRef,
    EnvironmentBackupRef,
    EnvironmentCloneDeploymentResultRef,
    EnvironmentCloneRef,
    EnvironmentRef,
    EnvironmentRestoreRef,
    EnvironmentRestoreSkipRef,
    RestoreRef,
    StepErrorRef,
    StepRef,
    TaskLinkRef,
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    TimelineEntry,
)

__all__ = [
    "BSLRef",
    "BackupRef",
    "ClusterRef",
    "DeploymentRef",
    "DriverVersionRef",
    "EnvironmentBackupConstituentRef",
    "EnvironmentBackupRef",
    "EnvironmentCloneDeploymentResultRef",
    "EnvironmentCloneRef",
    "EnvironmentRef",
    "EnvironmentRestoreRef",
    "EnvironmentRestoreSkipRef",
    "ResourceNotFound",
    "RestoreRef",
    "ScenarioActionError",
    "ScenarioDriver",
    "StepErrorRef",
    "StepRef",
    "TERMINAL_ENVIRONMENT_OPERATION_STATUSES",
    "TaskLinkRef",
    "TimelineEntry",
]
