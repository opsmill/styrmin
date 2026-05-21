"""GraphQL ↔ DB propagation tests for ``ApplicationDriver.createdOn`` and
``ApplicationDriverVersion.createdOn`` (012-driver-detail-tabs, T005).

Per Constitution §V every new GraphQL field requires a propagation test that
proves the value flows through the **real** service + repository layers
between the GraphQL boundary and the DB. This module covers the
``createdOn`` projections on both ``ApplicationDriver`` and
``ApplicationDriverVersion``.

Pattern: seed real rows with known ``created_on`` timestamps, read them back
through ``session.get`` (proves the value reached the DB, not just the
resolver), and assert the ``createdOn`` selection on the GraphQL query
round-trips with byte-equality on the ISO-formatted instant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
)

from .conftest import gql
from .seeds import seed_application_driver_version


@pytest.mark.asyncio
async def test_application_driver_created_on_round_trips(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed an ``ApplicationDriver`` row with a known ``created_on`` and
    assert ``ApplicationDriver.createdOn`` projects the exact timestamp.

    Reads back through ``session.get`` first to prove the value reached the
    DB before the resolver projects it (per the propagation-test recipe).
    """
    adv = await seed_application_driver_version(session)

    # Pin a deterministic ``created_on`` on the parent driver row so the
    # round-trip assertion is byte-exact against a value we control.
    pinned_driver_ts = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver is not None
    driver.created_on = pinned_driver_ts
    session.add(driver)
    await session.commit()

    # Read back through the real DB session — proves the value reached the
    # database, not just the resolver.
    db_driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert db_driver is not None
    assert db_driver.created_on == pinned_driver_ts

    data = await gql(
        client,
        "get_application_driver_created_on",
        {"applicationDriverId": str(adv.application_driver_id)},
    )
    payload = data["applicationDriver"]
    assert payload["id"] == str(adv.application_driver_id)
    # Strawberry serialises ``datetime`` as ISO-8601; compare via ``fromisoformat``
    # so the assertion is robust to ``+00:00`` / ``Z`` formatting differences.
    assert datetime.fromisoformat(payload["createdOn"]) == pinned_driver_ts


@pytest.mark.asyncio
async def test_application_driver_version_created_on_round_trips(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed an ``ApplicationDriverVersion`` row with a known ``created_on``
    and assert ``ApplicationDriverVersion.createdOn`` projects the exact
    timestamp under ``applicationDriver.versions[]``.
    """
    adv = await seed_application_driver_version(session)

    pinned_version_ts = datetime(2024, 6, 7, 8, 9, 10, tzinfo=timezone.utc)
    adv.created_on = pinned_version_ts
    session.add(adv)
    await session.commit()

    db_adv = await session.get(ApplicationDriverVersion, adv.id)
    assert db_adv is not None
    assert db_adv.created_on == pinned_version_ts

    data = await gql(
        client,
        "get_application_driver_created_on",
        {"applicationDriverId": str(adv.application_driver_id)},
    )
    versions = data["applicationDriver"]["versions"]
    matching = [v for v in versions if v["id"] == str(adv.id)]
    assert len(matching) == 1
    assert datetime.fromisoformat(matching[0]["createdOn"]) == pinned_version_ts


@pytest.mark.asyncio
async def test_application_driver_created_on_distinct_versions(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Two versions of the same driver project distinct ``createdOn`` values
    — exercises the relationship-loaded path that the frontend left rail
    relies on to sort versions newest-first.
    """
    adv_old = await seed_application_driver_version(session, version="1.0.0")
    # Reuse the same driver so both rows live under the same parent.
    adv_new = ApplicationDriverVersion(
        application_driver_id=adv_old.application_driver_id,
        version="2.0.0",
        application_supported_versions=">=2.0.0",
        source_type="local",
        source_repository="/tmp/test-driver",
        source_branch=None,
        helm_chart_id=adv_old.helm_chart_id,
    )
    session.add(adv_new)
    await session.commit()

    older_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    newer_ts = older_ts + timedelta(days=30)
    adv_old.created_on = older_ts
    adv_new.created_on = newer_ts
    session.add(adv_old)
    session.add(adv_new)
    await session.commit()

    data = await gql(
        client,
        "get_application_driver_created_on",
        {"applicationDriverId": str(adv_old.application_driver_id)},
    )
    versions = {v["id"]: v for v in data["applicationDriver"]["versions"]}
    assert datetime.fromisoformat(versions[str(adv_old.id)]["createdOn"]) == older_ts
    assert datetime.fromisoformat(versions[str(adv_new.id)]["createdOn"]) == newer_ts
