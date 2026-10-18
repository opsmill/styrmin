"""GraphQL types for the environment clone record.

Third member of the environment-operation family, and the one whose derived
status folds the most: ``status`` is a **field resolver, not a column** (010
spec FR-009, ADR-0055 decision 2), recomputed on every read from the backing
capture's own derived status, whether the created environment still exists, the
constituent cross-target ``Restore`` rows reachable only through the JSON
``deployment_results[].restore_id`` values, and the recorded ``clone_errors``.
A stored status could contradict any of the four.

``deploymentResults`` is the other half of the contract: **every** source
deployment considered gets exactly one entry (spec SC-003), so a clone that
left something out is visible rather than silently absent. Unlike the
open-string convention the DB row uses for ``outcome``, the wire type is a
closed enum — the write-side vocabulary is fixed at four values by
:class:`~styrmin_backend.services.backup.clone.EnvironmentCloneDeploymentOutcome`,
so the wire can afford the type safety. ``reason`` stays a free string
(ADR-0055 decision 4).

**The read path is never stricter than the derivation.** Both JSON columns are
projected through readers that degrade a single unreadable entry
(``EnvironmentCloneDeploymentResult.from_stored``, ``read_clone_errors``)
instead of raising. A stricter projection meant one malformed row failed the
whole ``environmentClone`` query as a masked ``INTERNAL_ERROR`` — hiding the
record precisely when an operator needs to read it.

**N+1 avoidance.** Deriving one clone's status needs the ``Restore`` rows named
by its JSON ids, which no ORM relationship can eager-load. Resolving that per
clone would be one query per entry, so the rows are fetched for the whole batch
with a single ``IN`` query
(``EnvironmentCloneRepository.get_referenced_restores``) and handed to
:meth:`EnvironmentClone.from_instance` as ``restores``. Both query resolvers do
this once per request; a clone constructed without the mapping still derives
correctly — an unresolvable reference keeps the entry's recorded outcome, which
is exactly what a cascade-deleted restore means (``data-model.md``).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

import strawberry
from loguru import logger

from styrmin_backend.api.definitions.backup.environment_backup import (
    EnvironmentBackup as EnvironmentBackupType,
)
from styrmin_backend.api.definitions.environment.model import (
    Environment as EnvironmentType,
)
from styrmin_backend.api.scalars import JSON
from styrmin_backend.db.models import EnvironmentClone as EnvironmentCloneModel
from styrmin_backend.db.models import Restore as RestoreModel
from styrmin_backend.services.backup.clone import (
    CloneDeploymentResult as CloneDeploymentResultModel,
    derive_environment_clone_status_from_record,
    read_clone_errors,
    resolve_deployment_result,
)

#: Stand-in ``deploymentId`` for an entry whose own id could not be read.
#: ``deploymentId`` is non-null on the wire, and widening it to please the one
#: unreadable row would weaken the type for every healthy one — so the nil UUID
#: says "unknown" while ``reason`` says why, keeping the entry visible.
_UNREADABLE_DEPLOYMENT_ID = UUID(int=0)


@strawberry.enum(
    name="EnvironmentCloneStatus",
    description=(
        "Derived status of an environment clone — recomputed on every read, "
        "never stored (FR-009). Same vocabulary as ``EnvironmentBackupStatus`` "
        "and ``EnvironmentRestoreStatus``, but folded from different inputs: "
        "the backing capture's own derived status, whether the created "
        "environment exists, the constituent cross-target restores, and the "
        "recorded clone errors."
    ),
)
class EnvironmentCloneStatus(str, Enum):
    """The GraphQL mirror of the service-layer ``EnvironmentCloneStatus``.

    ``strawberry.enum`` attaches its definition to the Python class, so
    registering the service-layer enum here would make an API concern of a
    service-layer type and permanently claim its one GraphQL name. The clone
    surface therefore declares its own mirror, exactly like
    ``EnvironmentRestoreStatus`` does. ``test_environment_clone.py`` asserts the
    members match the service enum one-for-one so the two cannot drift.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@strawberry.enum(
    name="EnvironmentCloneDeploymentOutcome",
    description=(
        "What became of one source deployment in a clone. ``PENDING`` is the "
        "transient value between registration and the step landing; a terminal "
        "clone contains no ``PENDING`` entry. Closed enum on the wire because "
        "the write-side vocabulary is fixed at these four values."
    ),
)
class EnvironmentCloneDeploymentOutcome(str, Enum):
    """The GraphQL mirror of the service-layer
    ``EnvironmentCloneDeploymentOutcome``.

    Same reasoning as :class:`EnvironmentCloneStatus`. Pinned to the service
    enum by a test in ``test_environment_clone.py``.
    """

    PENDING = "pending"
    CLONED = "cloned"
    SKIPPED = "skipped"
    FAILED = "failed"


@strawberry.type(
    description=(
        "One source deployment's outcome in the clone. Every source deployment "
        "considered appears exactly once (SC-003). ``reason`` is set for "
        "SKIPPED and FAILED and is open text — render it, do not switch on it. "
        "``counterpartDeploymentId`` is the deployment created in the cloned "
        "environment (null when the clone created no counterpart deployment "
        "for this source deployment); ``restoreId`` is the cross-target "
        "restore carrying the data (null until one is dispatched). An entry "
        "whose restore failed reads FAILED, with the reason ``the restore "
        "failed: <the restore's error>``, or ``the restore failed`` when the "
        "restore has no error message, and keeps its "
        "``counterpartDeploymentId`` and ``restoreId``."
    )
)
class EnvironmentCloneDeploymentResult:
    deployment_id: UUID
    deployment_name: str
    outcome: EnvironmentCloneDeploymentOutcome = strawberry.field(
        description=(
            "What became of the source deployment. An entry whose restore "
            "failed reads FAILED."
        )
    )
    reason: str | None = strawberry.field(
        description=(
            "Why the deployment was skipped or failed, as open text; null "
            "otherwise. For an entry whose restore failed, it reads ``the "
            "restore failed: <the restore's error>``, or ``the restore "
            "failed`` when the restore has no error message."
        )
    )
    counterpart_deployment_id: UUID | None
    restore_id: UUID | None

    @classmethod
    def from_model(
        cls, result: CloneDeploymentResultModel
    ) -> EnvironmentCloneDeploymentResult:
        return cls(
            deployment_id=result.deployment_id,
            deployment_name=result.deployment_name,
            outcome=EnvironmentCloneDeploymentOutcome(result.outcome.value),
            reason=result.reason,
            counterpart_deployment_id=result.counterpart_deployment_id,
            restore_id=result.restore_id,
        )

    @classmethod
    def from_stored(
        cls, raw: Any, index: int, restores: Mapping[UUID, RestoreModel]
    ) -> EnvironmentCloneDeploymentResult:
        """Project one stored entry, degrading instead of failing the query.

        A readable entry passes through
        :func:`~styrmin_backend.services.backup.clone.resolve_deployment_result`
        first, so a ``cloned`` entry whose restore failed reads ``FAILED``
        (#530).

        The wire type is stricter than the column: ``outcome`` is a closed enum
        here and free JSON there, and the derivation deliberately tolerates both
        an unrecognised outcome and an entry that is not a mapping at all
        (counting either as a failure, so the coverage identity holds). A bare
        ``model_validate`` therefore made the *whole* ``environmentClone`` query
        fail with a masked ``INTERNAL_ERROR`` over one bad row — leaving the
        operator unable to read the record on any surface, which is exactly when
        they need to.

        A degraded entry keeps whatever was readable and says what was not: the
        index, the field, and the raw value, in ``reason``. Its ``outcome`` is
        ``FAILED``, matching how the derivation counts it — an entry nobody can
        read is a source deployment nobody can account for, not a success.
        """
        try:
            result = CloneDeploymentResultModel.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 — one bad row must stay readable
            logger.warning(
                "Projecting unreadable deployment_results[{}] entry as FAILED: "
                "{!r} ({})",
                index,
                raw,
                exc,
            )
            return cls._from_unreadable(raw, index)
        return cls.from_model(resolve_deployment_result(result, restores))

    @classmethod
    def _from_unreadable(cls, raw: Any, index: int) -> EnvironmentCloneDeploymentResult:
        """Project an entry that does not validate, keeping what can be read."""
        entry = raw if isinstance(raw, dict) else {}
        return cls(
            deployment_id=_read_optional_uuid(entry.get("deployment_id"))
            or _UNREADABLE_DEPLOYMENT_ID,
            deployment_name=str(
                entry.get("deployment_name") or f"<unreadable entry {index}>"
            ),
            outcome=EnvironmentCloneDeploymentOutcome.FAILED,
            reason=(
                f"this attribution entry (index {index}) could not be read: {raw!r}"
            ),
            counterpart_deployment_id=_read_optional_uuid(
                entry.get("counterpart_deployment_id")
            ),
            restore_id=_read_optional_uuid(entry.get("restore_id")),
        )


@strawberry.type
class EnvironmentClone:
    id: UUID
    name: str
    source_environment_name: str
    created_on: datetime
    updated_on: datetime | None = None

    db_model: strawberry.Private[EnvironmentCloneModel]
    #: The ``Restore`` rows named by ``deployment_results[].restore_id``, keyed
    #: by id, fetched once per request for the whole batch. Empty is legal — the
    #: derivation treats an unresolvable reference as one whose recorded outcome
    #: stands.
    referenced_restores: strawberry.Private[Mapping[UUID, RestoreModel]]

    @strawberry.field(
        description=(
            "Derived on every read from the capture's own derived status, the "
            "existence of the created environment, the constituent "
            "cross-target restores and the recorded clone errors — never "
            "stored, so it cannot contradict any of them. Terminal values are "
            "COMPLETED, PARTIAL and FAILED."
        )
    )
    def status(self) -> EnvironmentCloneStatus:
        derived = derive_environment_clone_status_from_record(
            self.db_model, self.referenced_restores
        )
        return EnvironmentCloneStatus(derived.value)

    @strawberry.field(
        description=(
            "The environment that was cloned. Null once the source has been "
            "deleted — a clone that created an environment survives its source "
            "as that environment's provenance (``sourceEnvironmentName`` keeps "
            "it readable)."
        )
    )
    async def source_environment(self, info: strawberry.Info) -> EnvironmentType | None:
        return await _resolve_optional(
            info,
            "environments",
            self.db_model.source_environment_id,
            EnvironmentType,
        )

    @strawberry.field(
        description=(
            "The capture the clone was built from. Null when registration "
            "never linked one, or once the capture has been deleted "
            "post-terminality (routine TTL cleanup does not rewrite the "
            "clone's outcome)."
        )
    )
    async def environment_backup(
        self, info: strawberry.Info
    ) -> EnvironmentBackupType | None:
        return await _resolve_optional(
            info,
            "environment_backups",
            self.db_model.environment_backup_id,
            EnvironmentBackupType,
        )

    @strawberry.field(
        description=(
            "The environment the clone created. Null until the capture "
            "succeeds and the environment materialises, and again once it has "
            "been deleted (the discard path — SC-005)."
        )
    )
    async def created_environment(
        self, info: strawberry.Info
    ) -> EnvironmentType | None:
        return await _resolve_optional(
            info,
            "environments",
            self.db_model.created_environment_id,
            EnvironmentType,
        )

    @strawberry.field(
        description=(
            "The explicit deployment selection as requested. Null means every "
            "eligible deployment was included (FR-003)."
        )
    )
    def requested_deployment_ids(self) -> list[UUID] | None:
        raw = self.db_model.requested_deployment_ids
        if raw is None:
            return None
        return [_read_uuid(value) for value in raw]

    @strawberry.field(
        description=(
            "The environment-config override as supplied, canonicalised; null "
            "if none. Merged over the captured config by the clone flow "
            "(FR-006)."
        )
    )
    def config_override(self) -> JSON | None:
        return self.db_model.config_override

    @strawberry.field(
        description=(
            "The captured-config field names removed before the override "
            "merge, as supplied; null if none (FR-006)."
        )
    )
    def clear_config_fields(self) -> list[str] | None:
        raw = self.db_model.cleared_config_fields
        if raw is None:
            return None
        return [str(value) for value in raw]

    @strawberry.field(
        description=(
            "One entry per source deployment considered — cloned, skipped "
            "with a reason, or failed with a reason (SC-003)."
        )
    )
    def deployment_results(self) -> list[EnvironmentCloneDeploymentResult]:
        return [
            EnvironmentCloneDeploymentResult.from_stored(
                raw, index, self.referenced_restores
            )
            for index, raw in enumerate(self.db_model.deployment_results or [])
        ]

    @strawberry.field(
        description=(
            "Operation-level events that happened outside any single "
            "deployment (capture failed, target name lost, environment "
            "creation failed, an input deleted underneath the clone), rendered "
            "``step: error``. Per-deployment failures are not here — they are "
            "in ``deploymentResults``."
        )
    )
    def clone_errors(self) -> list[str]:
        # Read through the *derivation's* reader, not ``model_validate``:
        # ``fatal`` is required on the model but optional in practice (the
        # derivation reads a missing flag as non-fatal on purpose), so
        # validating here made one flag-less entry fail the whole clone query.
        # A read path may never be stricter than the write path it renders.
        return [
            f"{entry.step}: {entry.error}"
            for entry in read_clone_errors(self.db_model.clone_errors)
        ]

    @classmethod
    def from_instance(
        cls,
        instance: EnvironmentCloneModel,
        restores: Mapping[UUID, RestoreModel] | None = None,
    ) -> EnvironmentClone:
        """Wrap a persisted clone.

        Pass ``restores`` — from
        ``EnvironmentCloneRepository.get_referenced_restores`` over the whole
        batch — whenever more than one clone is being projected, so ``status``
        costs one query for the batch instead of one per referenced restore.
        """
        return cls(
            id=instance.id,
            name=instance.name,
            source_environment_name=instance.source_environment_name,
            created_on=instance.created_on,  # type: ignore[arg-type]
            updated_on=instance.updated_on,
            db_model=instance,
            referenced_restores=restores or {},
        )


def _read_uuid(value: Any) -> UUID:
    """Read a JSON-stored id back as a ``UUID``."""
    return value if isinstance(value, UUID) else UUID(str(value))


def _read_optional_uuid(value: Any) -> UUID | None:
    """Read a JSON-stored id, or ``None`` when it is absent or unreadable.

    Used only on the degraded projection path: an entry that already failed
    validation must not fail again on one of its ids.
    """
    if value is None:
        return None
    try:
        return _read_uuid(value)
    except TypeError, ValueError:
        return None


async def _resolve_optional(
    info: strawberry.Info,
    repo_attr: str,
    entity_id: UUID | None,
    type_cls: type[Any],
) -> Any:
    """Resolve a nullable link, returning ``None`` for an absent row.

    Deliberately not
    :func:`~styrmin_backend.api.resolvers.resolve_related`: every link on a
    clone is nullable *by design* (each one is nulled by a deletion path that
    records what happened in ``clone_errors``), so a missing row is data, not an
    error. Re-reading through the repository rather than using the eager-loaded
    relationship is what makes the nested type's own resolvers safe — the clone
    repository loads what the *clone's* derivation needs, not what the nested
    ``Environment``/``EnvironmentBackup`` types need.
    """
    if entity_id is None:
        return None
    uow: Any = info.context["uow"]
    async with uow:
        entity = await getattr(uow, repo_attr).get(entity_id)
        if entity is None:
            return None
        return type_cls.from_instance(entity)
