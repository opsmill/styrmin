"""Validation tests for BaseConfigSection.external_dns_endpoints_type.

Pinned to the field's Pydantic Literal contract (FR-005, US2): the only accepted
values are "NodeExternalIP", "ClusterIP", and None/missing. Anything else must
raise a ValidationError at config-parse time, before any reconcile runs.
"""

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.config import ClusterConfig


def test_validation_rejects_invalid_endpoints_type() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ClusterConfig(external_dns_endpoints_type="PodIP")  # type: ignore[arg-type]

    payload = str(exc_info.value)
    assert "external_dns_endpoints_type" in payload
    assert "NodeExternalIP" in payload
    assert "ClusterIP" in payload


def test_validation_accepts_explicit_null() -> None:
    config = ClusterConfig(external_dns_endpoints_type=None)
    assert config.external_dns_endpoints_type is None
