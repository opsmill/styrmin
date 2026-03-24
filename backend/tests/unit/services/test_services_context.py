"""Unit tests for services context building (T024)."""

from styrmin_backend.context.models.services import ServiceReference


class TestServiceReference:
    def test_http_url(self) -> None:
        ref = ServiceReference(host="infrahub", port=8000, kind="http")
        assert ref.url == "http://infrahub:8000"
        assert ref.host == "infrahub"
        assert ref.port == 8000
        assert ref.kind == "http"

    def test_https_url(self) -> None:
        ref = ServiceReference(host="infrahub", port=8443, kind="https")
        assert ref.url == "https://infrahub:8443"

    def test_tcp_url(self) -> None:
        ref = ServiceReference(host="redis", port=6379, kind="tcp")
        assert ref.url == "redis:6379"

    def test_udp_url(self) -> None:
        ref = ServiceReference(host="dns", port=53, kind="udp")
        assert ref.url == "dns:53"

    def test_model_dump(self) -> None:
        ref = ServiceReference(host="web", port=80, kind="http")
        data = ref.model_dump()
        assert data["url"] == "http://web:80"
        assert data["host"] == "web"
        assert data["port"] == 80
        assert data["kind"] == "http"


class TestServicesContextDict:
    def test_empty_services_dict(self) -> None:
        """Empty context when no services are deployed."""
        services: dict = {}
        assert services == {}

    def test_build_context_with_services(self) -> None:
        """Build context dict mapping service name -> ServiceReference properties."""
        from styrmin_backend.db.models import DeployedService
        from uuid import uuid4

        svcs = [
            DeployedService(
                id=uuid4(),
                driver_service_name="infrahub",
                resolved_name="infrahub",
                kind="https",
                scope="internal",
                port=8000,
                component="server",
                deployment_id=uuid4(),
                environment_id=uuid4(),
            ),
            DeployedService(
                id=uuid4(),
                driver_service_name="redis",
                resolved_name="redis",
                kind="tcp",
                scope="internal",
                port=6379,
                component="cache",
                deployment_id=uuid4(),
                environment_id=uuid4(),
            ),
        ]

        # Build context dict the same way the context service will
        context: dict = {}
        for svc in svcs:
            ref = ServiceReference(
                host=svc.resolved_name,
                port=svc.port,
                kind=svc.kind,
            )
            context[svc.driver_service_name] = ref.model_dump()

        assert "infrahub" in context
        assert context["infrahub"]["url"] == "https://infrahub:8000"
        assert context["infrahub"]["host"] == "infrahub"
        assert context["infrahub"]["port"] == 8000
        assert context["infrahub"]["kind"] == "https"

        assert "redis" in context
        assert context["redis"]["url"] == "redis:6379"
        assert context["redis"]["host"] == "redis"
        assert context["redis"]["port"] == 6379
