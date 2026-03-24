"""Tests for driver parameter definition model validation."""

import pytest
from pydantic import ValidationError

from styrmin_backend.services.driver.models.resources.parameters import (
    DriverParameterDefinition,
    DriverParameterKind,
    validate_parameter_names_unique,
)
from styrmin_backend.services.driver.models.resources.driver import Specification


class TestDriverParameterDefinition:
    """Tests for DriverParameterDefinition Pydantic model."""

    def test_valid_string_parameter(self) -> None:
        param = DriverParameterDefinition(
            name="custom_domain",
            label="Custom domain name",
            kind=DriverParameterKind.STRING,
        )
        assert param.name == "custom_domain"
        assert param.kind == DriverParameterKind.STRING
        assert param.default is None
        assert param.values is None

    def test_valid_string_parameter_with_default(self) -> None:
        param = DriverParameterDefinition(
            name="hostname",
            label="Hostname",
            kind=DriverParameterKind.STRING,
            default="localhost",
        )
        assert param.default == "localhost"

    def test_valid_integer_parameter(self) -> None:
        param = DriverParameterDefinition(
            name="replicas",
            label="Number of replicas",
            kind=DriverParameterKind.INTEGER,
            default=1,
        )
        assert param.default == 1

    def test_valid_boolean_parameter(self) -> None:
        param = DriverParameterDefinition(
            name="enable_metrics",
            label="Enable Prometheus metrics",
            kind=DriverParameterKind.BOOLEAN,
            default=False,
        )
        assert param.default is False

    def test_valid_enum_parameter(self) -> None:
        param = DriverParameterDefinition(
            name="log_level",
            label="Log level",
            kind=DriverParameterKind.ENUM,
            values=["debug", "info", "warning", "error"],
            default="info",
        )
        assert param.values == ["debug", "info", "warning", "error"]
        assert param.default == "info"

    def test_enum_without_values_raises_error(self) -> None:
        with pytest.raises(
            ValidationError, match="enum kind requires a non-empty 'values' list"
        ):
            DriverParameterDefinition(
                name="log_level",
                label="Log level",
                kind=DriverParameterKind.ENUM,
            )

    def test_enum_with_empty_values_raises_error(self) -> None:
        with pytest.raises(
            ValidationError, match="enum kind requires a non-empty 'values' list"
        ):
            DriverParameterDefinition(
                name="log_level",
                label="Log level",
                kind=DriverParameterKind.ENUM,
                values=[],
            )

    def test_non_enum_with_values_raises_error(self) -> None:
        with pytest.raises(
            ValidationError, match="'values' is only allowed for enum kind"
        ):
            DriverParameterDefinition(
                name="replicas",
                label="Replicas",
                kind=DriverParameterKind.INTEGER,
                values=["1", "2", "3"],
            )

    def test_default_type_mismatch_string_got_int(self) -> None:
        with pytest.raises(ValidationError, match="default value must be str"):
            DriverParameterDefinition(
                name="hostname",
                label="Hostname",
                kind=DriverParameterKind.STRING,
                default=123,
            )

    def test_default_type_mismatch_integer_got_string(self) -> None:
        with pytest.raises(ValidationError, match="default value must be int"):
            DriverParameterDefinition(
                name="replicas",
                label="Replicas",
                kind=DriverParameterKind.INTEGER,
                default="abc",
            )

    def test_default_type_mismatch_boolean_got_string(self) -> None:
        with pytest.raises(ValidationError, match="default value must be bool"):
            DriverParameterDefinition(
                name="enabled",
                label="Enabled",
                kind=DriverParameterKind.BOOLEAN,
                default="true",
            )

    def test_default_type_mismatch_integer_got_bool(self) -> None:
        with pytest.raises(ValidationError, match="default value must be int"):
            DriverParameterDefinition(
                name="replicas",
                label="Replicas",
                kind=DriverParameterKind.INTEGER,
                default=True,
            )

    def test_enum_default_not_in_values(self) -> None:
        with pytest.raises(
            ValidationError, match="default value 'verbose' is not in allowed values"
        ):
            DriverParameterDefinition(
                name="log_level",
                label="Log level",
                kind=DriverParameterKind.ENUM,
                values=["debug", "info", "warning", "error"],
                default="verbose",
            )

    def test_enum_parameter_without_default(self) -> None:
        param = DriverParameterDefinition(
            name="log_level",
            label="Log level",
            kind=DriverParameterKind.ENUM,
            values=["debug", "info"],
        )
        assert param.default is None


class TestParameterNameUniqueness:
    """Tests for parameter name uniqueness validation."""

    def test_unique_names_pass(self) -> None:
        params = [
            DriverParameterDefinition(
                name="a", label="A", kind=DriverParameterKind.STRING
            ),
            DriverParameterDefinition(
                name="b", label="B", kind=DriverParameterKind.INTEGER, default=1
            ),
        ]
        result = validate_parameter_names_unique(params)
        assert len(result) == 2

    def test_duplicate_names_raise_error(self) -> None:
        params = [
            DriverParameterDefinition(
                name="replicas", label="A", kind=DriverParameterKind.INTEGER, default=1
            ),
            DriverParameterDefinition(
                name="replicas", label="B", kind=DriverParameterKind.INTEGER, default=2
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate parameter names"):
            validate_parameter_names_unique(params)


class TestSpecificationWithParameters:
    """Tests for Specification model with parameters field."""

    def test_specification_without_parameters(self) -> None:
        """Backward compatibility: specs without parameters should work."""
        spec_data = {
            "version": "1",
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Test"},
            "helm": {"main": {"location": "oci://test/chart", "version": "1.0.0"}},
        }
        spec = Specification.model_validate(spec_data)
        assert spec.parameters is None

    def test_specification_with_empty_parameters(self) -> None:
        spec_data = {
            "version": "1",
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Test"},
            "helm": {"main": {"location": "oci://test/chart", "version": "1.0.0"}},
            "parameters": [],
        }
        spec = Specification.model_validate(spec_data)
        assert spec.parameters == []

    def test_specification_with_valid_parameters(self) -> None:
        spec_data = {
            "version": "1",
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Test"},
            "helm": {"main": {"location": "oci://test/chart", "version": "1.0.0"}},
            "parameters": [
                {
                    "name": "replicas",
                    "label": "Replicas",
                    "kind": "integer",
                    "default": 1,
                },
                {
                    "name": "log_level",
                    "label": "Log level",
                    "kind": "enum",
                    "values": ["debug", "info"],
                    "default": "info",
                },
            ],
        }
        spec = Specification.model_validate(spec_data)
        assert spec.parameters is not None
        assert len(spec.parameters) == 2

    def test_specification_with_duplicate_parameter_names(self) -> None:
        spec_data = {
            "version": "1",
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Test"},
            "helm": {"main": {"location": "oci://test/chart", "version": "1.0.0"}},
            "parameters": [
                {"name": "replicas", "label": "A", "kind": "integer", "default": 1},
                {"name": "replicas", "label": "B", "kind": "integer", "default": 2},
            ],
        }
        with pytest.raises(ValidationError, match="Duplicate parameter names"):
            Specification.model_validate(spec_data)
