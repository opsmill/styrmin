"""Driver-neutral reference types returned by ScenarioDriver implementations.

Each ref carries only the fields scenarios actually assert on today. Both
ApiScenarioDriver and UiScenarioDriver construct identical refs from their
respective underlying representations (SDK payload vs. rendered DOM).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClusterRef:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class EnvironmentRef:
    id: str
    name: str
    cluster_id: str


@dataclass(frozen=True, slots=True)
class BSLRef:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class DriverVersionRef:
    id: str
    application_driver_id: str
    driver_name: str
    version: str


@dataclass(frozen=True, slots=True)
class DeploymentRef:
    id: str
    status: str
    application_version: str | None
    instance_id: str | None


@dataclass(frozen=True, slots=True)
class BackupRef:
    id: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class RestoreRef:
    id: str
    status: str


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    task_id: str
    task_type: str
    task_status: str
    application_version: str | None
    created_on: str | None
