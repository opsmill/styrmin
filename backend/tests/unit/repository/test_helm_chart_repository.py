import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import HelmChart, HelmRepository
from styrmin_backend.repository.helm_chart import SQLModelHelmChartRepository
from styrmin_backend.repository.helm_repository import SQLModelHelmRepositoryRepository


@pytest.fixture
async def test_helm_repository(session: AsyncSession):
    repository = SQLModelHelmRepositoryRepository(session)
    helm_repo = await repository.create(
        HelmRepository(url="https://charts.example.com")
    )
    await session.flush()
    return helm_repo


@pytest.mark.asyncio
async def test_get_by_name_version(
    test_helm_repository: HelmRepository, session: AsyncSession
):
    repository = SQLModelHelmChartRepository(session)
    chart_name = "test_chart"
    chart_version = "1.0.0"

    chart = await repository.create(
        HelmChart(
            name=chart_name,
            version=chart_version,
            values_template="",
            repository_id=test_helm_repository.id,
        )
    )

    result = await repository.get_by_name_version(chart_name, chart_version)
    assert result == chart


@pytest.mark.asyncio
async def test_get_by_name_version_amongst_many(
    test_helm_repository: HelmRepository, session: AsyncSession
):
    repository = SQLModelHelmChartRepository(session)
    chart_name = "test_chart"
    chart_version = "1.0.0"

    await repository.create(
        HelmChart(
            name=chart_name,
            version=chart_version,
            values_template="",
            repository_id=test_helm_repository.id,
        )
    )
    await repository.create(
        HelmChart(
            name=chart_name,
            version="1.0.1",
            values_template="",
            repository_id=test_helm_repository.id,
        )
    )

    result = await repository.get_by_name_version(chart_name, chart_version)
    assert result is not None
    assert result.version == chart_version
