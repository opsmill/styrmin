"""Unit tests for ServiceDefinition validation (T010)."""

import pytest
from pydantic import ValidationError

from styrmin_backend.services.driver.models.resources.services import (
    ServiceDefinition,
    ServiceKind,
    ServiceScope,
    validate_service_names_unique,
)


def _make_service(**overrides) -> dict:
    """Helper to create a valid service definition dict with overrides."""
    defaults = {
        "name": "my-service",
        "kind": "http",
        "scope": "internal",
        "port": 8080,
        "component": "server",
    }
    defaults.update(overrides)
    return defaults


class TestServiceDefinitionValid:
    def test_valid_http_service(self) -> None:
        svc = ServiceDefinition(**_make_service())
        assert svc.name == "my-service"
        assert svc.kind == ServiceKind.HTTP
        assert svc.scope == ServiceScope.INTERNAL
        assert svc.port == 8080
        assert svc.component == "server"

    def test_valid_https_service(self) -> None:
        svc = ServiceDefinition(**_make_service(kind="https", scope="external"))
        assert svc.kind == ServiceKind.HTTPS
        assert svc.scope == ServiceScope.EXTERNAL

    def test_valid_tcp_service(self) -> None:
        svc = ServiceDefinition(**_make_service(kind="tcp", port=6379))
        assert svc.kind == ServiceKind.TCP

    def test_valid_udp_service(self) -> None:
        svc = ServiceDefinition(**_make_service(kind="udp", port=53))
        assert svc.kind == ServiceKind.UDP

    def test_min_port(self) -> None:
        svc = ServiceDefinition(**_make_service(port=1))
        assert svc.port == 1

    def test_max_port(self) -> None:
        svc = ServiceDefinition(**_make_service(port=65535))
        assert svc.port == 65535

    def test_single_char_name(self) -> None:
        svc = ServiceDefinition(**_make_service(name="a"))
        assert svc.name == "a"


class TestServiceDefinitionInvalidKind:
    def test_invalid_kind(self) -> None:
        with pytest.raises(ValidationError, match="kind"):
            ServiceDefinition(**_make_service(kind="grpc"))


class TestServiceDefinitionInvalidPort:
    def test_port_zero(self) -> None:
        with pytest.raises(ValidationError, match="Port must be between"):
            ServiceDefinition(**_make_service(port=0))

    def test_port_negative(self) -> None:
        with pytest.raises(ValidationError, match="Port must be between"):
            ServiceDefinition(**_make_service(port=-1))

    def test_port_too_large(self) -> None:
        with pytest.raises(ValidationError, match="Port must be between"):
            ServiceDefinition(**_make_service(port=65536))


class TestServiceDefinitionDNSLabelValidation:
    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DNS label"):
            ServiceDefinition(**_make_service(name="MyService"))

    def test_leading_hyphen_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DNS label"):
            ServiceDefinition(**_make_service(name="-service"))

    def test_trailing_hyphen_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DNS label"):
            ServiceDefinition(**_make_service(name="service-"))

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DNS label"):
            ServiceDefinition(**_make_service(name="a" * 64))

    def test_max_length_accepted(self) -> None:
        svc = ServiceDefinition(**_make_service(name="a" * 63))
        assert len(svc.name) == 63

    def test_underscore_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DNS label"):
            ServiceDefinition(**_make_service(name="my_service"))

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="DNS label"):
            ServiceDefinition(**_make_service(name=""))


class TestServiceDefinitionMissingFields:
    def test_missing_component(self) -> None:
        data = _make_service()
        del data["component"]
        with pytest.raises(ValidationError):
            ServiceDefinition(**data)

    def test_missing_name(self) -> None:
        data = _make_service()
        del data["name"]
        with pytest.raises(ValidationError):
            ServiceDefinition(**data)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServiceDefinition(**_make_service(extra_field="bad"))


class TestServiceNamesUnique:
    def test_unique_names(self) -> None:
        services = [
            ServiceDefinition(**_make_service(name="svc-a")),
            ServiceDefinition(**_make_service(name="svc-b")),
        ]
        result = validate_service_names_unique(services)
        assert result == services

    def test_duplicate_names(self) -> None:
        services = [
            ServiceDefinition(**_make_service(name="svc-a")),
            ServiceDefinition(**_make_service(name="svc-a")),
        ]
        with pytest.raises(ValueError, match="Duplicate service names"):
            validate_service_names_unique(services)

    def test_empty_list(self) -> None:
        result = validate_service_names_unique([])
        assert result == []


class TestOptionalServicesField:
    """Test that the services field on Specification is optional."""

    def test_services_field_none_by_default(self) -> None:
        """ServiceDefinition list can be None (no services section in driver)."""
        # This is tested at the Specification level in T011
        # Here we just verify the model itself works independently
        svc = ServiceDefinition(**_make_service())
        assert svc is not None
