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


#: Derived environment-operation statuses that never change again, as the raw
#: GraphQL enum *names* :class:`EnvironmentBackupRef` / :class:`EnvironmentRestoreRef`
#: carry. ``PARTIAL`` is terminal: it means some constituents failed and the
#: rest completed, which is a final outcome, not a transitional one.
#:
#: Deliberately plain strings rather than the SDK's two
#: ``TERMINAL_ENVIRONMENT_{BACKUP,RESTORE}_STATUSES`` frozensets — those hold
#: distinct Python enum types that would never both match one ref field, and
#: the UI driver reads the value out of the DOM as a string anyway.
TERMINAL_ENVIRONMENT_OPERATION_STATUSES = frozenset({"COMPLETED", "PARTIAL", "FAILED"})


@dataclass(frozen=True, slots=True)
class EnvironmentBackupConstituentRef:
    """One eligible deployment's outcome inside an environment backup.

    ``outcome`` is the closed vocabulary the frontend publishes as
    ``data-constituent-outcome`` (``completed`` / ``failed`` / ``error`` /
    ``in-flight`` / ``missing``); the API driver derives the identical value
    from the SDK payload so both entrypoints report the same string.

    ``missing`` — neither a constituent backup nor a creation error — is the
    deliberately-visible gap left by a constituent deleted individually after
    the snapshot was taken (spec FR-010 / US3).
    """

    deployment_id: str
    deployment_name: str
    outcome: str
    backup_id: str | None
    backup_status: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class EnvironmentBackupRef:
    """A coordinated environment snapshot.

    ``status`` carries the raw ``EnvironmentBackupStatus`` enum value
    (``PENDING`` / ``IN_PROGRESS`` / ``COMPLETED`` / ``PARTIAL`` / ``FAILED``)
    — *derived* from the constituents on every read, never stored.
    """

    id: str
    name: str
    status: str
    constituents: tuple[EnvironmentBackupConstituentRef, ...]


@dataclass(frozen=True, slots=True)
class EnvironmentRestoreSkipRef:
    """A constituent that was not restored, attributed by name and reason.

    ``reason`` is free text, not a closed enum: the service emits the uniform
    reasons (``backup deleted``, ``deployment no longer exists``, …) plus the
    ``restore could not be created: <exc>`` escape hatch. Scenarios assert on
    it as text.
    """

    deployment_id: str
    deployment_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class EnvironmentRestoreRef:
    """One coordinated restore of an environment backup.

    ``status`` carries the raw ``EnvironmentRestoreStatus`` enum value, derived
    from the constituent restores plus the recorded skips.
    """

    id: str
    status: str
    restore_ids: tuple[str, ...]
    skipped: tuple[EnvironmentRestoreSkipRef, ...]


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    task_id: str
    task_type: str
    task_status: str
    application_version: str | None
    created_on: str | None
