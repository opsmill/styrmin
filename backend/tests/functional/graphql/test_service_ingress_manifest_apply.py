"""``styrminctl deployments apply`` stores a manifest's ``spec.config.services`` (#598, T030).

The real SDK ``apply_files`` runs against the real backend through the ASGI client. A manifest
with an ``services`` block creates a deployment with the override, or updates an existing one,
and the stored ``Deployment.config["services"]`` is read back. The block must not be dropped
as an unknown key (research D-009).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from styrmin_sdk import StyrminClient

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Deployment,
)

from .test_service_ingress_propagation import (
    ENVIRONMENT_NAME,
    OVERRIDE_CLASS,
    OVERRIDE_SUFFIX,
    TASK_MANAGER_OVERRIDE_STORED,
    _arm_prefect,
    _seed_deploy_driver,
    _seed_deployment,
)

MANIFEST = """\
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: {name}
spec:
  driver: {driver}
  version: "1.0.0"
  environment: {environment}
  config:
{config}
"""

SERVICES_CONFIG = f"""\
    services:
      - name: task-manager
        ingress_class: {OVERRIDE_CLASS}
        fqdn_suffix: {OVERRIDE_SUFFIX}
"""


def _write_manifest(path: Path, *, name: str, driver: str, config: str) -> Path:
    path.write_text(
        MANIFEST.format(
            name=name,
            driver=driver,
            environment=ENVIRONMENT_NAME,
            config=config.rstrip(),
        ),
        encoding="utf-8",
    )
    return path


async def _apply(client: AsyncClient, manifest: Path) -> Any:
    """Run the SDK ``apply_files`` through the ASGI client of the backend."""
    sdk = StyrminClient(server_address="http://test")
    sdk._transport._client = client  # noqa: SLF001 - the SDK has no hook for another transport
    [outcome] = await sdk.deployments.apply_files([manifest])
    return outcome


async def _stored_config(session: AsyncSession, name: str) -> dict[str, Any]:
    session.expire_all()
    row = (await session.exec(select(Deployment).where(Deployment.name == name))).one()
    assert row.config is not None
    return row.config


async def _existing(session: AsyncSession, config: dict[str, Any]) -> tuple[str, str]:
    """Seed a deployment and return its name and its driver name."""
    deployment_id: UUID = await _seed_deployment(session, config=config)
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    adv = await session.get(
        ApplicationDriverVersion, deployment.application_driver_version_id
    )
    assert adv is not None
    driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver is not None
    return deployment.name, driver.name


@pytest.mark.asyncio
async def test_apply_creates_a_deployment_with_the_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    _arm_prefect(prefect_manager_mock)
    driver_name, _environment_id = await _seed_deploy_driver(session)
    manifest = _write_manifest(
        tmp_path / "app.yaml",
        name="from-manifest",
        driver=driver_name,
        config=SERVICES_CONFIG,
    )

    outcome = await _apply(client, manifest)

    assert outcome.action == "created", outcome
    assert (await _stored_config(session, "from-manifest"))["services"] == {
        "task-manager": TASK_MANAGER_OVERRIDE_STORED
    }


@pytest.mark.asyncio
async def test_apply_adds_the_override_to_an_existing_deployment(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    _arm_prefect(prefect_manager_mock)
    name, driver_name = await _existing(session, config={})
    manifest = _write_manifest(
        tmp_path / "app.yaml", name=name, driver=driver_name, config=SERVICES_CONFIG
    )

    outcome = await _apply(client, manifest)

    assert outcome.action == "updated", outcome
    assert await _stored_config(session, name) == {
        "services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}
    }


@pytest.mark.asyncio
async def test_apply_without_services_clears_the_stored_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A manifest with other config fields and no ``services`` replaces the stored config."""
    _arm_prefect(prefect_manager_mock)
    name, driver_name = await _existing(
        session, config={"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
    )
    manifest = _write_manifest(
        tmp_path / "app.yaml",
        name=name,
        driver=driver_name,
        config="    ip_whitelist:\n      - 10.0.0.0/8\n",
    )

    outcome = await _apply(client, manifest)

    assert outcome.action == "updated", outcome
    assert await _stored_config(session, name) == {"ip_whitelist": ["10.0.0.0/8"]}
