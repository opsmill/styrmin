"""GraphQL <-> DB propagation tests for the new fingerprint fields on
``ApplicationDriverVersion`` (013-driver-fingerprint, T014 + T015).

Per Constitution §V and ``dev/guides/graphql-propagation-tests.md`` every new
GraphQL field requires a propagation test that proves the value flows through
the **real** repository + resolver layers between the database and the
GraphQL boundary. This module covers the two new read-only scalar fields:

- ``contentHash`` (Python ``content_hash``): populated when
  ``sourceType == "local"`` — a SHA-256 hex of the driver's three canonical
  input files.
- ``sourceCommitSha`` (Python ``source_commit_sha``): populated when
  ``sourceType == "git"`` — the git commit SHA resolved at load time.

Pattern: seed a real ``ApplicationDriverVersion`` row with a known
fingerprint via the shared ``seed_application_driver_version`` helper,
read it back through ``session.get`` (proves the value reached the DB,
not just the resolver), and assert the GraphQL query projects the
fingerprint verbatim. Mirrors the round-trip recipe used by
``test_application_driver_created_on_propagation``.

Test location note: the task list specifies
``backend/tests/unit/api/schema/test_application_driver_version_propagation.py``
but the project's documented propagation-test harness (fixtures, seeds,
operation loader) lives in ``backend/tests/functional/graphql/`` per
``dev/guides/graphql-propagation-tests.md``. We follow the guide.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import ApplicationDriverVersion

from .conftest import gql
from .seeds import seed_application_driver_version

# A deterministic SHA-256 hex (64 chars) — value is arbitrary; what matters
# is that it survives DB write + resolver read byte-for-byte.
KNOWN_CONTENT_HASH = "a" * 64

# A deterministic git commit SHA (40 hex chars) — same rationale.
KNOWN_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.asyncio
async def test_content_hash_propagates_from_db_to_graphql(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed a local-sourced ``ApplicationDriverVersion`` with a known
    ``content_hash`` and assert ``contentHash`` projects it verbatim while
    ``sourceCommitSha`` projects as null.
    """
    adv = await seed_application_driver_version(session)
    # The default seed uses ``source_type="git"``; flip to local so the
    # fingerprint discriminator matches the field under test.
    adv.source_type = "local"
    adv.content_hash = KNOWN_CONTENT_HASH
    adv.source_commit_sha = None
    session.add(adv)
    await session.commit()

    # Read back through the real DB session — proves the value reached the
    # database, not just the resolver.
    db_adv = await session.get(ApplicationDriverVersion, adv.id)
    assert db_adv is not None
    assert db_adv.content_hash == KNOWN_CONTENT_HASH
    assert db_adv.source_commit_sha is None

    data = await gql(
        client,
        "get_application_driver_version_fingerprint",
        {"applicationDriverId": str(adv.application_driver_id)},
    )
    versions = data["applicationDriver"]["versions"]
    matching = [v for v in versions if v["id"] == str(adv.id)]
    assert len(matching) == 1
    version_payload = matching[0]
    assert version_payload["sourceType"] == "local"
    assert version_payload["contentHash"] == KNOWN_CONTENT_HASH
    assert version_payload["sourceCommitSha"] is None


@pytest.mark.asyncio
async def test_source_commit_sha_propagates_from_db_to_graphql(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed a git-sourced ``ApplicationDriverVersion`` with a known
    ``source_commit_sha`` and assert ``sourceCommitSha`` projects it
    verbatim while ``contentHash`` projects as null.
    """
    adv = await seed_application_driver_version(session)
    # ``seed_application_driver_version`` already sets ``source_type="git"``;
    # set the commit SHA explicitly and make sure the local fingerprint is
    # null so the discriminator invariant holds for the assertion.
    assert adv.source_type == "git"
    adv.source_commit_sha = KNOWN_COMMIT_SHA
    adv.content_hash = None
    session.add(adv)
    await session.commit()

    db_adv = await session.get(ApplicationDriverVersion, adv.id)
    assert db_adv is not None
    assert db_adv.source_commit_sha == KNOWN_COMMIT_SHA
    assert db_adv.content_hash is None

    data = await gql(
        client,
        "get_application_driver_version_fingerprint",
        {"applicationDriverId": str(adv.application_driver_id)},
    )
    versions = data["applicationDriver"]["versions"]
    matching = [v for v in versions if v["id"] == str(adv.id)]
    assert len(matching) == 1
    version_payload = matching[0]
    assert version_payload["sourceType"] == "git"
    assert version_payload["sourceCommitSha"] == KNOWN_COMMIT_SHA
    assert version_payload["contentHash"] is None
