import pytest
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession


class DummyModel(SQLModel, table=True):
    id: int | None = Field(primary_key=True, default=None)
    name: str = Field(unique=True)


class DummyModelRepository(BaseSQLModelRepository[DummyModel]):  # type: ignore[type-var]
    model_class = DummyModel


@pytest.mark.asyncio
async def test_create_test_model(session: AsyncSession):
    repository = DummyModelRepository(session)
    test_model = DummyModel(name="test_test_model")

    test_model = await repository.create(test_model)
    result = await session.exec(select(DummyModel))
    model_in_db = result.first()

    assert test_model == model_in_db


@pytest.mark.asyncio
async def test_get_test_model(session: AsyncSession):
    test_model = DummyModel(name="test_test_model")
    session.add(test_model)
    await session.commit()
    await session.refresh(test_model)

    repository = DummyModelRepository(session)
    result = await repository.get(test_model.id)  # type: ignore[arg-type]

    assert result == test_model
    assert result.id == test_model.id
    assert result.name == test_model.name


@pytest.mark.asyncio
async def test_get_all_test_models(session: AsyncSession):
    test_model1 = DummyModel(name="test_test_model1")
    test_model2 = DummyModel(name="test_test_model2")
    session.add(test_model1)
    session.add(test_model2)
    await session.commit()

    repository = DummyModelRepository(session)
    result = await repository.get_all()

    assert len(result) == 2
    assert test_model1 in result
    assert test_model2 in result


@pytest.mark.asyncio
async def test_delete_test_model(session: AsyncSession):
    test_model = DummyModel(name="test_test_model")
    session.add(test_model)
    await session.commit()
    await session.refresh(test_model)

    repository = DummyModelRepository(session)
    await repository.delete(test_model)
    await session.commit()

    result = await session.exec(select(DummyModel))
    assert result.first() is None
