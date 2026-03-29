"""Unit tests for DeployedService FQDN resolver fields."""

from typing import Any
from uuid import uuid4

from styrmin_backend.api.definitions.service.model import DeployedService
from styrmin_backend.db.models import DeployedService as DeployedServiceModel


def _make_db_service(**overrides: Any) -> DeployedServiceModel:
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "driver_service_name": "web",
        "resolved_name": "web-svc",
        "kind": "http",
        "scope": "internal",
        "port": 8080,
        "component": "server",
        "deployment_id": uuid4(),
        "environment_id": uuid4(),
    }
    defaults.update(overrides)
    return DeployedServiceModel(**defaults)


class TestDeployedServiceFqdnFields:
    """Tests for primaryFqdn and humanReadableFqdn resolver fields."""

    def test_fqdns_present_when_injected(self) -> None:
        db_svc = _make_db_service()
        gql_svc = DeployedService.from_instance(
            db_svc,
            primary_fqdn="myapp-123.example.com",
            human_readable_fqdn="web-svc-prod.example.com",
        )
        assert gql_svc.primary_fqdn == "myapp-123.example.com"
        assert gql_svc.human_readable_fqdn == "web-svc-prod.example.com"

    def test_fqdns_none_when_not_provided(self) -> None:
        db_svc = _make_db_service()
        gql_svc = DeployedService.from_instance(db_svc)
        assert gql_svc.primary_fqdn is None
        assert gql_svc.human_readable_fqdn is None

    def test_fqdns_none_when_explicitly_none(self) -> None:
        db_svc = _make_db_service()
        gql_svc = DeployedService.from_instance(
            db_svc, primary_fqdn=None, human_readable_fqdn=None
        )
        assert gql_svc.primary_fqdn is None
        assert gql_svc.human_readable_fqdn is None

    def test_existing_fields_preserved(self) -> None:
        db_svc = _make_db_service(
            driver_service_name="api",
            resolved_name="api-svc",
            port=3000,
        )
        gql_svc = DeployedService.from_instance(
            db_svc,
            primary_fqdn="app-uuid.example.com",
            human_readable_fqdn="api-svc-prod.example.com",
        )
        assert gql_svc.driver_service_name == "api"
        assert gql_svc.resolved_name == "api-svc"
        assert gql_svc.port == 3000
        assert gql_svc.instance.deployment_id == db_svc.deployment_id

    def test_fqdn_with_sanitized_values(self) -> None:
        """FQDNs should already be sanitized when injected."""
        db_svc = _make_db_service()
        gql_svc = DeployedService.from_instance(
            db_svc,
            primary_fqdn="my-app-550e8400-e29b-41d4-a716-446655440000.example.com",
            human_readable_fqdn="web-svc-production.example.com",
        )
        assert (
            gql_svc.primary_fqdn
            == "my-app-550e8400-e29b-41d4-a716-446655440000.example.com"
        )
        assert gql_svc.human_readable_fqdn == "web-svc-production.example.com"
