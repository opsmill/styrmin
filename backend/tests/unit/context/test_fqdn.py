"""Unit tests for FQDN computation and DNS sanitization utilities."""

from uuid import UUID


from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
    to_fqdn_label,
)


class TestToFqdnLabel:
    """Tests for to_fqdn_label DNS sanitization."""

    def test_lowercase_conversion(self) -> None:
        assert to_fqdn_label("MyApp") == "myapp"

    def test_special_chars_replaced_with_hyphens(self) -> None:
        assert to_fqdn_label("my_app.name") == "my-app-name"

    def test_consecutive_hyphens_collapsed(self) -> None:
        assert to_fqdn_label("my--app---name") == "my-app-name"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert to_fqdn_label("-my-app-") == "my-app"

    def test_special_chars_at_edges_stripped(self) -> None:
        assert to_fqdn_label("...my-app...") == "my-app"

    def test_truncation_at_63_chars(self) -> None:
        long_name = "a" * 100
        result = to_fqdn_label(long_name)
        assert len(result) == 63

    def test_empty_string(self) -> None:
        assert to_fqdn_label("") == ""

    def test_already_valid_label(self) -> None:
        assert to_fqdn_label("valid-label-123") == "valid-label-123"

    def test_uuid_passthrough(self) -> None:
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        assert to_fqdn_label(uuid_str) == uuid_str

    def test_mixed_special_characters(self) -> None:
        assert to_fqdn_label("My App! @#$% v2.0") == "my-app-v2-0"


class TestComputePrimaryFqdn:
    """Tests for compute_primary_fqdn."""

    def test_with_valid_suffix(self) -> None:
        result = compute_primary_fqdn(
            "MyApp", "550e8400-e29b-41d4-a716-446655440000", "example.com"
        )
        assert result == "myapp-550e8400-e29b-41d4-a716-446655440000.example.com"

    def test_with_uuid_object(self) -> None:
        uid = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = compute_primary_fqdn("MyApp", uid, "example.com")
        assert result == "myapp-550e8400-e29b-41d4-a716-446655440000.example.com"

    def test_none_suffix_returns_none(self) -> None:
        result = compute_primary_fqdn("MyApp", "some-id", None)
        assert result is None

    def test_empty_suffix_returns_none(self) -> None:
        result = compute_primary_fqdn("MyApp", "some-id", "")
        assert result is None

    def test_app_name_sanitized(self) -> None:
        result = compute_primary_fqdn("My_App!!", "deploy-123", "example.com")
        assert result == "my-app-deploy-123.example.com"


class TestComputeHumanReadableFqdn:
    """Tests for compute_human_readable_fqdn."""

    def test_with_valid_suffix(self) -> None:
        result = compute_human_readable_fqdn("my-service", "production", "example.com")
        assert result == "my-service-production.example.com"

    def test_none_suffix_returns_none(self) -> None:
        result = compute_human_readable_fqdn("my-service", "production", None)
        assert result is None

    def test_empty_suffix_returns_none(self) -> None:
        result = compute_human_readable_fqdn("my-service", "production", "")
        assert result is None

    def test_host_sanitized(self) -> None:
        result = compute_human_readable_fqdn("My_Service!", "prod", "example.com")
        assert result == "my-service-prod.example.com"

    def test_environment_sanitized(self) -> None:
        result = compute_human_readable_fqdn("svc", "My Env!", "example.com")
        assert result == "svc-my-env.example.com"

    def test_both_components_sanitized(self) -> None:
        result = compute_human_readable_fqdn("My_Service", "Dev_Env", "example.com")
        assert result == "my-service-dev-env.example.com"
