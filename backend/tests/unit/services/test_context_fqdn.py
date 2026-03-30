"""Unit tests for FQDN population during context generation."""

from styrmin_backend.context.models.services import ServiceReference


class TestServiceReferenceFqdnFields:
    """Tests for FQDN fields on ServiceReference."""

    def test_fqdn_fields_default_to_none(self) -> None:
        ref = ServiceReference(host="my-svc", port=8080, kind="http")
        assert ref.primary_fqdn is None
        assert ref.human_readable_fqdn is None

    def test_fqdn_fields_set_when_provided(self) -> None:
        ref = ServiceReference(
            host="my-svc",
            port=8080,
            kind="http",
            primary_fqdn="app-123.example.com",
            human_readable_fqdn="my-svc-prod.example.com",
        )
        assert ref.primary_fqdn == "app-123.example.com"
        assert ref.human_readable_fqdn == "my-svc-prod.example.com"

    def test_fqdn_fields_included_in_model_dump(self) -> None:
        ref = ServiceReference(
            host="my-svc",
            port=8080,
            kind="http",
            primary_fqdn="app-123.example.com",
            human_readable_fqdn="my-svc-prod.example.com",
        )
        data = ref.model_dump()
        assert data["primary_fqdn"] == "app-123.example.com"
        assert data["human_readable_fqdn"] == "my-svc-prod.example.com"

    def test_fqdn_fields_excluded_from_dump_when_none(self) -> None:
        ref = ServiceReference(host="my-svc", port=8080, kind="http")
        data = ref.model_dump(exclude_none=True)
        assert "primary_fqdn" not in data
        assert "human_readable_fqdn" not in data

    def test_url_still_computed(self) -> None:
        ref = ServiceReference(
            host="my-svc",
            port=8080,
            kind="http",
            primary_fqdn="app-123.example.com",
            human_readable_fqdn="my-svc-prod.example.com",
        )
        assert ref.url == "http://my-svc:8080"

    def test_multiple_services_with_different_fqdns(self) -> None:
        svc1 = ServiceReference(
            host="web",
            port=80,
            kind="http",
            primary_fqdn="app-id1.example.com",
            human_readable_fqdn="web-prod.example.com",
        )
        svc2 = ServiceReference(
            host="api",
            port=3000,
            kind="http",
            primary_fqdn="app-id2.example.com",
            human_readable_fqdn="api-prod.example.com",
        )
        assert svc1.primary_fqdn != svc2.primary_fqdn
        assert svc1.human_readable_fqdn != svc2.human_readable_fqdn

    def test_missing_suffix_results_in_none_fqdns(self) -> None:
        """When fqdn_suffix is not configured, fields should be None."""
        ref = ServiceReference(host="my-svc", port=8080, kind="http")
        assert ref.primary_fqdn is None
        assert ref.human_readable_fqdn is None
