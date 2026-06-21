"""Tests for parameter validation service."""

import pytest

from styrmin_backend.services.driver.models.resources.parameters import (
    DriverParameterDefinition,
    DriverParameterKind,
)
from styrmin_backend.services.exceptions import ServiceError
from styrmin_backend.services.parameters import (
    parse_parameter_definitions,
    validate_parameter_values,
)


SAMPLE_DEFINITIONS = [
    DriverParameterDefinition(
        name="replicas", label="Replicas", kind=DriverParameterKind.INTEGER, default=1
    ),
    DriverParameterDefinition(
        name="log_level",
        label="Log level",
        kind=DriverParameterKind.ENUM,
        values=["debug", "info", "warning", "error"],
        default="info",
    ),
    DriverParameterDefinition(
        name="enable_metrics",
        label="Metrics",
        kind=DriverParameterKind.BOOLEAN,
        default=False,
    ),
    DriverParameterDefinition(
        name="custom_domain", label="Domain", kind=DriverParameterKind.STRING
    ),
]


class TestValidateParameterValues:
    """Tests for validate_parameter_values()."""

    def test_valid_values_all_provided(self) -> None:
        values = {
            "replicas": 3,
            "log_level": "debug",
            "enable_metrics": True,
            "custom_domain": "app.example.com",
        }
        result = validate_parameter_values(SAMPLE_DEFINITIONS, values)
        assert result == values

    def test_defaults_applied_for_omitted_optional_params(self) -> None:
        values = {"custom_domain": "app.example.com"}
        result = validate_parameter_values(SAMPLE_DEFINITIONS, values)
        assert result == {
            "replicas": 1,
            "log_level": "info",
            "enable_metrics": False,
            "custom_domain": "app.example.com",
        }

    def test_missing_required_param_raises_error(self) -> None:
        # custom_domain has no default, so it's required
        values = {"replicas": 2}
        with pytest.raises(
            ServiceError, match="Missing required parameter: 'custom_domain'"
        ):
            validate_parameter_values(SAMPLE_DEFINITIONS, values)

    def test_unknown_param_raises_error(self) -> None:
        values = {"custom_domain": "x", "nonexistent": "value"}
        with pytest.raises(ServiceError, match="Unknown parameter: 'nonexistent'"):
            validate_parameter_values(SAMPLE_DEFINITIONS, values)

    def test_type_mismatch_integer_got_string(self) -> None:
        values = {"replicas": "abc", "custom_domain": "x"}
        with pytest.raises(
            ServiceError, match="Parameter 'replicas': expected integer, got str"
        ):
            validate_parameter_values(SAMPLE_DEFINITIONS, values)

    def test_type_mismatch_boolean_got_string(self) -> None:
        values = {"enable_metrics": "true", "custom_domain": "x"}
        with pytest.raises(
            ServiceError, match="Parameter 'enable_metrics': expected boolean, got str"
        ):
            validate_parameter_values(SAMPLE_DEFINITIONS, values)

    def test_invalid_enum_value(self) -> None:
        values = {"log_level": "verbose", "custom_domain": "x"}
        with pytest.raises(
            ServiceError,
            match="Parameter 'log_level': value 'verbose' is not in allowed values",
        ):
            validate_parameter_values(SAMPLE_DEFINITIONS, values)

    def test_boolean_rejected_as_integer(self) -> None:
        values = {"replicas": True, "custom_domain": "x"}
        with pytest.raises(
            ServiceError, match="Parameter 'replicas': expected integer, got bool"
        ):
            validate_parameter_values(SAMPLE_DEFINITIONS, values)

    def test_no_definitions_no_values_succeeds(self) -> None:
        result = validate_parameter_values([], {})
        assert result == {}

    def test_no_definitions_none_values_succeeds(self) -> None:
        result = validate_parameter_values([], None)
        assert result == {}

    def test_no_definitions_with_values_raises_error(self) -> None:
        with pytest.raises(ServiceError, match="Unknown parameter"):
            validate_parameter_values([], {"replicas": 1})

    def test_all_defaults_no_values_provided(self) -> None:
        definitions = [
            DriverParameterDefinition(
                name="replicas", label="R", kind=DriverParameterKind.INTEGER, default=1
            ),
            DriverParameterDefinition(
                name="debug", label="D", kind=DriverParameterKind.BOOLEAN, default=False
            ),
        ]
        result = validate_parameter_values(definitions, {})
        assert result == {"replicas": 1, "debug": False}

    def test_all_defaults_none_values(self) -> None:
        definitions = [
            DriverParameterDefinition(
                name="replicas", label="R", kind=DriverParameterKind.INTEGER, default=1
            ),
        ]
        result = validate_parameter_values(definitions, None)
        assert result == {"replicas": 1}

    def test_none_definitions_treated_as_empty(self) -> None:
        """When driver has no parameter definitions (None from DB)."""
        result = validate_parameter_values([], None)
        assert result == {}


INFRAHUB_MCP_DEFINITIONS = [
    DriverParameterDefinition(
        name="infrahub_address",
        label="Infrahub address",
        kind=DriverParameterKind.STRING,
    ),
]


class TestInfrahubMcpParameters:
    """Parameter-validation tests for the infrahub-mcp Driver (015, US1).

    US1 declares only ``infrahub_address``. Later chunks (US2/US3) extend this
    class to cover ``mcp_read_only`` and ``mcp_log_level``.
    """

    def test_infrahub_address_only_resolves(self) -> None:
        values = {"infrahub_address": "https://infrahub.example.com"}
        result = validate_parameter_values(INFRAHUB_MCP_DEFINITIONS, values)
        assert result == {"infrahub_address": "https://infrahub.example.com"}

    def test_missing_infrahub_address_raises(self) -> None:
        with pytest.raises(
            ServiceError, match="Missing required parameter: 'infrahub_address'"
        ):
            validate_parameter_values(INFRAHUB_MCP_DEFINITIONS, {})

    def test_unknown_parameter_raises(self) -> None:
        values = {
            "infrahub_address": "https://infrahub.example.com",
            "bogus": 1,
        }
        with pytest.raises(ServiceError, match="Unknown parameter: 'bogus'"):
            validate_parameter_values(INFRAHUB_MCP_DEFINITIONS, values)


class TestParseParameterDefinitions:
    """Tests for parse_parameter_definitions()."""

    def test_parse_none_returns_empty(self) -> None:
        assert parse_parameter_definitions(None) == []

    def test_parse_empty_list_returns_empty(self) -> None:
        assert parse_parameter_definitions([]) == []

    def test_parse_valid_dicts(self) -> None:
        raw: list[dict] = [
            {"name": "replicas", "label": "R", "kind": "integer", "default": 1},
            {"name": "mode", "label": "M", "kind": "string"},
        ]
        result = parse_parameter_definitions(raw)
        assert len(result) == 2
        assert result[0].name == "replicas"
        assert result[0].kind == DriverParameterKind.INTEGER
        assert result[1].kind == DriverParameterKind.STRING
