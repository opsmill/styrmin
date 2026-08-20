"""Propagation tests for the environment-clone GraphQL surface.

Constitution §V: every new field, argument, and mutation under ``api/schema/``
must be proven to reach the database (writes) and to project persisted state
(reads). Three things make that non-negotiable here:

* ``EnvironmentClone.status`` has **no column** — it is recomputed on every read
  from four heterogeneous inputs (the capture's *own* derived status, whether the
  created environment exists, the constituent cross-target ``Restore`` rows, and
  the recorded ``clone_errors``). A test that asserted only on the mutation's
  return value would pass even if the derivation never touched the DB.
* the constituent ``Restore`` rows are reachable **only** through ids inside the
  JSON ``deployment_results`` entries, so nothing about them is enforced by a
  foreign key or a relationship. They are also why the list resolver batches:
  the N+1 guard at the bottom of this module pins that to one query.
* the capture link is a nullable FK stamped *last* inside the registration
  transaction, so a registration that created the capture but forgot to write
  ``environment_backup_id`` would look perfectly healthy in the response.

Every read assertion goes through a **second session bound to the same engine**
(``fresh_client``), i.e. a unit of work with its own identity map, so the values
must have survived a real round-trip.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.api.definitions.backup.environment_clone import (
    EnvironmentCloneDeploymentOutcome as EnvironmentCloneDeploymentOutcomeType,
    EnvironmentCloneStatus as EnvironmentCloneStatusType,
)
from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    Cluster,
    Deployment,
    Environment,
    EnvironmentBackup,
    EnvironmentClone,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.backup.clone import (
    CLONE_REASON_NOT_ELIGIBLE,
    CLONE_REASON_NOT_SELECTED,
    CLONE_STEP_CAPTURE_FAILED,
    CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
    CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
    EnvironmentCloneDeploymentOutcome,
    EnvironmentCloneStatus,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from styrmin_backend.workflows.templates import clone as clone_flow

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

# The clone surface reuses the environment-backup harness rather than copying
# it: ``fresh_client`` (resolvers on a second session over the same engine),
# ``read_write_client`` (authenticated one rung below ADMIN) and
# ``seed_running_deployment`` (a deployment wired to an active instance with a
# valid context — which is what makes it *eligible*) are exactly what this
# module needs. The first two are imported for their fixture side effect, hence
# the noqa.
from .test_environment_backup import (  # noqa: F401
    fresh_client_fixture,
    read_write_client_fixture,
    seed_running_deployment,
)

#: A ``deployment_results`` entry that names a restore id which no longer
#: resolves to a row — the cascade-deleted case whose recorded outcome must
#: stand (``data-model.md`` resolution rule 1).
MISSING_RESTORE = "missing-restore"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _result_entry(
    *,
    deployment_id: UUID,
    deployment_name: str,
    outcome: str,
    reason: str | None = None,
    counterpart_deployment_id: UUID | None = None,
    restore_id: UUID | None = None,
) -> dict[str, Any]:
    """One JSON ``deployment_results`` entry, exactly as the service writes it."""
    return {
        "deployment_id": str(deployment_id),
        "deployment_name": deployment_name,
        "outcome": outcome,
        "reason": reason,
        "counterpart_deployment_id": (
            str(counterpart_deployment_id) if counterpart_deployment_id else None
        ),
        "restore_id": str(restore_id) if restore_id else None,
    }


async def _sibling_environment(
    session: AsyncSession, source: Environment, name: str
) -> Environment:
    """Seed a second environment in ``source``'s cluster.

    ``source.cluster`` is lazy on a committed row, so the cluster is re-read by
    id rather than walked off the relationship (which would raise
    ``MissingGreenlet`` under the async session).
    """
    cluster = await session.get(Cluster, source.cluster_id)
    assert cluster is not None
    return await seed_environment(session, cluster=cluster, name=name)


async def _seed_capture(
    session: AsyncSession,
    *,
    environment: Environment,
    instance: ApplicationInstance,
    constituent_statuses: Sequence[BackupStatus],
    error_count: int = 0,
) -> EnvironmentBackup:
    """Seed an ``EnvironmentBackup`` whose *derived* status is what we want.

    The capture's status is itself derived, so it is expressed the only way it
    honestly can be: through the constituent ``Backup`` rows and the recorded
    ``constituent_errors``.
    """
    capture = EnvironmentBackup(
        name=f"capture-{uuid4().hex[:8]}",
        environment_id=environment.id,
        environment_config=environment.config,
        constituent_errors=[
            {
                "deployment_id": str(uuid4()),
                "deployment_name": f"errored-{index}",
                "error": "backup already in progress",
            }
            for index in range(error_count)
        ]
        or None,
    )
    session.add(capture)
    await session.commit()
    for index, status in enumerate(constituent_statuses):
        session.add(
            Backup(
                name=f"constituent-{index}-{uuid4().hex[:8]}",
                status=status,
                instance_id=instance.id,
                environment_backup_id=capture.id,
            )
        )
    await session.commit()
    return capture


async def _seed_restore(
    session: AsyncSession,
    *,
    instance: ApplicationInstance,
    status: RestoreStatus,
) -> Restore:
    """Seed a constituent cross-target ``Restore`` (with the backup it needs)."""
    backup = Backup(
        name=f"restored-from-{uuid4().hex[:8]}",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    session.add(backup)
    await session.commit()
    restore = Restore(
        name=f"restore-{uuid4().hex[:8]}",
        status=status,
        target_namespace=f"ns-{uuid4().hex[:6]}",
        backup_id=backup.id,
    )
    session.add(restore)
    await session.commit()
    return restore


async def _seed_clone(
    session: AsyncSession,
    *,
    source: Environment,
    instance: ApplicationInstance,
    name: str | None = None,
    capture_statuses: Sequence[BackupStatus] | None = None,
    capture_error_count: int = 0,
    created_environment: Environment | None = None,
    results: Sequence[tuple[str, Any]] = (),
    clone_errors: Sequence[dict[str, Any]] | None = None,
    created_on: datetime | None = None,
) -> EnvironmentClone:
    """Seed a clone record in an arbitrary real state.

    ``results`` is a list of ``(outcome, restore)`` pairs where ``restore`` is
    ``None`` (no restore dispatched), a :class:`RestoreStatus` (a row is seeded
    at that status), or :data:`MISSING_RESTORE` (an id is written but no row
    exists — the cascade-deleted case).
    """
    capture = (
        await _seed_capture(
            session,
            environment=source,
            instance=instance,
            constituent_statuses=capture_statuses,
            error_count=capture_error_count,
        )
        if capture_statuses is not None
        else None
    )

    entries: list[dict[str, Any]] = []
    for index, (outcome, restore_spec) in enumerate(results):
        restore_id: UUID | None = None
        if restore_spec == MISSING_RESTORE:
            restore_id = uuid4()
        elif restore_spec is not None:
            restore = await _seed_restore(
                session, instance=instance, status=restore_spec
            )
            restore_id = restore.id
        attributed = outcome in (
            EnvironmentCloneDeploymentOutcome.SKIPPED.value,
            EnvironmentCloneDeploymentOutcome.FAILED.value,
        )
        entries.append(
            _result_entry(
                deployment_id=uuid4(),
                deployment_name=f"app-{index}",
                outcome=outcome,
                reason=CLONE_REASON_NOT_ELIGIBLE if attributed else None,
                counterpart_deployment_id=(
                    uuid4()
                    if outcome == EnvironmentCloneDeploymentOutcome.CLONED.value
                    else None
                ),
                restore_id=restore_id,
            )
        )

    clone = EnvironmentClone(
        name=name or f"clone-{uuid4().hex[:8]}",
        source_environment_id=source.id,
        source_environment_name=source.name,
        environment_backup_id=capture.id if capture else None,
        created_environment_id=created_environment.id if created_environment else None,
        deployment_results=entries or None,
        clone_errors=list(clone_errors) if clone_errors else None,
    )
    if created_on is not None:
        clone.created_on = created_on
    session.add(clone)
    await session.commit()
    return clone


async def _seed_source_with_instance(
    session: AsyncSession,
) -> tuple[Environment, ApplicationInstance]:
    """A source environment plus one active instance to hang seeded rows off."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    _deployment, instance = await seed_running_deployment(
        session, environment=environment, adv=adv, name="seeded-app"
    )
    return environment, instance


# ---------------------------------------------------------------------------
# cloneEnvironment — write propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_environment_persists_clone_capture_links_and_upfront_skips(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The clone record, its capture, the link between them and the skips that
    are already knowable at registration must all reach the database.
    """
    source = await seed_environment(session, name="prod")
    source.config = {"fqdn_suffix": "prod.example.com"}
    session.add(source)
    await session.commit()
    adv = await seed_application_driver_version(session)
    infrahub, infrahub_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="infrahub"
    )
    netbox, netbox_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="netbox"
    )
    # No active instance: eligible by topology but with nothing to capture, so
    # it is an attributed skip rather than an error (FR-004).
    never_deployed = await seed_deployment(
        session, environment=source, adv=adv, name="never-deployed"
    )
    # Platform infrastructure: the clone gets its own ingress controller, so the
    # source's is deliberately absent from the attribution list.
    await seed_running_deployment(
        session, environment=source, adv=adv, name="ingress", internal=True
    )

    data = await gql(
        fresh_client,
        "clone_environment",
        {"environmentId": str(source.id), "name": "prod-rehearsal"},
    )
    payload = data["cloneEnvironment"]

    # --- The clone row reached the database ----------------------------
    persisted = await session.get(EnvironmentClone, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.name == "prod-rehearsal"
    assert persisted.source_environment_id == source.id
    assert persisted.source_environment_name == "prod"
    assert persisted.created_environment_id is None
    assert persisted.requested_deployment_ids is None
    assert persisted.config_override is None
    assert persisted.cleared_config_fields is None
    assert persisted.clone_errors is None

    # --- The capture, and the link to it, reached the database ---------
    assert persisted.environment_backup_id is not None
    capture = await session.get(EnvironmentBackup, persisted.environment_backup_id)
    assert capture is not None
    assert capture.environment_id == source.id
    assert capture.environment_config == {"fqdn_suffix": "prod.example.com"}
    assert capture.deployment_snapshots is not None
    assert {raw["deployment_name"] for raw in capture.deployment_snapshots} == {
        "infrahub",
        "netbox",
    }
    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == capture.id)
    )
    constituents = list(result.all())
    assert {backup.instance_id for backup in constituents} == {
        infrahub_instance.id,
        netbox_instance.id,
    }
    assert all(backup.status is BackupStatus.PENDING for backup in constituents)

    # --- Every source deployment is accounted for (SC-003) -------------
    assert persisted.deployment_results is not None
    by_name = {raw["deployment_name"]: raw for raw in persisted.deployment_results}
    assert set(by_name) == {"infrahub", "netbox", "never-deployed"}
    assert by_name["infrahub"]["deployment_id"] == str(infrahub.id)
    assert by_name["infrahub"]["outcome"] == "pending"
    assert by_name["infrahub"]["reason"] is None
    assert by_name["netbox"]["deployment_id"] == str(netbox.id)
    assert by_name["netbox"]["outcome"] == "pending"
    assert by_name["never-deployed"]["deployment_id"] == str(never_deployed.id)
    assert by_name["never-deployed"]["outcome"] == "skipped"
    assert by_name["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE

    # --- The response projects the same state --------------------------
    # IN_PROGRESS, not PENDING: an upfront skip is recorded progress, so the
    # derivation's "capture queued and nothing else recorded" rule no longer
    # applies (see ``derive_environment_clone_status``). The capture itself is
    # still PENDING, and the matrix below covers the PENDING projection.
    assert payload["status"] == "IN_PROGRESS"
    assert payload["name"] == "prod-rehearsal"
    assert payload["sourceEnvironmentName"] == "prod"
    assert payload["sourceEnvironment"]["id"] == str(source.id)
    assert payload["environmentBackup"]["id"] == str(capture.id)
    assert payload["environmentBackup"]["status"] == "PENDING"
    assert {
        snapshot["deploymentName"]
        for snapshot in payload["environmentBackup"]["deploymentSnapshots"]
    } == {"infrahub", "netbox"}
    assert payload["createdEnvironment"] is None
    assert payload["requestedDeploymentIds"] is None
    assert payload["configOverride"] is None
    assert payload["clearConfigFields"] is None
    assert payload["cloneErrors"] == []
    assert payload["createdOn"] is not None
    wire = {row["deploymentName"]: row for row in payload["deploymentResults"]}
    assert set(wire) == {"infrahub", "netbox", "never-deployed"}
    assert wire["infrahub"]["outcome"] == "PENDING"
    assert wire["infrahub"]["counterpartDeploymentId"] is None
    assert wire["infrahub"]["restoreId"] is None
    assert wire["never-deployed"]["outcome"] == "SKIPPED"
    assert wire["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_clone_environment_persists_selection_override_and_cleared_fields(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``deploymentIds`` / ``configOverride`` / ``clearConfigFields`` ride the
    contract from the start, so each must reach the row it is persisted on and
    project back. (Their *semantics* — what the cloned environment ends up
    with — belong to the selection and override stories.)
    """
    source = await seed_environment(session, name="prod-2")
    source.config = {"fqdn_suffix": "prod.example.com", "ingress_class": "prod-nginx"}
    session.add(source)
    await session.commit()
    adv = await seed_application_driver_version(session)
    included, _included_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="included"
    )
    excluded, _excluded_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="excluded"
    )

    data = await gql(
        fresh_client,
        "clone_environment",
        {
            "environmentId": str(source.id),
            "name": "prod-2-rehearsal",
            "deploymentIds": [str(included.id)],
            "configOverride": {"fqdnSuffix": "rehearsal.example.com"},
            "clearConfigFields": ["ingress_class"],
        },
    )
    payload = data["cloneEnvironment"]

    persisted = await session.get(EnvironmentClone, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.requested_deployment_ids == [str(included.id)]
    # Stored canonical (the ``EnvironmentConfig`` round-trip), snake_case — not
    # the camelCase the wire used.
    assert persisted.config_override == {"fqdn_suffix": "rehearsal.example.com"}
    assert persisted.cleared_config_fields == ["ingress_class"]

    results = persisted.deployment_results or []
    by_name = {raw["deployment_name"]: raw for raw in results}
    assert by_name["included"]["outcome"] == "pending"
    assert by_name["excluded"]["outcome"] == "skipped"
    assert by_name["excluded"]["reason"] == CLONE_REASON_NOT_SELECTED
    assert by_name["excluded"]["deployment_id"] == str(excluded.id)

    assert payload["requestedDeploymentIds"] == [str(included.id)]
    assert payload["configOverride"] == {"fqdn_suffix": "rehearsal.example.com"}
    assert payload["clearConfigFields"] == ["ingress_class"]


# ---------------------------------------------------------------------------
# cloneEnvironment — deployment selection (US2: FR-003 / FR-004)
# ---------------------------------------------------------------------------
#
# ``deploymentIds`` is only honoured if it reaches the *capture*: the clone is
# built entirely from that capture and never re-reads the live source (FR-007),
# so a selection that shaped the attribution list but not the snapshot would
# still clone an excluded deployment. Both halves are asserted from a second
# session, against the rows themselves.


@pytest.mark.asyncio
async def test_clone_environment_with_a_selection_captures_only_the_selection(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-003/FR-004: the selection filters the capture; an ineligible pick is a skip.

    The selection here names one eligible deployment *and* one that has never
    been deployed. The first is captured; the second is attributed as skipped
    with a reason rather than failing the request (FR-004); the deployment that
    was not named is attributed as unselected.
    """
    source = await seed_environment(session, name="prod-selection")
    adv = await seed_application_driver_version(session)
    included, included_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="included"
    )
    excluded, excluded_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="excluded"
    )
    selected_but_ineligible = await seed_deployment(
        session, environment=source, adv=adv, name="never-deployed"
    )

    data = await gql(
        fresh_client,
        "clone_environment",
        {
            "environmentId": str(source.id),
            "name": "prod-selection-rehearsal",
            "deploymentIds": [str(included.id), str(selected_but_ineligible.id)],
        },
    )
    payload = data["cloneEnvironment"]

    persisted = await session.get(EnvironmentClone, UUID(payload["id"]))
    assert persisted is not None
    assert persisted.requested_deployment_ids == [
        str(included.id),
        str(selected_but_ineligible.id),
    ]

    # --- The capture holds the selection, and only the selection ------
    capture = await session.get(EnvironmentBackup, persisted.environment_backup_id)
    assert capture is not None
    assert {raw["deployment_name"] for raw in capture.deployment_snapshots or []} == {
        "included"
    }
    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == capture.id)
    )
    constituents = list(result.all())
    assert [backup.instance_id for backup in constituents] == [included_instance.id]
    assert excluded_instance.id not in {backup.instance_id for backup in constituents}

    # --- Every source deployment is still accounted for (SC-003) -------
    by_name = {
        raw["deployment_name"]: raw for raw in persisted.deployment_results or []
    }
    assert set(by_name) == {"included", "excluded", "never-deployed"}
    assert by_name["included"]["outcome"] == "pending"
    assert by_name["excluded"]["outcome"] == "skipped"
    assert by_name["excluded"]["reason"] == CLONE_REASON_NOT_SELECTED
    assert by_name["excluded"]["deployment_id"] == str(excluded.id)
    assert by_name["never-deployed"]["outcome"] == "skipped"
    assert by_name["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE

    # --- The response projects the same shape --------------------------
    assert {
        snapshot["deploymentName"]
        for snapshot in payload["environmentBackup"]["deploymentSnapshots"]
    } == {"included"}
    wire = {row["deploymentName"]: row for row in payload["deploymentResults"]}
    assert wire["excluded"]["outcome"] == "SKIPPED"
    assert wire["excluded"]["reason"] == CLONE_REASON_NOT_SELECTED
    assert wire["never-deployed"]["outcome"] == "SKIPPED"
    assert wire["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_clone_environment_without_a_selection_captures_every_eligible_deployment(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-003: omitting ``deploymentIds`` includes all eligible, and nothing else.

    The contrast with the test above is the point: same topology, no selection,
    so both eligible deployments are captured and *no* entry carries the
    unselected reason. The never-deployed deployment is still a skip with a
    reason — ineligibility does not depend on how the selection was expressed.
    """
    source = await seed_environment(session, name="prod-no-selection")
    adv = await seed_application_driver_version(session)
    first, first_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="first"
    )
    second, second_instance = await seed_running_deployment(
        session, environment=source, adv=adv, name="second"
    )
    never_deployed = await seed_deployment(
        session, environment=source, adv=adv, name="never-deployed"
    )

    data = await gql(
        fresh_client,
        "clone_environment",
        {
            "environmentId": str(source.id),
            "name": "prod-no-selection-rehearsal",
        },
    )
    payload = data["cloneEnvironment"]

    persisted = await session.get(EnvironmentClone, UUID(payload["id"]))
    assert persisted is not None
    # ``None``, not ``[]``: "no selection" and "an empty selection" are
    # different requests and the row keeps them apart.
    assert persisted.requested_deployment_ids is None

    capture = await session.get(EnvironmentBackup, persisted.environment_backup_id)
    assert capture is not None
    assert {raw["deployment_name"] for raw in capture.deployment_snapshots or []} == {
        "first",
        "second",
    }
    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == capture.id)
    )
    assert {backup.instance_id for backup in result.all()} == {
        first_instance.id,
        second_instance.id,
    }

    by_name = {
        raw["deployment_name"]: raw for raw in persisted.deployment_results or []
    }
    assert set(by_name) == {"first", "second", "never-deployed"}
    assert by_name["first"]["deployment_id"] == str(first.id)
    assert by_name["second"]["deployment_id"] == str(second.id)
    assert {by_name["first"]["outcome"], by_name["second"]["outcome"]} == {"pending"}
    assert by_name["first"]["reason"] is None
    assert by_name["second"]["reason"] is None
    assert CLONE_REASON_NOT_SELECTED not in {
        raw["reason"] for raw in persisted.deployment_results or []
    }
    # FR-004: the ineligible deployment is reported, not raised.
    assert by_name["never-deployed"]["deployment_id"] == str(never_deployed.id)
    assert by_name["never-deployed"]["outcome"] == "skipped"
    assert by_name["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE
    assert payload["cloneErrors"] == []


@pytest.mark.asyncio
async def test_clone_environment_requires_admin(
    session: AsyncSession, read_write_client: AsyncClient, prefect_manager_mock
) -> None:
    """FR-010: a clone writes an environment config and creates deployments, so
    it is gated at ADMIN — strictly superseding ``restoreEnvironmentBackup``.
    """
    source = await seed_environment(session, name="prod-3")

    response = await read_write_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {"environmentId": str(source.id), "name": "nope"},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "FORBIDDEN"

    # Rejected before any write: no clone row, no capture.
    clones = await session.exec(select(EnvironmentClone))
    assert list(clones.all()) == []
    captures = await session.exec(select(EnvironmentBackup))
    assert list(captures.all()) == []


# ---------------------------------------------------------------------------
# cloneEnvironment — upfront typed errors, zero side effects (FR-011)
# ---------------------------------------------------------------------------


async def _assert_no_clone_was_written(session: AsyncSession) -> None:
    """FR-011: an upfront rejection costs a typed error and nothing else."""
    clones = await session.exec(select(EnvironmentClone))
    assert list(clones.all()) == []


@pytest.mark.asyncio
async def test_clone_environment_rejects_a_taken_target_name(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-011: the target name is already an environment in the cluster."""
    source, _instance = await _seed_source_with_instance(session)
    await _sibling_environment(session, source, "already-there")

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {
                "environmentId": str(source.id),
                "name": "already-there",
            },
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "ALREADY_EXISTS"
    await _assert_no_clone_was_written(session)
    # Not even the capture was registered.
    captures = await session.exec(select(EnvironmentBackup))
    assert list(captures.all()) == []


@pytest.mark.asyncio
async def test_clone_environment_rejects_an_unknown_source_environment(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-011: the source is resolved (ADR-031) before anything is written."""
    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {"environmentId": str(uuid4()), "name": "orphan-clone"},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "NOT_FOUND"
    await _assert_no_clone_was_written(session)


@pytest.mark.asyncio
async def test_clone_environment_rejects_an_unknown_selected_deployment(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-011: a selected id that names nothing is refused before any write.

    Unlike an ineligible pick (attributed as a skip — FR-004), an id the source
    does not have cannot be attributed to anything, so it is a typed
    ``NOT_FOUND`` naming the offenders and nothing else happens.
    """
    source, _instance = await _seed_source_with_instance(session)
    ghost = uuid4()

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {
                "environmentId": str(source.id),
                "name": "ghost-selection",
                "deploymentIds": [str(ghost)],
            },
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "NOT_FOUND"
    assert errors[0]["extensions"]["deployment_ids"] == [str(ghost)]
    await _assert_no_clone_was_written(session)
    # Not even the capture was registered (FR-011: zero side effects).
    captures = await session.exec(select(EnvironmentBackup))
    assert list(captures.all()) == []


@pytest.mark.asyncio
async def test_clone_environment_rejects_a_deployment_from_another_environment(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-011: a foreign deployment id is a typo, not a skip.

    It exists — so a naive "does this row exist?" check would let it through —
    but it belongs to a different environment, and cloning another
    environment's deployment is never what the caller meant.
    """
    source, _instance = await _seed_source_with_instance(session)
    neighbour = await _sibling_environment(session, source, "neighbour")
    adv = await seed_application_driver_version(session)
    foreign, _foreign_instance = await seed_running_deployment(
        session, environment=neighbour, adv=adv, name="foreign"
    )

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {
                "environmentId": str(source.id),
                "name": "foreign-selection",
                "deploymentIds": [str(foreign.id)],
            },
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "NOT_FOUND"
    assert errors[0]["extensions"]["deployment_ids"] == [str(foreign.id)]
    await _assert_no_clone_was_written(session)
    captures = await session.exec(select(EnvironmentBackup))
    assert list(captures.all()) == []


@pytest.mark.asyncio
async def test_clone_environment_rejects_a_concurrent_operation(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """D8: an environment-level operation already occupies the source."""
    source, instance = await _seed_source_with_instance(session)
    in_flight = EnvironmentBackup(name="in-flight", environment_id=source.id)
    session.add(in_flight)
    await session.commit()
    session.add(
        Backup(
            name="in-flight-constituent",
            status=BackupStatus.PENDING,
            instance_id=instance.id,
            environment_backup_id=in_flight.id,
        )
    )
    await session.commit()

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {"environmentId": str(source.id), "name": "too-soon"},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "ALREADY_IN_PROGRESS"
    assert errors[0]["extensions"]["operation_kind"] == "environment_backup"
    await _assert_no_clone_was_written(session)
    # The in-flight operation is untouched — no second capture was registered.
    result = await session.exec(
        select(EnvironmentBackup).where(EnvironmentBackup.environment_id == source.id)
    )
    assert [capture.id for capture in result.all()] == [in_flight.id]


@pytest.mark.asyncio
async def test_clone_environment_rejects_an_unknown_clear_config_field(
    fresh_client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """FR-011: ``clearConfigFields`` is validated upfront, not inside the flow."""
    source, _instance = await _seed_source_with_instance(session)

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("clone_environment"),
            "variables": {
                "environmentId": str(source.id),
                "name": "bad-clear",
                "clearConfigFields": ["not_a_config_field"],
            },
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "VALIDATION_ERROR"
    await _assert_no_clone_was_written(session)


# ---------------------------------------------------------------------------
# cloneEnvironment — config override semantics (US3: FR-006)
# ---------------------------------------------------------------------------
#
# ``configOverride`` and ``clearConfigFields`` are persisted by the mutation
# (covered above) but only *mean* something downstream of it: the merge runs
# inside ``EXECUTE_ENVIRONMENT_CLONE``, over the captured config, and its result
# is both the created environment's config and the config every counterpart's
# first instance context is resolved from. A test that stopped at the mutation
# response would pass on an implementation that stored the override and then
# ignored it.
#
# So these tests register the clone through GraphQL, drive its capture terminal
# in the database, run the real flow over the test session, and assert on the
# rows it wrote — re-read after ``expire_all()`` so nothing is answered out of
# the identity map.


def _set_fields(config: dict[str, Any]) -> dict[str, Any]:
    """Drop the ``None``-valued keys of a rendered config section.

    A resolved context carries every ``EnvironmentConfig`` field, unset ones as
    nulls, while the stored config carries only what was set. Comparing the set
    fields makes "the override landed and the cleared field did not" a single
    equality rather than a field-by-field walk.
    """
    return {key: value for key, value in config.items() if value is not None}


async def _complete_capture_constituents(
    session: AsyncSession, environment_backup_id: UUID
) -> None:
    """Drive a registered capture's constituents to ``COMPLETED``.

    The clone flow gates on the capture's *derived* status, so making the
    capture restorable means making its constituent ``Backup`` rows terminal —
    there is no parent status column to set.
    """
    result = await session.exec(
        select(Backup).where(Backup.environment_backup_id == environment_backup_id)
    )
    # NOTE: commit each row separately. Mutating two dirty rows of the same
    # table in one flush triggers SQLAlchemy's bulk UPDATE path, which raises
    # ``InvalidRequestError`` on SQLite because ``updated_on``'s
    # ``onupdate=func.now()`` renders as a postcompile ``strftime(...)`` and
    # postcompile / ``literal_execute`` params cannot be used with
    # ``executemany()``. Same workaround as
    # ``test_application_driver_created_on_distinct_versions``.
    for backup in result.all():
        backup.status = BackupStatus.COMPLETED
        session.add(backup)
        await session.commit()


async def _run_clone_flow(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, clone_id: UUID
) -> list[dict[str, Any]]:
    """Run ``EXECUTE_ENVIRONMENT_CLONE`` against the test session.

    Only the flow's two outbound edges are replaced:

    * ``get_unit_of_work`` — the flow builds units of work from the global
      engine; here it must use the test session's;
    * ``create_restore`` / ``get_manager`` — the Kubernetes-facing dispatch,
      which has its own suite in
      ``backend/tests/unit/services/backup/test_restore.py``. It is stubbed
      rather than run because a counterpart is created in ``RESTORING`` and
      ``create_restore``'s concurrency guard refuses a ``RESTORING`` target —
      an interaction owned by US1, not by the config merge under test here.

    Everything the merge touches runs for real: the capture gate, the merge
    itself, ``create_environment`` (capabilities recomputed rather than
    copied — ADR-0027) and ``deploy_application`` with its service rows and
    instance-context generation.

    Returns:
        The keyword arguments of every cross-target restore the flow created.
    """
    restore_calls: list[dict[str, Any]] = []
    uow = SqlModelUnitOfWork(session=session)

    async def _get_unit_of_work() -> SqlModelUnitOfWork:
        return uow

    async def _create_restore(**kwargs: Any) -> tuple[Restore, UUID]:
        restore_calls.append(kwargs)
        restore_id = uuid4()
        restore = Restore(
            id=restore_id,
            name=f"styrmin-{restore_id}",
            status=RestoreStatus.PENDING,
            target_namespace=kwargs["target_namespace"],
            backup_id=kwargs["backup_id"],
        )
        session.add(restore)
        await session.commit()
        return restore, kwargs["target_deployment_id"]

    class _Manager:
        async def run_action(self, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr(clone_flow, "get_unit_of_work", _get_unit_of_work)
    monkeypatch.setattr(clone_flow, "get_run_logger", lambda: logging.getLogger("test"))
    monkeypatch.setattr(clone_flow, "create_restore", _create_restore)
    monkeypatch.setattr(clone_flow, "get_manager", lambda: _Manager())

    await clone_flow.execute_environment_clone_workflow.fn(str(clone_id))
    return restore_calls


async def _clone_and_materialise(
    fresh_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    variables: dict[str, Any],
) -> EnvironmentClone:
    """Register a clone through GraphQL and run it to its counterparts.

    Returns the clone record re-read from the database with everything the flow
    wrote on it.
    """
    data = await gql(fresh_client, "clone_environment", variables)
    clone_id = UUID(data["cloneEnvironment"]["id"])

    registered = await session.get(EnvironmentClone, clone_id)
    assert registered is not None
    assert registered.environment_backup_id is not None
    await _complete_capture_constituents(session, registered.environment_backup_id)

    await _run_clone_flow(session, monkeypatch, clone_id)

    session.expire_all()
    materialised = await session.get(EnvironmentClone, clone_id)
    assert materialised is not None
    assert materialised.created_environment_id is not None, (
        f"the clone never materialised an environment: {materialised.clone_errors}"
    )
    return materialised


async def _counterpart_instance_context(
    session: AsyncSession, clone: EnvironmentClone, deployment_name: str
) -> dict[str, Any]:
    """The first instance context of a cloned deployment's counterpart."""
    entries = {
        entry["deployment_name"]: entry for entry in clone.deployment_results or []
    }
    entry = entries[deployment_name]
    assert entry["outcome"] == EnvironmentCloneDeploymentOutcome.CLONED.value, entry
    counterpart = await session.get(
        Deployment, UUID(entry["counterpart_deployment_id"])
    )
    assert counterpart is not None
    assert counterpart.environment_id == clone.created_environment_id
    assert counterpart.active_application_instance_id is not None
    instance = await session.get(
        ApplicationInstance, counterpart.active_application_instance_id
    )
    assert instance is not None and instance.context is not None
    return instance.context


@pytest.mark.asyncio
async def test_clone_environment_creates_the_environment_from_the_merged_config(
    fresh_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    prefect_manager_mock,
) -> None:
    """FR-006: override merged over the capture, cleared field gone entirely.

    Spec US3 scenarios 1 and 3 in one materialisation: ``fqdn_suffix`` is
    replaced, ``ingress_class`` is **absent** from the created config (not null,
    not a default), and the untouched ``db_size`` survives from the capture.
    """
    source = await seed_environment(session, name="prod-us3-merge")
    source.config = {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
        "db_size": "50Gi",
    }
    session.add(source)
    await session.commit()
    adv = await seed_application_driver_version(session)
    await seed_running_deployment(session, environment=source, adv=adv, name="infrahub")
    # Held before materialising: ``_clone_and_materialise`` expires the identity
    # map, after which attribute access on ``source`` would lazy-load.
    source_id = source.id

    clone = await _clone_and_materialise(
        fresh_client,
        session,
        monkeypatch,
        {
            "environmentId": str(source_id),
            "name": "prod-us3-merge-rehearsal",
            "configOverride": {"fqdnSuffix": "rehearsal.example.com"},
            "clearConfigFields": ["ingress_class"],
        },
    )

    assert clone.created_environment_id is not None
    created = await session.get(Environment, clone.created_environment_id)
    assert created is not None
    assert created.config == {
        "fqdn_suffix": "rehearsal.example.com",
        "db_size": "50Gi",
    }
    # Absent, not present-and-null: a cleared field must not reappear as a key
    # the renderer can read back as an empty value.
    assert "ingress_class" not in (created.config or {})

    # SC-002: the source and the capture it was read from are untouched.
    # Re-read rather than walked off the seeded instance: materialising the
    # clone expired the identity map, so the attribute would lazy-load.
    reloaded_source = await session.get(Environment, source_id)
    assert reloaded_source is not None
    assert reloaded_source.config == {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
        "db_size": "50Gi",
    }
    assert clone.environment_backup_id is not None
    capture = await session.get(EnvironmentBackup, clone.environment_backup_id)
    assert capture is not None
    assert capture.environment_config == {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
        "db_size": "50Gi",
    }

    # The clone row still reports the request that produced it, canonicalised.
    assert clone.config_override == {"fqdn_suffix": "rehearsal.example.com"}
    assert clone.cleared_config_fields == ["ingress_class"]

    # ...and the read surface projects the created environment's merged config.
    payload = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    assert payload["environmentClone"]["createdEnvironment"]["id"] == str(created.id)


@pytest.mark.asyncio
async def test_cloned_counterparts_first_instance_context_uses_the_merged_config(
    fresh_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    prefect_manager_mock,
) -> None:
    """FR-006: the merge lands before any counterpart comes up.

    This is the non-interference guarantee proper. A counterpart's *first*
    instance context is resolved by ``generate_instance_from_deployment`` from
    the environment row, so if the merge happened after counterpart creation the
    first context — the one the initial reconcile would render from — would
    still carry production configuration.
    """
    source = await seed_environment(session, name="prod-us3-context")
    source.config = {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
        "env_vars": {"SMTP_HOST": "smtp.prod.example.com"},
    }
    session.add(source)
    await session.commit()
    adv = await seed_application_driver_version(session)
    await seed_running_deployment(session, environment=source, adv=adv, name="infrahub")
    source_id = source.id

    clone = await _clone_and_materialise(
        fresh_client,
        session,
        monkeypatch,
        {
            "environmentId": str(source_id),
            "name": "prod-us3-context-rehearsal",
            "configOverride": {
                "fqdnSuffix": "rehearsal.example.com",
                "envVars": [{"name": "SMTP_HOST", "value": "localhost"}],
            },
            "clearConfigFields": ["ingress_class"],
        },
    )

    merged = {
        "fqdn_suffix": "rehearsal.example.com",
        "env_vars": {"SMTP_HOST": "localhost"},
    }
    assert clone.config_override == merged

    context = await _counterpart_instance_context(session, clone, "infrahub")
    # The context carries the whole ``EnvironmentConfig`` shape, so unset fields
    # are present as nulls; what matters is that the *set* fields are exactly
    # the merged config — the cleared ``ingress_class`` among the nulls.
    assert _set_fields(context["environment"]["config"]) == merged
    assert context["environment"]["config"]["ingress_class"] is None
    # The resolved (deepest-wins) config the renderer actually reads, too.
    assert context["instance"]["config"]["fqdn_suffix"] == "rehearsal.example.com"
    assert context["instance"]["config"]["ingress_class"] is None
    assert context["instance"]["config"]["env_vars"] == {"SMTP_HOST": "localhost"}

    # SC-002: the source environment is byte-identical to before the clone.
    reloaded_source = await session.get(Environment, source_id)
    assert reloaded_source is not None
    assert reloaded_source.config == {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
        "env_vars": {"SMTP_HOST": "smtp.prod.example.com"},
    }


@pytest.mark.asyncio
async def test_clone_environment_without_an_override_copies_the_captured_config(
    fresh_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    prefect_manager_mock,
) -> None:
    """Spec US3 scenario 2: no override → the clone's config *is* the capture's.

    The negative control for the two tests above: the same materialisation path,
    with nothing overridden and nothing cleared, must reproduce the captured
    config verbatim in both the environment row and the counterpart's first
    instance context.
    """
    source = await seed_environment(session, name="prod-us3-plain")
    source.config = {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
    }
    session.add(source)
    await session.commit()
    adv = await seed_application_driver_version(session)
    await seed_running_deployment(session, environment=source, adv=adv, name="infrahub")
    source_id = source.id

    clone = await _clone_and_materialise(
        fresh_client,
        session,
        monkeypatch,
        {
            "environmentId": str(source_id),
            "name": "prod-us3-plain-rehearsal",
        },
    )

    captured = {"fqdn_suffix": "prod.example.com", "ingress_class": "prod-nginx"}
    assert clone.config_override is None
    assert clone.cleared_config_fields is None
    assert clone.created_environment_id is not None
    created = await session.get(Environment, clone.created_environment_id)
    assert created is not None and created.config == captured

    context = await _counterpart_instance_context(session, clone, "infrahub")
    assert _set_fields(context["environment"]["config"]) == captured


# ---------------------------------------------------------------------------
# environmentClone — derived-status projection from real DB state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "capture_statuses",
        "with_created_environment",
        "results",
        "clone_errors",
        "expected",
    ),
    [
        pytest.param(
            [BackupStatus.PENDING],
            False,
            [("pending", None)],
            None,
            "PENDING",
            id="capture-queued-nothing-progressed",
        ),
        pytest.param(
            [BackupStatus.IN_PROGRESS],
            False,
            [("pending", None)],
            None,
            "IN_PROGRESS",
            id="capture-still-running",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            False,
            [("pending", None)],
            None,
            "IN_PROGRESS",
            id="capture-terminal-environment-not-materialised",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            True,
            [("pending", None)],
            None,
            "IN_PROGRESS",
            id="an-entry-is-still-pending",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            True,
            [("cloned", RestoreStatus.IN_PROGRESS)],
            None,
            "IN_PROGRESS",
            id="a-referenced-restore-is-still-running",
        ),
        pytest.param(
            [BackupStatus.COMPLETED, BackupStatus.COMPLETED],
            True,
            [("cloned", RestoreStatus.COMPLETED), ("cloned", RestoreStatus.COMPLETED)],
            None,
            "COMPLETED",
            id="every-entry-cloned",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            True,
            [("skipped", None), ("skipped", None)],
            None,
            "COMPLETED",
            id="all-skipped-is-not-a-failure",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            True,
            [("cloned", MISSING_RESTORE)],
            None,
            "COMPLETED",
            id="cascade-deleted-restore-keeps-the-recorded-outcome",
        ),
        pytest.param(
            [BackupStatus.COMPLETED, BackupStatus.FAILED],
            True,
            [("cloned", RestoreStatus.COMPLETED), ("failed", None)],
            None,
            "PARTIAL",
            id="partial-capture-attributes-the-failed-constituent",
        ),
        pytest.param(
            [BackupStatus.COMPLETED, BackupStatus.COMPLETED],
            True,
            [("cloned", RestoreStatus.FAILED), ("cloned", RestoreStatus.COMPLETED)],
            None,
            "PARTIAL",
            id="a-cloned-entry-whose-restore-failed",
        ),
        pytest.param(
            [BackupStatus.COMPLETED, BackupStatus.FAILED],
            True,
            [("failed", None), ("failed", None)],
            None,
            "FAILED",
            id="every-included-entry-failed",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            True,
            [("cloned", RestoreStatus.COMPLETED)],
            [
                {
                    "step": CLONE_STEP_CAPTURE_FAILED,
                    "error": "the capture never became restorable",
                    "fatal": True,
                }
            ],
            "FAILED",
            id="a-fatal-clone-error-wins",
        ),
        pytest.param(
            [BackupStatus.COMPLETED],
            False,
            [("cloned", RestoreStatus.COMPLETED)],
            [
                {
                    "step": CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
                    "error": "discarded by the operator",
                    "fatal": False,
                }
            ],
            "COMPLETED",
            id="discarding-a-finished-clone-does-not-rewrite-it",
        ),
        pytest.param(
            None,
            False,
            [("pending", None)],
            [
                {
                    "step": CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
                    "error": "the backing capture was deleted",
                    "fatal": True,
                }
            ],
            "FAILED",
            id="the-escape-hatch-ends-a-stuck-clone",
        ),
    ],
)
async def test_environment_clone_projects_derived_status_from_the_database(
    fresh_client: AsyncClient,
    session: AsyncSession,
    capture_statuses: list[BackupStatus] | None,
    with_created_environment: bool,
    results: list[tuple[str, Any]],
    clone_errors: list[dict[str, Any]] | None,
    expected: str,
) -> None:
    """FR-009: the resolver derives the status from persisted rows on every read.

    Nothing here goes through the mutation — the state is seeded directly so the
    derivation is exercised against DB state it could not have cached.
    """
    source, instance = await _seed_source_with_instance(session)
    created = (
        await _sibling_environment(session, source, "the-clone")
        if with_created_environment
        else None
    )
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=capture_statuses,
        created_environment=created,
        results=results,
        clone_errors=clone_errors,
    )

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )

    assert data["environmentClone"]["status"] == expected


@pytest.mark.asyncio
async def test_environment_clone_projects_links_attribution_and_errors(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The read projects every link, the whole attribution list, and the
    operation-level events rendered ``step: error``.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-read")
    restore = await _seed_restore(
        session, instance=instance, status=RestoreStatus.COMPLETED
    )
    capture = await _seed_capture(
        session,
        environment=source,
        instance=instance,
        constituent_statuses=[BackupStatus.COMPLETED],
    )
    counterpart_id = uuid4()
    cloned_source_id = uuid4()
    skipped_source_id = uuid4()
    clone = EnvironmentClone(
        name="prod-rehearsal-read",
        source_environment_id=source.id,
        source_environment_name=source.name,
        environment_backup_id=capture.id,
        created_environment_id=created.id,
        requested_deployment_ids=[str(cloned_source_id)],
        config_override={"fqdn_suffix": "rehearsal.example.com"},
        cleared_config_fields=["ingress_class"],
        deployment_results=[
            _result_entry(
                deployment_id=cloned_source_id,
                deployment_name="infrahub",
                outcome="cloned",
                counterpart_deployment_id=counterpart_id,
                restore_id=restore.id,
            ),
            _result_entry(
                deployment_id=skipped_source_id,
                deployment_name="never-deployed",
                outcome="skipped",
                reason=CLONE_REASON_NOT_ELIGIBLE,
            ),
        ],
        clone_errors=[
            {
                "step": CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
                "error": "discarded by the operator",
                "fatal": False,
            }
        ],
    )
    session.add(clone)
    await session.commit()

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]

    assert row["status"] == "COMPLETED"
    assert row["name"] == "prod-rehearsal-read"
    assert row["sourceEnvironmentName"] == source.name
    assert row["sourceEnvironment"]["id"] == str(source.id)
    # The nested type's own resolvers work: the clone read re-reads each linked
    # row through its repository, so ``cluster`` is loaded too.
    assert row["sourceEnvironment"]["cluster"]["id"] == str(source.cluster_id)
    assert row["environmentBackup"]["id"] == str(capture.id)
    assert row["environmentBackup"]["status"] == "COMPLETED"
    assert row["createdEnvironment"]["id"] == str(created.id)
    assert row["createdEnvironment"]["name"] == "prod-rehearsal-read"
    assert row["requestedDeploymentIds"] == [str(cloned_source_id)]
    assert row["configOverride"] == {"fqdn_suffix": "rehearsal.example.com"}
    assert row["clearConfigFields"] == ["ingress_class"]
    assert row["cloneErrors"] == [
        f"{CLONE_STEP_CREATED_ENVIRONMENT_DELETED}: discarded by the operator"
    ]

    by_name = {entry["deploymentName"]: entry for entry in row["deploymentResults"]}
    assert set(by_name) == {"infrahub", "never-deployed"}
    assert by_name["infrahub"]["outcome"] == "CLONED"
    assert by_name["infrahub"]["deploymentId"] == str(cloned_source_id)
    assert by_name["infrahub"]["counterpartDeploymentId"] == str(counterpart_id)
    assert by_name["infrahub"]["restoreId"] == str(restore.id)
    assert by_name["infrahub"]["reason"] is None
    assert by_name["never-deployed"]["outcome"] == "SKIPPED"
    assert by_name["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE
    assert by_name["never-deployed"]["counterpartDeploymentId"] is None
    assert by_name["never-deployed"]["restoreId"] is None


@pytest.mark.asyncio
async def test_environment_clone_projects_null_links_after_deletion(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """Every link on a clone is nullable by design: a terminal clone survives
    its source, and the denormalised name keeps the provenance readable.
    """
    clone = EnvironmentClone(
        name="orphaned-clone",
        source_environment_id=None,
        source_environment_name="prod-that-is-gone",
        environment_backup_id=None,
        created_environment_id=None,
        deployment_results=[
            _result_entry(
                deployment_id=uuid4(),
                deployment_name="infrahub",
                outcome="cloned",
                counterpart_deployment_id=uuid4(),
            )
        ],
        clone_errors=[
            {
                "step": CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
                "error": "discarded",
                "fatal": False,
            }
        ],
    )
    session.add(clone)
    await session.commit()

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]

    assert row["sourceEnvironment"] is None
    assert row["environmentBackup"] is None
    assert row["createdEnvironment"] is None
    assert row["sourceEnvironmentName"] == "prod-that-is-gone"
    # A missing derivation input is never re-interpreted: the recorded outcome
    # stands (``data-model.md`` resolution rule 1).
    assert row["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_environment_clone_rejects_an_unknown_id(
    fresh_client: AsyncClient,
) -> None:
    """The single-clone query surfaces ``NOT_FOUND`` for an unknown id."""
    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("get_environment_clone"),
            "variables": {"environmentCloneId": str(uuid4())},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# environmentClones — list projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_environment_clones_lists_newest_first_and_scopes_by_source(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The list is scoped by **source** environment and ordered newest first."""
    source, instance = await _seed_source_with_instance(session)
    other, other_instance = await _seed_source_with_instance(session)
    base = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    # Seeded oldest-first with explicit timestamps so the ordering assertion is
    # about the resolver, not about how fast the seeds ran.
    for offset, name in enumerate(("oldest", "middle", "newest")):
        await _seed_clone(
            session,
            source=source,
            instance=instance,
            name=name,
            capture_statuses=[BackupStatus.COMPLETED],
            results=[("skipped", None)],
            created_on=base + timedelta(minutes=offset),
        )
    await _seed_clone(
        session,
        source=other,
        instance=other_instance,
        name="elsewhere",
        capture_statuses=[BackupStatus.COMPLETED],
    )
    # A clone that *created* this environment is not a clone *of* it.
    created_by_clone = await _seed_clone(
        session,
        source=other,
        instance=other_instance,
        name="created-source",
        capture_statuses=[BackupStatus.COMPLETED],
    )
    created_by_clone.created_environment_id = source.id
    session.add(created_by_clone)
    await session.commit()

    data = await gql(
        fresh_client, "list_environment_clones", {"environmentId": str(source.id)}
    )

    rows = data["environmentClones"]
    assert [row["name"] for row in rows] == ["newest", "middle", "oldest"]
    assert all(row["sourceEnvironment"]["id"] == str(source.id) for row in rows)
    # Each listed clone has a terminal capture, one recorded skip and no created
    # environment, so each derives IN_PROGRESS — the derivation ran per row
    # rather than being copied off the first.
    assert {row["status"] for row in rows} == {"IN_PROGRESS"}
    assert [row["deploymentResults"][0]["outcome"] for row in rows] == [
        "SKIPPED",
        "SKIPPED",
        "SKIPPED",
    ]


@pytest.mark.asyncio
async def test_environment_clones_is_empty_for_a_clone_free_environment(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """A plain non-null list, no pagination: nothing to list is ``[]``."""
    environment = await seed_environment(session)

    data = await gql(
        fresh_client,
        "list_environment_clones",
        {"environmentId": str(environment.id)},
    )

    assert data["environmentClones"] == []


@pytest.mark.asyncio
async def test_environment_clones_resolves_every_status_with_one_restore_query(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The referenced ``Restore`` rows are fetched once for the whole batch.

    They hang off JSON ids, so no eager-load can reach them and a naive resolver
    would issue one query per entry. The batched ``IN`` query on the repository
    exists for exactly this, and this test is what keeps the list resolver wired
    to it.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "batched")
    for index in range(3):
        await _seed_clone(
            session,
            source=source,
            instance=instance,
            name=f"batched-{index}",
            capture_statuses=[BackupStatus.COMPLETED],
            created_environment=created,
            results=[
                ("cloned", RestoreStatus.COMPLETED),
                ("cloned", RestoreStatus.COMPLETED),
            ],
        )

    bind = session.get_bind()
    engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)
    restore_selects: list[str] = []

    def _record(
        conn: Any,  # noqa: ARG001
        cursor: Any,  # noqa: ARG001
        statement: str,
        parameters: Any,  # noqa: ARG001
        context: Any,  # noqa: ARG001
        executemany: bool,  # noqa: ARG001
    ) -> None:
        normalised = " ".join(statement.split()).lower()
        if normalised.startswith("select") and " from restore" in normalised:
            restore_selects.append(normalised)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        data = await gql(
            fresh_client, "list_environment_clones", {"environmentId": str(source.id)}
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)

    assert len(data["environmentClones"]) == 3
    assert {row["status"] for row in data["environmentClones"]} == {"COMPLETED"}
    # Six referenced restores across three clones — one query.
    assert len(restore_selects) == 1, restore_selects


# ---------------------------------------------------------------------------
# Enum mirrors
# ---------------------------------------------------------------------------


def test_environment_clone_status_mirrors_the_service_enum() -> None:
    """``strawberry.enum`` binds one GraphQL name per class, so the clone surface
    declares its own mirror rather than registering the service enum. Drift
    between the two would silently change what the API reports.
    """
    assert {member.name: member.value for member in EnvironmentCloneStatusType} == {
        member.name: member.value for member in EnvironmentCloneStatus
    }


def test_environment_clone_deployment_outcome_mirrors_the_service_enum() -> None:
    """Same pinning for the per-deployment outcome vocabulary: the wire enum is
    closed precisely because the service writes exactly these four values.
    """
    assert {
        member.name: member.value for member in EnvironmentCloneDeploymentOutcomeType
    } == {member.name: member.value for member in EnvironmentCloneDeploymentOutcome}


# ---------------------------------------------------------------------------
# Environment.clonedFrom — the provenance back-reference (T034)
# ---------------------------------------------------------------------------
#
# ``environmentClones`` is scoped by **source** environment, so without this
# field a cloned environment has no way to say where it came from — and the
# clone record deliberately outlives its source, which is exactly when the
# question gets asked.


@pytest.mark.asyncio
async def test_environment_cloned_from_projects_the_clone_that_created_it(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The back-reference resolves the whole clone, derived status included."""
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-provenance")
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        name="prod-rehearsal-provenance",
        capture_statuses=[BackupStatus.COMPLETED],
        created_environment=created,
        results=[("cloned", RestoreStatus.COMPLETED)],
    )

    data = await gql(
        fresh_client, "get_environment_cloned_from", {"environmentId": str(created.id)}
    )
    row = data["environment"]["clonedFrom"]

    assert row["id"] == str(clone.id)
    assert row["name"] == "prod-rehearsal-provenance"
    assert row["status"] == "COMPLETED"
    assert row["sourceEnvironment"]["id"] == str(source.id)
    assert row["sourceEnvironmentName"] == source.name
    assert row["createdEnvironment"]["id"] == str(created.id)
    assert row["environmentBackup"]["id"] == str(clone.environment_backup_id)
    assert [entry["outcome"] for entry in row["deploymentResults"]] == ["CLONED"]


@pytest.mark.asyncio
async def test_environment_cloned_from_is_null_when_no_clone_created_it(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The reference points one way: a *source* is not itself clone-born.

    The source of the seeded clone is the interesting negative case — an
    implementation that matched on either environment id would answer with the
    clone here and quietly invert the provenance.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-oneway")
    await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=[BackupStatus.COMPLETED],
        created_environment=created,
        results=[("cloned", RestoreStatus.COMPLETED)],
    )

    data = await gql(
        fresh_client, "get_environment_cloned_from", {"environmentId": str(source.id)}
    )

    assert data["environment"]["clonedFrom"] is None


@pytest.mark.asyncio
async def test_environment_cloned_from_survives_deleting_the_source(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """T035: provenance outlives the source environment (research D9).

    The whole reason ``source_environment_id`` is nullable. Deleting the source
    goes through the real mutation, so the clone-settling cascade, the
    environment-backup cascade **and** the FR-008 guard all run for real — the
    guard being the thing that would otherwise refuse to delete the capture
    this terminal clone still references.

    The seeded instance lives in the *created* environment (it is what a
    counterpart looks like), which is also what leaves the source free of
    deployment rows so it can actually be deleted.
    """
    source = await seed_environment(session, name="prod-to-be-deleted")
    created = await _sibling_environment(session, source, "prod-rehearsal-orphan")
    adv = await seed_application_driver_version(session)
    _counterpart, instance = await seed_running_deployment(
        session, environment=created, adv=adv, name="infrahub"
    )
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        name="prod-rehearsal-orphan",
        capture_statuses=[BackupStatus.COMPLETED],
        created_environment=created,
        results=[("cloned", RestoreStatus.COMPLETED)],
    )
    source_id = source.id
    source_name = source.name

    await gql(fresh_client, "delete_environment", {"environmentId": str(source_id)})

    data = await gql(
        fresh_client, "get_environment_cloned_from", {"environmentId": str(created.id)}
    )
    row = data["environment"]["clonedFrom"]

    assert row["id"] == str(clone.id)
    # The link is gone, the readable provenance is not.
    assert row["sourceEnvironment"] is None
    assert row["sourceEnvironmentName"] == source_name
    assert row["createdEnvironment"]["id"] == str(created.id)
    # The source's capture cascaded with it, which the record says out loud —
    # non-fatally, because the clone had already finished.
    assert row["environmentBackup"] is None
    assert row["cloneErrors"] == [
        f"{CLONE_STEP_ENVIRONMENT_BACKUP_DELETED}: "
        f"the backing environment backup {clone.environment_backup_id} was deleted"
    ]
    assert row["status"] == "COMPLETED"
    # ...and the source-scoped list can no longer reach it, which is precisely
    # why the back-reference has to exist.
    assert (
        await gql(
            fresh_client, "list_environment_clones", {"environmentId": str(source_id)}
        )
    )["environmentClones"] == []


@pytest.mark.asyncio
async def test_discarding_a_cloned_environment_keeps_the_record_and_fails_it(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """SC-005 through the real mutation: the discard path is always open.

    A half-built clone is exactly what an operator discards, and the deletion
    has to leave a record that says *discarded* rather than a clone stuck
    ``IN_PROGRESS`` forever.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-discarded")
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=[BackupStatus.COMPLETED],
        created_environment=created,
        results=[("pending", None)],
    )
    before = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    assert before["environmentClone"]["status"] == "IN_PROGRESS"

    await gql(fresh_client, "delete_environment", {"environmentId": str(created.id)})

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]

    assert row["createdEnvironment"] is None
    assert row["cloneErrors"] == [
        f"{CLONE_STEP_CREATED_ENVIRONMENT_DELETED}: "
        f"the created environment {created.id} was deleted"
    ]
    assert row["status"] == "FAILED"


# ---------------------------------------------------------------------------
# deleteEnvironmentBackup — the FR-008 window on the wire (T032/T035)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_a_capture_in_flight_is_refused_with_in_use(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """FR-008 on the wire: the typed ``IN_USE`` code, and nothing deleted."""
    source, instance = await _seed_source_with_instance(session)
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        name="prod-rehearsal-in-use",
        capture_statuses=[BackupStatus.IN_PROGRESS],
        results=[("pending", None)],
    )

    response = await fresh_client.post(
        "/graphql",
        json={
            "query": load_query("delete_environment_backup"),
            "variables": {"environmentBackupId": str(clone.environment_backup_id)},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors[0]["extensions"]["code"] == "IN_USE"
    assert "prod-rehearsal-in-use" in errors[0]["message"]
    # Refused, not partially applied.
    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    assert data["environmentClone"]["environmentBackup"]["id"] == str(
        clone.environment_backup_id
    )
    assert data["environmentClone"]["cloneErrors"] == []


@pytest.mark.asyncio
async def test_deleting_a_landed_capture_is_the_escape_hatch_for_a_stuck_clone(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """FR-008 on the wire: post-capture deletion ends a stuck clone, attributed."""
    source, instance = await _seed_source_with_instance(session)
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=[BackupStatus.COMPLETED],
        results=[("pending", None)],
    )
    environment_backup_id = clone.environment_backup_id

    await gql(
        fresh_client,
        "delete_environment_backup",
        {"environmentBackupId": str(environment_backup_id)},
    )

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]

    assert row["environmentBackup"] is None
    assert row["cloneErrors"] == [
        f"{CLONE_STEP_ENVIRONMENT_BACKUP_DELETED}: "
        f"the backing environment backup {environment_backup_id} was deleted"
    ]
    assert row["status"] == "FAILED"


# ---------------------------------------------------------------------------
# deploymentResults — the join projection and the coverage identity (T035)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_environment_clone_projects_every_outcome_with_its_reason_and_ids(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """All four outcomes in one read, each with the ids the UI links on.

    ``restoreId`` is the only pointer to the cross-target restore — it lives
    inside a JSON entry, so no foreign key or relationship checks it and only a
    read like this one proves the id that was written is the id that comes
    back.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-outcomes")
    landed = await _seed_restore(
        session, instance=instance, status=RestoreStatus.COMPLETED
    )
    running = await _seed_restore(
        session, instance=instance, status=RestoreStatus.IN_PROGRESS
    )
    capture = await _seed_capture(
        session,
        environment=source,
        instance=instance,
        constituent_statuses=[BackupStatus.COMPLETED, BackupStatus.FAILED],
    )
    counterpart_id = uuid4()
    entries = {
        "infrahub": _result_entry(
            deployment_id=uuid4(),
            deployment_name="infrahub",
            outcome="cloned",
            counterpart_deployment_id=counterpart_id,
            restore_id=landed.id,
        ),
        "netbox": _result_entry(
            deployment_id=uuid4(),
            deployment_name="netbox",
            outcome="cloned",
            counterpart_deployment_id=uuid4(),
            restore_id=running.id,
        ),
        "never-deployed": _result_entry(
            deployment_id=uuid4(),
            deployment_name="never-deployed",
            outcome="skipped",
            reason=CLONE_REASON_NOT_ELIGIBLE,
        ),
        "grafana": _result_entry(
            deployment_id=uuid4(),
            deployment_name="grafana",
            outcome="failed",
            reason=CLONE_REASON_NOT_SELECTED,
        ),
        "prometheus": _result_entry(
            deployment_id=uuid4(),
            deployment_name="prometheus",
            outcome="pending",
        ),
    }
    clone = EnvironmentClone(
        name="prod-rehearsal-outcomes",
        source_environment_id=source.id,
        source_environment_name=source.name,
        environment_backup_id=capture.id,
        created_environment_id=created.id,
        deployment_results=list(entries.values()),
    )
    session.add(clone)
    await session.commit()

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]
    by_name = {entry["deploymentName"]: entry for entry in row["deploymentResults"]}

    assert set(by_name) == set(entries)
    assert {name: entry["outcome"] for name, entry in by_name.items()} == {
        "infrahub": "CLONED",
        "netbox": "CLONED",
        "never-deployed": "SKIPPED",
        "grafana": "FAILED",
        "prometheus": "PENDING",
    }
    assert by_name["infrahub"]["restoreId"] == str(landed.id)
    assert by_name["infrahub"]["counterpartDeploymentId"] == str(counterpart_id)
    assert by_name["infrahub"]["deploymentId"] == entries["infrahub"]["deployment_id"]
    assert by_name["netbox"]["restoreId"] == str(running.id)
    assert by_name["never-deployed"]["reason"] == CLONE_REASON_NOT_ELIGIBLE
    assert by_name["never-deployed"]["restoreId"] is None
    assert by_name["grafana"]["reason"] == CLONE_REASON_NOT_SELECTED
    assert by_name["grafana"]["counterpartDeploymentId"] is None
    assert by_name["prometheus"]["reason"] is None
    # The join is what decides the status: one referenced restore is still
    # running and one entry is still pending, so the clone is not done.
    assert row["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_a_terminal_clone_accounts_for_every_deployment_exactly_once(
    fresh_client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    prefect_manager_mock,
) -> None:
    """SC-003's coverage identity, asserted where it matters: at terminality.

    Registration-time attribution is covered above; this runs the real flow to
    a **terminal** clone and asserts the two halves of the identity in
    ``data-model.md`` — one entry per source deployment considered, and not one
    of them left ``PENDING``. A flow that dropped a deployment on the floor
    between registration and terminality would still satisfy the earlier test.

    "Considered" is the eligible-plus-explicitly-selected set: the internal and
    tombstoned deployments seeded here are part of the environment and
    deliberately absent from the list (FR-003), which is why the assertion is an
    exact set rather than a count.
    """
    source = await seed_environment(session, name="prod-coverage")
    adv = await seed_application_driver_version(session)
    await seed_running_deployment(session, environment=source, adv=adv, name="infrahub")
    await seed_running_deployment(session, environment=source, adv=adv, name="netbox")
    # Eligible-looking but never deployed: no active instance, so it is a skip
    # with a reason rather than an omission.
    await seed_deployment(session, environment=source, adv=adv, name="never-deployed")
    internal = await seed_deployment(
        session, environment=source, adv=adv, name="ingress-controller"
    )
    internal.internal = True
    tombstoned = await seed_deployment(
        session, environment=source, adv=adv, name="deleted-app"
    )
    tombstoned.deleted_at = datetime.now(timezone.utc)
    session.add(internal)
    session.add(tombstoned)
    await session.commit()
    source_id = source.id

    clone = await _clone_and_materialise(
        fresh_client,
        session,
        monkeypatch,
        {"environmentId": str(source_id), "name": "prod-coverage-rehearsal"},
    )
    # The stubbed cross-target restores land, which is what makes the clone
    # terminal — the derivation folds their status, not the flow's exit.
    result = await session.exec(select(Restore))
    # One commit per row: see the note in ``_complete_capture_constituents``
    # for why a multi-row flush cannot carry the ``updated_on`` onupdate here.
    for restore in result.all():
        restore.status = RestoreStatus.COMPLETED
        session.add(restore)
        await session.commit()

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]
    entries = row["deploymentResults"]

    assert row["status"] == "COMPLETED"
    assert {entry["deploymentName"] for entry in entries} == {
        "infrahub",
        "netbox",
        "never-deployed",
    }
    assert len(entries) == 3
    assert EnvironmentCloneDeploymentOutcomeType.PENDING.value.upper() not in {
        entry["outcome"] for entry in entries
    }
    assert {entry["deploymentName"]: entry["outcome"] for entry in entries} == {
        "infrahub": "CLONED",
        "netbox": "CLONED",
        "never-deployed": "SKIPPED",
    }
    # Every non-skipped entry carries the two ids that make it auditable.
    for entry in entries:
        if entry["outcome"] == "CLONED":
            assert entry["counterpartDeploymentId"] is not None
            assert entry["restoreId"] is not None
        else:
            assert entry["reason"]


@pytest.mark.asyncio
async def test_environment_clone_renders_clone_errors_in_recorded_order(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """``cloneErrors`` is a flat ``step: error`` list, fatal or not.

    The ``fatal`` flag drives the derivation and is deliberately **not** on the
    wire — a client that filtered on it would be re-deriving the status the
    server already computed. What the operator needs is the sequence of what
    happened, in the order it happened.
    """
    source, instance = await _seed_source_with_instance(session)
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=[BackupStatus.FAILED],
        results=[("failed", None)],
        clone_errors=[
            {
                "step": CLONE_STEP_CAPTURE_FAILED,
                "error": "the capture never became restorable",
                "fatal": True,
            },
            {
                "step": CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
                "error": "cleaned up afterwards",
                "fatal": False,
            },
        ],
    )

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )

    assert data["environmentClone"]["cloneErrors"] == [
        f"{CLONE_STEP_CAPTURE_FAILED}: the capture never became restorable",
        f"{CLONE_STEP_ENVIRONMENT_BACKUP_DELETED}: cleaned up afterwards",
    ]
    assert data["environmentClone"]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_environment_clone_renders_no_clone_errors_as_an_empty_list(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """A clean clone reports ``[]``, never null: the field is non-null."""
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-clean")
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=[BackupStatus.COMPLETED],
        created_environment=created,
        results=[("cloned", RestoreStatus.COMPLETED)],
    )

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )

    assert data["environmentClone"]["cloneErrors"] == []
    assert data["environmentClone"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_environment_clone_stays_readable_with_a_flagless_clone_error(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """The read path may never be stricter than the derivation.

    ``CloneError.fatal`` is required on the model but optional in practice — the
    derivation reads a missing flag as non-fatal on purpose — so validating it in
    the resolver made one flag-less entry raise ``ValidationError``, get masked
    as ``INTERNAL_ERROR`` ("An internal error occurred"), and fail the **whole**
    ``environmentClone`` query. The operator was left with no field, no index and
    no row id, unable to read the clone on any surface, at exactly the moment
    something had gone wrong with it.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-flagless")
    clone = await _seed_clone(
        session,
        source=source,
        instance=instance,
        capture_statuses=[BackupStatus.COMPLETED],
        created_environment=created,
        results=[("cloned", RestoreStatus.COMPLETED)],
        clone_errors=[{"step": "mystery", "error": "written without a flag"}],
    )

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]

    assert row["id"] == str(clone.id)
    assert row["cloneErrors"] == ["mystery: written without a flag"]
    # Read as non-fatal, exactly as the derivation reads it.
    assert row["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_environment_clone_projects_an_unreadable_result_entry(
    fresh_client: AsyncClient, session: AsyncSession
) -> None:
    """An entry the wire type cannot express is degraded, never fatal to the query.

    ``outcome`` is a closed enum on the wire and free JSON in the column, and the
    derivation deliberately counts an unrecognised or unreadable entry as a
    failure. The projection now says the same thing — and says *which* entry, by
    index, so the operator can go and fix the row.
    """
    source, instance = await _seed_source_with_instance(session)
    created = await _sibling_environment(session, source, "prod-rehearsal-unreadable")
    good_deployment_id = uuid4()
    clone = EnvironmentClone(
        name="prod-rehearsal-unreadable",
        source_environment_id=source.id,
        source_environment_name=source.name,
        created_environment_id=created.id,
        deployment_results=[
            _result_entry(
                deployment_id=good_deployment_id,
                deployment_name="infrahub",
                outcome="cloned",
            ),
            {"deployment_name": "half-written", "outcome": "teleported"},
            "nonsense",
        ],
    )
    session.add(clone)
    await session.commit()

    data = await gql(
        fresh_client, "get_environment_clone", {"environmentCloneId": str(clone.id)}
    )
    row = data["environmentClone"]

    entries = row["deploymentResults"]
    assert len(entries) == 3, "an unreadable entry must not vanish from the account"
    assert entries[0]["deploymentId"] == str(good_deployment_id)
    assert entries[0]["outcome"] == "CLONED"
    # Both unreadable shapes: an unknown outcome, and a non-entry.
    assert [entry["outcome"] for entry in entries[1:]] == ["FAILED", "FAILED"]
    assert "index 1" in entries[1]["reason"]
    assert entries[2]["deploymentName"] == "<unreadable entry 2>"
    assert entries[2]["deploymentId"] == "00000000-0000-0000-0000-000000000000"
    # And the clone is honest about it rather than claiming COMPLETED.
    assert row["status"] == "PARTIAL"
