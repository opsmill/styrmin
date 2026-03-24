from uuid import uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationDriverVersion,
    Environment,
    InstanceStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.applications import (
    instantiate_application,
)
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    EnvironmentNotFoundError,
    InvalidVersionError,
)
from tests.unit.services.fakes import (
    FakeUnitOfWork,
)


async def test_instantiate_application_with_invalid_version(
    prefect_manager_mock,
    fake_environment: Environment,
    fake_application: ApplicationDriverVersion,
    uow: FakeUnitOfWork,
):
    """Test that instantiate_application raises an error when version doesn't match specifier."""
    instance_config = {
        "ingress_class": "instance_ingress_class",
        "db_size": "200Gi",
    }

    with pytest.raises(InvalidVersionError):
        await instantiate_application(
            name="test_instance",
            version="0.0.1",  # Version that doesn't match >=1.0.0
            application_id=fake_application.id,
            environment_id=fake_environment.id,
            instance_config=instance_config,
            uow=uow,
        )


async def test_instantiate_application_with_nonexistent_application(
    prefect_manager_mock,
    fake_environment: Environment,
    uow: FakeUnitOfWork,
):
    """Test that instantiate_application raises an error when application doesn't exist."""
    with pytest.raises(ApplicationDriverNotFoundError):
        await instantiate_application(
            name="test_instance",
            version="1.0.0",
            application_id=uuid4(),  # Non-existent application
            environment_id=fake_environment.id,
            instance_config={},
            uow=uow,
        )


async def test_instantiate_application_with_nonexistent_environment(
    prefect_manager_mock,
    fake_application: ApplicationDriverVersion,
    uow: FakeUnitOfWork,
):
    """Test that instantiate_application raises an error when environment doesn't exist."""
    with pytest.raises(EnvironmentNotFoundError):
        await instantiate_application(
            name="test_instance",
            version="1.0.0",
            application_id=fake_application.id,
            environment_id=uuid4(),  # Non-existent environment
            instance_config={},
            uow=uow,
        )


async def test_instantiate_application(
    prefect_manager_mock,
    fake_environment: Environment,
    fake_application: ApplicationDriverVersion,
    uow: FakeUnitOfWork,
):
    """Test that instantiate_application creates a task and instance correctly."""
    instance_config = {
        "ingress_class": "instance_ingress_class",
        "db_size": "200Gi",
    }

    # Mock the prefect_manager methods
    core_deployment_id = uuid4()
    flow_run_id = uuid4()
    prefect_manager_mock.get_user_action_deployment_id.return_value = None
    prefect_manager_mock.get_action_deployment_id.return_value = core_deployment_id

    # Create a mock for the workflow info return value
    from unittest.mock import MagicMock

    mock_workflow_info = MagicMock()
    mock_workflow_info.info.id = flow_run_id
    prefect_manager_mock.run_action.return_value = mock_workflow_info

    task: Task = await instantiate_application(
        name="test_instance",
        version="1.0.0",
        application_id=fake_application.id,
        environment_id=fake_environment.id,
        instance_config=instance_config,
        uow=uow,
    )

    # Verify task was created correctly
    assert task is not None
    assert task.status == TaskStatus.PENDING
    assert task.type == TaskType.CREATE_INSTANCE
    assert task.prefect_flow_run_id == flow_run_id

    # Verify instance was created
    instances = await uow.instances.get_all()
    assert len(instances) == 1
    instance = instances[0]
    assert instance.name == "test_instance"
    assert instance.status == InstanceStatus.PENDING
    assert instance.application_version == "1.0.0"

    # Verify prefect_manager was called correctly
    prefect_manager_mock.run_action.assert_called_once()
    assert uow.committed
