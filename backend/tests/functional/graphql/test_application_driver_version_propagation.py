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

017-post-render-env-vars (T029) adds ``componentConfigs { container }``: the
component container a driver declares (``components.<name>.container``),
loaded through ``loadLocalApplicationDriverVersion`` and read back from both
the DB row and the ``applicationDriver`` query.

020-driver-info-display (T010) adds ``icon``, ``description`` and ``links``:
the ``spec.info`` values, loaded through ``loadLocalApplicationDriverVersion``,
read back from the DB row and projected through ``applicationDriver.versions``.
T028 adds the invalid-value case: an invalid ``icon`` or link is left out and
returned in ``loadWarnings``, and the load succeeds (PR #418 review, item 2).
``STYRMIN_DRIVER_SHOW_LOGOS=false`` hides ``icon`` from every response (item 5).
T033 adds the reload case: an unchanged driver fills in a pre-feature row (FR-006).

Test location note: the task list specifies
``backend/tests/unit/api/schema/test_application_driver_version_propagation.py``
but the project's documented propagation-test harness (fixtures, seeds,
operation loader) lives in ``backend/tests/functional/graphql/`` per
``dev/guides/graphql-propagation-tests.md``. We follow the guide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend import config
from styrmin_backend.db.models import ApplicationDriverVersion, ComponentConfig

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


def _write_container_driver(path: Path) -> None:
    """Write a local driver whose ``server`` declares a container and whose
    ``database`` omits it."""
    spec: dict[str, Any] = {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "container-propagation"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=0.1,<1.0",
            "info": {"description": "Component container propagation fixture"},
            "helm": {
                "main": {
                    "location": "oci://registry.example.com/charts/simple-app",
                    "version": "0.1.0",
                }
            },
            "components": {
                "server": {
                    "identifier": {"label": {"app.kubernetes.io/name": "simple-app"}},
                    "container": "simple-app",
                },
                "database": {
                    "identifier": {"label": {"app.kubernetes.io/name": "postgresql"}},
                },
            },
        },
    }
    (path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (path / "values.j2.yml").write_text("{}\n")


INFO_ICON = "https://example.com/logo.svg"
INFO_DESCRIPTION = "Driver info propagation fixture"
# The bare-host URL checks that ``HttpUrl`` normalisation (trailing ``/``) is what gets stored.
INFO_LINKS = [
    {"link": "Homepage", "url": "https://example.com"},
    {"link": "Documentation", "url": "https://docs.example.com/guide"},
]
STORED_INFO_LINKS = [
    {"link": "Homepage", "url": "https://example.com/"},
    {"link": "Documentation", "url": "https://docs.example.com/guide"},
]


def _write_info_driver(path: Path, info: dict[str, Any]) -> None:
    """Write a local driver whose ``spec.info`` block is ``info``."""
    spec: dict[str, Any] = {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "info-propagation"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=0.1,<1.0",
            "info": info,
            "helm": {
                "main": {
                    "location": "oci://registry.example.com/charts/simple-app",
                    "version": "0.1.0",
                }
            },
            "components": {
                "server": {
                    "identifier": {"label": {"app.kubernetes.io/name": "simple-app"}},
                },
            },
        },
    }
    (path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (path / "values.j2.yml").write_text("{}\n")


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_propagates_from_driver_load_to_db(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    """Loading a driver stores ``spec.info`` icon, description and links on
    the ``ApplicationDriverVersion`` row."""
    _write_info_driver(
        tmp_path,
        {"icon": INFO_ICON, "description": INFO_DESCRIPTION, "links": INFO_LINKS},
    )

    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    version = loaded["loadLocalApplicationDriverVersion"]

    row = await session.get(
        ApplicationDriverVersion, UUID(version["id"]), populate_existing=True
    )
    assert row is not None
    assert row.icon == INFO_ICON
    assert row.description == INFO_DESCRIPTION
    assert row.links == STORED_INFO_LINKS


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_projects_through_application_driver_query(
    client: AsyncClient, tmp_path: Path
) -> None:
    """``applicationDriver.versions`` returns the loaded icon, description and
    links, with the links in file order."""
    _write_info_driver(
        tmp_path,
        {"icon": INFO_ICON, "description": INFO_DESCRIPTION, "links": INFO_LINKS},
    )
    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    version = loaded["loadLocalApplicationDriverVersion"]

    data = await gql(
        client,
        "get_driver_info",
        {"applicationDriverId": version["applicationDriverId"]},
    )
    [read_back] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == version["id"]
    ]
    expected_links = [
        {"label": "Homepage", "url": "https://example.com/"},
        {"label": "Documentation", "url": "https://docs.example.com/guide"},
    ]
    assert read_back["icon"] == INFO_ICON
    assert read_back["description"] == INFO_DESCRIPTION
    assert read_back["links"] == expected_links
    assert version["links"] == expected_links


@pytest.mark.asyncio
async def test_driver_info_is_empty_for_rows_without_info(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Rows stored without info (or before the columns existed) project as
    ``null``, ``null`` and ``[]``."""
    adv = await seed_application_driver_version(session)
    assert (adv.icon, adv.description, adv.links) == (None, None, None)

    data = await gql(
        client,
        "get_driver_info",
        {"applicationDriverId": str(adv.application_driver_id)},
    )
    [version] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == str(adv.id)
    ]
    assert version["icon"] is None
    assert version["description"] is None
    assert version["links"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_empty_description_and_links_are_stored_as_null(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    """An empty ``description`` and an empty ``links`` list are stored as NULL
    and project as ``null`` and ``[]``."""
    _write_info_driver(tmp_path, {"description": "", "links": []})

    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    version = loaded["loadLocalApplicationDriverVersion"]

    row = await session.get(
        ApplicationDriverVersion, UUID(version["id"]), populate_existing=True
    )
    assert row is not None
    assert (row.icon, row.description, row.links) == (None, None, None)

    data = await gql(
        client,
        "get_driver_info",
        {"applicationDriverId": version["applicationDriverId"]},
    )
    [read_back] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == version["id"]
    ]
    assert read_back["icon"] is None
    assert read_back["description"] is None
    assert read_back["links"] == []


INVALID_ICON_WARNING = (
    "spec.info.icon must be an absolute https URL, such as "
    "https://example.com/logo.svg (found 'xxxx'). The icon was not stored."
)
INVALID_LINK_WARNING = (
    "spec.info.links[1] has keys other than `link` and `url`: name. "
    "The link was not stored."
)


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_invalid_values_are_dropped_and_returned_as_warnings(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    """A placeholder ``icon`` and a link with an unknown key do not fail the
    load: they are left out of the row and named in ``loadWarnings``. A reload
    of the same file returns the same row and the same warnings."""
    _write_info_driver(
        tmp_path,
        {
            "icon": "xxxx",
            "links": [
                INFO_LINKS[1],
                {"link": "Old", "url": "https://example.com/old", "name": "x"},
            ],
        },
    )

    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    first = loaded["loadLocalApplicationDriverVersion"]
    assert first["icon"] is None
    assert first["links"] == [
        {"label": "Documentation", "url": "https://docs.example.com/guide"}
    ]
    assert first["loadWarnings"] == [INVALID_ICON_WARNING, INVALID_LINK_WARNING]

    row = await session.get(
        ApplicationDriverVersion, UUID(first["id"]), populate_existing=True
    )
    assert row is not None
    assert row.icon is None
    assert row.links == [STORED_INFO_LINKS[1]]

    reloaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    second = reloaded["loadLocalApplicationDriverVersion"]
    assert second["id"] == first["id"]
    assert second["loadWarnings"] == first["loadWarnings"]

    # The warnings belong to the load, not to the stored driver version.
    data = await gql(
        client,
        "get_driver_info",
        {"applicationDriverId": first["applicationDriverId"]},
    )
    [read_back] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == first["id"]
    ]
    assert read_back["loadWarnings"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_valid_load_returns_no_warnings(
    client: AsyncClient, tmp_path: Path
) -> None:
    """A driver whose ``spec.info`` is valid loads with an empty ``loadWarnings``."""
    _write_info_driver(tmp_path, {"icon": INFO_ICON, "links": INFO_LINKS})

    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})

    assert loaded["loadLocalApplicationDriverVersion"]["loadWarnings"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_icon_is_hidden_when_show_logos_is_off(
    client: AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``STYRMIN_DRIVER_SHOW_LOGOS=false`` the API returns no ``icon``, so
    no browser requests the logo; the row still stores it."""
    monkeypatch.setattr(config.SETTINGS.driver, "show_logos", False)
    _write_info_driver(tmp_path, {"icon": INFO_ICON, "description": INFO_DESCRIPTION})

    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    version = loaded["loadLocalApplicationDriverVersion"]
    assert version["icon"] is None
    assert version["description"] == INFO_DESCRIPTION

    data = await gql(
        client,
        "get_driver_info",
        {"applicationDriverId": version["applicationDriverId"]},
    )
    [read_back] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == version["id"]
    ]
    assert read_back["icon"] is None

    row = await session.get(
        ApplicationDriverVersion, UUID(version["id"]), populate_existing=True
    )
    assert row is not None
    assert row.icon == INFO_ICON


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_driver_info_is_filled_in_on_reload_of_an_unchanged_driver(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    """Reloading an unchanged driver fills in the info columns of a row stored
    before they existed, on the same driver version (FR-006, US4)."""
    _write_info_driver(
        tmp_path,
        {"icon": INFO_ICON, "description": INFO_DESCRIPTION, "links": INFO_LINKS},
    )
    loaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    first = loaded["loadLocalApplicationDriverVersion"]
    version_id = UUID(first["id"])

    # Simulate a row stored before the info columns existed.
    row = await session.get(ApplicationDriverVersion, version_id)
    assert row is not None
    row.icon = None
    row.description = None
    row.links = None
    session.add(row)
    await session.commit()

    reloaded = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    second = reloaded["loadLocalApplicationDriverVersion"]
    assert second["id"] == first["id"]

    row = await session.get(
        ApplicationDriverVersion, version_id, populate_existing=True
    )
    assert row is not None
    assert row.icon == INFO_ICON
    assert row.description == INFO_DESCRIPTION
    assert row.links == STORED_INFO_LINKS

    data = await gql(
        client,
        "get_driver_info",
        {"applicationDriverId": first["applicationDriverId"]},
    )
    [read_back] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == first["id"]
    ]
    assert read_back["icon"] == INFO_ICON
    assert read_back["description"] == INFO_DESCRIPTION
    assert read_back["links"] == [
        {"label": "Homepage", "url": "https://example.com/"},
        {"label": "Documentation", "url": "https://docs.example.com/guide"},
    ]

    third = await gql(client, "load_local_driver_info", {"path": str(tmp_path)})
    assert third["loadLocalApplicationDriverVersion"]["id"] == first["id"]
    versions = (
        await session.exec(
            select(ApplicationDriverVersion).where(
                ApplicationDriverVersion.application_driver_id
                == UUID(first["applicationDriverId"])
            )
        )
    ).all()
    assert len(versions) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("prefect_manager_mock")
async def test_component_container_propagates_from_driver_load_to_graphql(
    client: AsyncClient, session: AsyncSession, tmp_path: Path
) -> None:
    """A loaded driver's declared component container reaches the
    ``ComponentConfig`` row and projects through ``componentConfigs``; an
    undeclared one projects as null."""
    _write_container_driver(tmp_path)

    loaded = await gql(
        client, "load_local_driver_component_containers", {"path": str(tmp_path)}
    )
    version = loaded["loadLocalApplicationDriverVersion"]
    assert {c["name"]: c["container"] for c in version["componentConfigs"]} == {
        "server": "simple-app",
        "database": None,
    }

    rows = (
        await session.exec(
            select(ComponentConfig).where(
                ComponentConfig.application_driver_version_id == UUID(version["id"])
            )
        )
    ).all()
    assert {row.name: row.config.get("container") for row in rows} == {
        "server": "simple-app",
        "database": None,
    }

    data = await gql(
        client,
        "get_driver_component_containers",
        {"applicationDriverId": version["applicationDriverId"]},
    )
    [read_back] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == version["id"]
    ]
    assert {c["name"]: c["container"] for c in read_back["componentConfigs"]} == {
        "server": "simple-app",
        "database": None,
    }


@pytest.mark.asyncio
async def test_component_container_is_null_for_rows_without_the_key(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Rows stored before the field existed have no ``container`` key; the
    resolver reads them as null rather than failing."""
    adv = await seed_application_driver_version(session)
    session.add(
        ComponentConfig(
            name="legacy",
            config={"identifier": {"label": {"app.kubernetes.io/name": "legacy"}}},
            application_driver_version_id=adv.id,
        )
    )
    await session.commit()

    data = await gql(
        client,
        "get_driver_component_containers",
        {"applicationDriverId": str(adv.application_driver_id)},
    )
    [version] = [
        v for v in data["applicationDriver"]["versions"] if v["id"] == str(adv.id)
    ]
    assert version["componentConfigs"] == [{"name": "legacy", "container": None}]
