"""Unit tests for FQDN computation and DNS sanitization utilities."""

import re
from uuid import UUID


from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
    to_fqdn_label,
)

_VALID_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _assert_valid_fqdn(fqdn: str | None, suffix: str) -> str:
    """Assert *fqdn* ends with ``.{suffix}`` and its left-hand label is valid."""
    assert fqdn is not None
    assert fqdn.endswith(f".{suffix}")
    label = fqdn[: -(len(suffix) + 1)]
    assert _VALID_LABEL_RE.match(label), f"invalid DNS label: {label!r}"
    assert len(label) <= 63
    return label


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

    def test_truncation_does_not_leave_trailing_hyphen(self) -> None:
        # 'a' * 63 + '-' + 'b' * 36 → after truncation char[63] would be '-'
        value = ("a" * 63) + "-" + ("b" * 36)
        result = to_fqdn_label(value)
        assert not result.endswith("-")
        assert _VALID_LABEL_RE.match(result)

    def test_empty_string(self) -> None:
        assert to_fqdn_label("") == ""

    def test_only_special_characters_yields_empty(self) -> None:
        assert to_fqdn_label("!!!@@@###") == ""

    def test_already_valid_label(self) -> None:
        assert to_fqdn_label("valid-label-123") == "valid-label-123"

    def test_uuid_passthrough(self) -> None:
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        assert to_fqdn_label(uuid_str) == uuid_str

    def test_mixed_special_characters(self) -> None:
        assert to_fqdn_label("My App! @#$% v2.0") == "my-app-v2-0"

    def test_unicode_replaced_with_hyphens(self) -> None:
        # Unicode characters are not allowed in DNS labels and must be replaced.
        assert to_fqdn_label("café-münchen") == "caf-m-nchen"


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

    def test_long_app_name_is_truncated_to_fit_label_limit(self) -> None:
        long_app = "a" * 200
        deployment_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        result = compute_primary_fqdn(long_app, deployment_id, "example.com")
        label = _assert_valid_fqdn(result, "example.com")
        # deployment_id (36 chars) must be preserved in full for uniqueness.
        assert label.endswith("-550e8400-e29b-41d4-a716-446655440000")

    def test_long_app_name_truncation_does_not_leave_trailing_hyphen(self) -> None:
        # Construct an app name whose sanitized truncation would end on a hyphen.
        # deployment_id length 36 → available_for_prefix = 63 - 1 - 36 = 26.
        # Use a sanitized fragment whose 26th char is '-'.
        app_name = "a" * 26 + "-" + "b" * 30  # sanitized → "a"*26 + "-" + "b"*30
        deployment_id = "550e8400-e29b-41d4-a716-446655440000"
        result = compute_primary_fqdn(app_name, deployment_id, "example.com")
        label = _assert_valid_fqdn(result, "example.com")
        assert label.endswith("-550e8400-e29b-41d4-a716-446655440000")

    def test_empty_app_name_uses_deployment_id_only(self) -> None:
        result = compute_primary_fqdn(
            "", "550e8400-e29b-41d4-a716-446655440000", "example.com"
        )
        assert result == "550e8400-e29b-41d4-a716-446655440000.example.com"

    def test_app_name_sanitizing_to_empty_uses_deployment_id_only(self) -> None:
        result = compute_primary_fqdn(
            "!!!@@@###", "550e8400-e29b-41d4-a716-446655440000", "example.com"
        )
        assert result == "550e8400-e29b-41d4-a716-446655440000.example.com"

    def test_both_components_empty_returns_none(self) -> None:
        # Defensive: if deployment_id sanitizes to empty too, no valid label exists.
        assert compute_primary_fqdn("", "", "example.com") is None
        assert compute_primary_fqdn("!!!", "@@@", "example.com") is None


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

    def test_long_host_truncated_env_preserved(self) -> None:
        result = compute_human_readable_fqdn("a" * 100, "production", "example.com")
        label = _assert_valid_fqdn(result, "example.com")
        # env label is preserved at the end for human recognizability.
        assert label.endswith("-production")

    def test_long_environment_alone_consumes_label_budget(self) -> None:
        # When the environment alone exceeds 63 chars, host is dropped to keep
        # the result valid and deterministic.
        result = compute_human_readable_fqdn("svc", "e" * 80, "example.com")
        label = _assert_valid_fqdn(result, "example.com")
        assert label == ("e" * 63)

    def test_empty_host_uses_environment_only(self) -> None:
        result = compute_human_readable_fqdn("", "production", "example.com")
        assert result == "production.example.com"

    def test_empty_environment_uses_host_only(self) -> None:
        result = compute_human_readable_fqdn("svc", "", "example.com")
        assert result == "svc.example.com"

    def test_host_sanitizing_to_empty_uses_environment_only(self) -> None:
        result = compute_human_readable_fqdn("!!!@@@", "production", "example.com")
        assert result == "production.example.com"

    def test_environment_sanitizing_to_empty_uses_host_only(self) -> None:
        result = compute_human_readable_fqdn("svc", "###", "example.com")
        assert result == "svc.example.com"

    def test_both_sanitizing_to_empty_returns_none(self) -> None:
        assert compute_human_readable_fqdn("!!!", "@@@", "example.com") is None
        assert compute_human_readable_fqdn("", "", "example.com") is None

    def test_unicode_inputs_remain_valid(self) -> None:
        result = compute_human_readable_fqdn("café", "münchen", "example.com")
        _assert_valid_fqdn(result, "example.com")
