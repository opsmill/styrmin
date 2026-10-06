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
    # One step per component (spec 019); empty on the ref ``create_backup`` returns.
    steps: tuple[StepRef, ...] = ()


@dataclass(frozen=True, slots=True)
class RestoreRef:
    id: str
    status: str
    # The restore's steps (spec 019); empty on the ref ``create_restore`` returns.
    steps: tuple[StepRef, ...] = ()


#: Derived environment-operation statuses that never change again, as the raw
#: GraphQL enum *names* :class:`EnvironmentBackupRef` /
#: :class:`EnvironmentRestoreRef` / :class:`EnvironmentCloneRef` carry.
#: ``PARTIAL`` is terminal: it means some constituents failed and the rest
#: completed, which is a final outcome, not a transitional one.
#:
#: Deliberately plain strings rather than the SDK's three
#: ``TERMINAL_ENVIRONMENT_{BACKUP,RESTORE,CLONE}_STATUSES`` frozensets — those
#: hold distinct Python enum types that would never both match one ref field,
#: and the UI driver reads the value out of the DOM as a string anyway. All
#: three environment-level operations share this vocabulary by design (ADR-0055),
#: so one frozenset covers them.
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
class EnvironmentCloneDeploymentResultRef:
    """One source deployment's outcome inside an environment clone.

    Every source deployment the clone *considered* gets exactly one of these
    (spec SC-003), so the tuple on :class:`EnvironmentCloneRef` is the coverage
    identity a scenario asserts against. Note what "considered" excludes:
    internal and tombstoned deployments are **omitted entirely** unless the
    caller named them in the selection — they are not reported as skips.

    ``outcome`` is the raw ``EnvironmentCloneDeploymentOutcome`` enum name
    (``PENDING`` / ``CLONED`` / ``SKIPPED`` / ``FAILED``); the frontend
    publishes it verbatim as ``data-outcome`` and the API driver reads the same
    string off the generated enum's ``.value``, so both entrypoints report
    identical values.

    ``reason`` is free text by contract (open vocabulary — the backend may add
    to it), so scenarios assert on it as text rather than switching on it.
    """

    deployment_id: str
    deployment_name: str
    outcome: str
    reason: str | None
    counterpart_deployment_id: str | None
    restore_id: str | None


@dataclass(frozen=True, slots=True)
class EnvironmentCloneRef:
    """One clone of an environment into a new environment (spec 010).

    ``status`` carries the raw ``EnvironmentCloneStatus`` enum name, *derived*
    on every read from the backing capture, whether the created environment
    still exists, the cross-target constituent restores and the recorded clone
    errors — never stored. A clone can already read ``IN_PROGRESS`` the instant
    it is registered (an upfront skip counts as progress), so nothing may assume
    a ``PENDING``-first progression.

    ``created_environment_id`` is ``None`` in two different situations that must
    not be conflated: the environment has not materialised yet, and the
    environment was deleted (the supported discard path — SC-005). ``discarded``
    tells them apart, derived the same way on both entrypoints: from a
    ``created_environment_deleted`` entry in ``clone_errors``.

    ``clone_errors`` holds the operation-level events pre-rendered as
    ``"step: error"``. It is **not** an error list in the "clone failed" sense:
    a terminal clone whose backing capture or created environment was later
    deleted carries a non-fatal entry while keeping its recorded outcome.
    """

    id: str
    name: str
    status: str
    created_environment_id: str | None
    environment_backup_id: str | None
    discarded: bool
    deployment_results: tuple[EnvironmentCloneDeploymentResultRef, ...]
    clone_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StepErrorRef:
    """The error of one failed attempt of a step."""

    attempt: int
    message: str
    occurred_at: str | None


@dataclass(frozen=True, slots=True)
class StepRef:
    """One step of a task, in the order the API lists them (spec 019).

    ``kind`` and ``status`` are the raw GraphQL enum names (``OPERATOR_PHASE``,
    ``SUCCEEDED`` …); timestamps are ISO 8601 strings.
    """

    id: str
    key: str
    name: str
    kind: str
    status: str
    started_at: str | None
    ended_at: str | None
    attempt_count: int
    errors: tuple[StepErrorRef, ...]
    detail: str | None
    has_output: bool
    # The id of the task that interrupted this step, when it is superseded.
    superseded_by: str | None = None


@dataclass(frozen=True, slots=True)
class TaskLinkRef:
    """A task that started, or was started by, a timeline entry's task."""

    id: str
    type: str
    result: str | None


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    task_id: str
    task_type: str
    task_status: str
    application_version: str | None
    created_on: str | None
    steps: tuple[StepRef, ...] = ()
    started_by_step_id: str | None = None
    # ``started_by.result`` stays None: the timeline reads only its id and type.
    result: str | None = None
    started_by: TaskLinkRef | None = None
    started_tasks: tuple[TaskLinkRef, ...] = ()
