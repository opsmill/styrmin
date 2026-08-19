"""Unit tests for the clone's environment-config merge (010 research D7).

Two rules carry the whole feature's US3 story:

* the override is a **top-level-field replacement** — override a field and you
  own that whole field, matching the granularity ADR-0012 fixed for
  ``updateEnvironment``;
* ``cleared_fields`` is the only way to *remove* a copied scalar, because the
  override input omits ``None``-valued fields and therefore cannot express
  "unset this" — which is exactly what "clone production without its real DNS"
  needs.
"""

import pytest

from styrmin_backend.services.backup.clone import merge_environment_config
from styrmin_backend.services.exceptions import (
    InvalidContextError,
    UnknownEnvironmentConfigFieldError,
)

PRODUCTION_CONFIG = {
    "fqdn_suffix": "prod.example.com",
    "ingress_class": "nginx",
    "db_size": "100Gi",
    "external_dns_endpoints_type": "NodeExternalIP",
    "env_vars": {"REGION": "eu-west-1", "TIER": "prod"},
    "ip_whitelist": ["10.0.0.0/8"],
}


def test_no_override_returns_the_captured_config() -> None:
    assert merge_environment_config(PRODUCTION_CONFIG) == PRODUCTION_CONFIG


def test_a_missing_captured_config_is_an_empty_one() -> None:
    assert merge_environment_config(None) == {}
    assert merge_environment_config(None, {"db_size": "10Gi"}) == {"db_size": "10Gi"}


def test_the_captured_config_is_canonicalised() -> None:
    """``None``-vs-missing drift is flattened, as in ``_deployment_already_at_config``."""
    assert merge_environment_config(
        {"db_size": "10Gi", "fqdn_suffix": None, "ip_whitelist": None}
    ) == {"db_size": "10Gi"}


def test_the_input_mappings_are_not_mutated() -> None:
    """Callers persist the override verbatim on the clone row (FR-006)."""
    captured = dict(PRODUCTION_CONFIG)
    override = {"db_size": "10Gi"}

    merge_environment_config(captured, override, ["fqdn_suffix"])

    assert captured == PRODUCTION_CONFIG
    assert override == {"db_size": "10Gi"}


def test_an_overridden_field_replaces_the_captured_one_and_peers_survive() -> None:
    merged = merge_environment_config(PRODUCTION_CONFIG, {"db_size": "10Gi"})

    assert merged["db_size"] == "10Gi"
    assert merged["fqdn_suffix"] == "prod.example.com"
    assert merged["env_vars"] == {"REGION": "eu-west-1", "TIER": "prod"}


def test_a_dict_valued_field_is_replaced_wholesale_not_deep_merged() -> None:
    """The rejected alternative: ``TIER`` must NOT survive under the new dict."""
    merged = merge_environment_config(
        PRODUCTION_CONFIG, {"env_vars": {"REGION": "local"}}
    )

    assert merged["env_vars"] == {"REGION": "local"}


def test_a_list_valued_field_is_replaced_wholesale() -> None:
    merged = merge_environment_config(
        PRODUCTION_CONFIG, {"ip_whitelist": ["192.168.0.0/16"]}
    )

    assert merged["ip_whitelist"] == ["192.168.0.0/16"]


def test_a_cleared_field_is_absent_from_the_result() -> None:
    """US3: production-only settings are removed, not merely changed (FR-006)."""
    merged = merge_environment_config(
        PRODUCTION_CONFIG,
        None,
        ["fqdn_suffix", "external_dns_endpoints_type"],
    )

    assert "fqdn_suffix" not in merged
    assert "external_dns_endpoints_type" not in merged
    assert merged["ingress_class"] == "nginx"


def test_clearing_a_field_the_capture_never_had_is_a_no_op() -> None:
    assert merge_environment_config({"db_size": "10Gi"}, None, ["fqdn_suffix"]) == {
        "db_size": "10Gi"
    }


def test_a_field_both_cleared_and_overridden_takes_the_override_value() -> None:
    """The merge runs after the pop, so the override always wins (research D7)."""
    merged = merge_environment_config(
        PRODUCTION_CONFIG,
        {"fqdn_suffix": "dev.example.com"},
        ["fqdn_suffix"],
    )

    assert merged["fqdn_suffix"] == "dev.example.com"


def test_clearing_everything_yields_an_empty_config() -> None:
    merged = merge_environment_config(
        PRODUCTION_CONFIG, None, list(PRODUCTION_CONFIG.keys())
    )

    assert merged == {}


def test_an_unknown_cleared_field_is_a_typed_validation_error() -> None:
    with pytest.raises(UnknownEnvironmentConfigFieldError) as excinfo:
        merge_environment_config(PRODUCTION_CONFIG, None, ["fqdn_suffix", "dns_zone"])

    error = excinfo.value
    assert error.error_code == "VALIDATION_ERROR"
    assert error.error_metadata["fields"] == ["dns_zone"]
    assert "fqdn_suffix" in error.error_metadata["known_fields"]
    assert "dns_zone" in str(error)


def test_an_unknown_cleared_field_is_rejected_before_anything_is_merged() -> None:
    """FR-011's zero-side-effects discipline: validate names first."""
    with pytest.raises(UnknownEnvironmentConfigFieldError):
        merge_environment_config({"not-a-field": 1}, None, ["nonsense"])


def test_an_invalid_override_is_a_typed_validation_error() -> None:
    with pytest.raises(InvalidContextError) as excinfo:
        merge_environment_config(PRODUCTION_CONFIG, {"backup_ttl": "30d"})

    assert excinfo.value.error_code == "VALIDATION_ERROR"
    assert "override" in str(excinfo.value)
    assert "backup_ttl" in str(excinfo.value)


def test_an_unknown_override_field_is_rejected() -> None:
    """``EnvironmentConfig`` forbids extras, so a typo cannot reach the clone."""
    with pytest.raises(InvalidContextError):
        merge_environment_config(PRODUCTION_CONFIG, {"dns_zone": "dev.example.com"})


def test_an_invalid_captured_config_fails_loudly() -> None:
    """Better than silently creating an environment that differs from the capture."""
    with pytest.raises(InvalidContextError) as excinfo:
        merge_environment_config({"backup_ttl": "30d"})

    assert "captured" in str(excinfo.value)


def test_a_nested_field_is_replaced_wholesale_and_canonicalised() -> None:
    merged = merge_environment_config(
        {"dedicated_ingress": {"implementation": "traefik", "type": "ingress"}},
        {"dedicated_ingress": {"implementation": "nginx"}},
    )

    assert merged["dedicated_ingress"]["implementation"] == "nginx"
    # Canonical form fills the submodel's own defaults, not the captured values.
    assert merged["dedicated_ingress"]["type"] == "ingress"


def test_the_result_carries_no_none_values() -> None:
    """The merged dict is stored on ``Environment.config`` and re-validated there."""
    merged = merge_environment_config(
        {"db_size": "10Gi"}, {"fqdn_suffix": "dev.example.com"}
    )

    assert all(value is not None for value in merged.values())
