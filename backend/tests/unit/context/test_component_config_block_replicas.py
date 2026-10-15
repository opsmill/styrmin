"""``ComponentConfigBlock.replicas``: the stored replica override (023, research D-001).

The ``mode="before"`` validator raises ``INVALID_REPLICA_COUNT`` before type conversion, so
``True``, ``"2"`` and ``2.0`` never reach the stored config as an integer.
"""

from __future__ import annotations

import pytest

from styrmin_backend.context.models.config import ComponentConfigBlock, DeploymentConfig
from styrmin_backend.context.validators import validate_deployment_config
from styrmin_backend.services.replicas.exceptions import InvalidReplicaCountError

_INVALID = [0, -1, 2147483648, True, False, "2", 2.0]
_INVALID_IDS = ["zero", "negative", "above-int32", "true", "false", "string", "float"]


@pytest.mark.parametrize("value", [None, 1, 3, 2147483647])
def test_valid_replica_count_is_stored(value: int | None) -> None:
    block = ComponentConfigBlock.model_validate({"replicas": value})

    assert block.replicas == value


def test_block_without_the_key_reads_as_none() -> None:
    assert ComponentConfigBlock.model_validate({}).replicas is None


def test_stored_config_without_the_key_reads_as_none() -> None:
    config = DeploymentConfig.model_validate(
        {"components": {"server": {"env_vars": {"A": "1"}}}}
    )

    assert config.components is not None
    assert config.components["server"].replicas is None


@pytest.mark.parametrize("value", _INVALID, ids=_INVALID_IDS)
def test_invalid_count_raises_typed_error_with_component_name(value: object) -> None:
    with pytest.raises(InvalidReplicaCountError) as exc_info:
        DeploymentConfig.model_validate({"components": {"server": {"replicas": value}}})

    error = exc_info.value
    assert error.error_code == "INVALID_REPLICA_COUNT"
    assert error.error_metadata == {
        "component_name": "server",
        "requested_replicas": value,
    }
    assert "Replica count for component 'server'" in str(error)
    assert "from 1 to 2147483647" in str(error)
    assert "stop the component instead" in str(error)


@pytest.mark.parametrize("value", _INVALID, ids=_INVALID_IDS)
def test_block_validation_reads_component_name_from_context(value: object) -> None:
    with pytest.raises(InvalidReplicaCountError) as exc_info:
        ComponentConfigBlock.model_validate(
            {"replicas": value}, context={"component_name": "worker"}
        )

    assert exc_info.value.error_metadata == {
        "component_name": "worker",
        "requested_replicas": value,
    }


def test_block_validation_without_a_name_still_raises_typed_error() -> None:
    with pytest.raises(InvalidReplicaCountError) as exc_info:
        ComponentConfigBlock.model_validate({"replicas": 0})

    assert exc_info.value.error_metadata["component_name"] is None
    assert exc_info.value.error_metadata["requested_replicas"] == 0


def test_write_path_surfaces_typed_error() -> None:
    """``validate_deployment_config`` wraps only ``ValidationError``; the typed code survives."""
    with pytest.raises(InvalidReplicaCountError):
        validate_deployment_config({"components": {"server": {"replicas": 0}}})
