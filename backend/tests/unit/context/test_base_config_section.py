"""Validation tests for the shared ``BaseConfigSection`` fields.

Two field contracts are pinned here, both enforced by Pydantic at
config-parse time — i.e. before any reconcile runs and before anything is
persisted:

* ``external_dns_endpoints_type`` (FR-005, US2 of 001-cluster-env-capabilities):
  a Literal accepting only ``"NodeExternalIP"``, ``"ClusterIP"``, or None.
* ``backup_ttl`` (FR-004, US3 of 016-backup-retention-ttl): a strictly
  positive Go duration in ``h``/``m``/``s`` units. Because the field lives on
  ``BaseConfigSection``, the same rule governs all three concrete config
  models — and therefore all five input surfaces (cluster create, environment
  create/update, deploy, deployment update) that funnel through
  ``validate_*_config``.
"""

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
)
from styrmin_backend.services.backup.ttl import (
    MAX_BACKUP_TTL_HOURS,
    validate_backup_ttl,
)

# Every concrete config model that inherits ``backup_ttl`` from
# ``BaseConfigSection``. Parametrising over all three is what proves the rule
# is shared rather than bolted onto one surface (FR-004: "at every input
# surface").
CONFIG_MODELS = (ClusterConfig, EnvironmentConfig, DeploymentConfig)

# Valid retention durations: whole hours (the common case), plus the minute /
# second units, a compound, and a decimal — all legal Go durations.
VALID_BACKUP_TTLS = (
    "720h",
    "2160h",
    "8760h",
    "1h",
    "90m",
    "3600s",
    "1h30m",
    "1.5h",
)

# Rejected values, one per failure mode:
#   "30d"     — day unit; Go has none, so Velero would reject it at apply time
#   "0h"      — syntactically fine but expresses no retention
#   "-24h"    — negative
#   "720"     — bare integer, ambiguous unit
#   ""        — empty
#   "0h0m0s"  — all-zero compound (the multi-component form of "0h")
#   "720h\n"  — trailing newline; ``$`` matches before it, so a ``match``-based
#               check would accept this and hand Velero an unparseable ttl
#   "٧٢٠h"    — Arabic-Indic digits; ``\d`` is Unicode-aware and would accept
#               them even though Go's ParseDuration only reads ASCII digits
#   " 720h"   — leading whitespace
INVALID_BACKUP_TTLS = (
    "30d",
    "0h",
    "-24h",
    "720",
    "",
    "0h0m0s",
    "720h\n",
    "٧٢٠h",
    " 720h",
)

# Durations whose syntax is fine but whose magnitude overflows Go's int64-
# nanosecond duration, so ``time.ParseDuration`` (and therefore Velero's
# ``metav1.Duration`` unmarshal of ``spec.ttl``) cannot decode them.
TOO_LARGE_BACKUP_TTLS = (
    f"{MAX_BACKUP_TTL_HOURS + 1}h",
    "8760000h",
    f"{MAX_BACKUP_TTL_HOURS}h1s",
)


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


# ---------------------------------------------------------------------------
# 016 / T026 — backup_ttl validation (FR-004, US3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", VALID_BACKUP_TTLS)
def test_validate_backup_ttl_accepts_positive_go_duration(value: str) -> None:
    """The validator returns valid values unchanged — no normalisation.

    Velero must receive exactly what the operator wrote, so the accepted
    value is passed through verbatim.
    """
    assert validate_backup_ttl(value) == value


@pytest.mark.parametrize("value", INVALID_BACKUP_TTLS)
def test_validate_backup_ttl_rejects_invalid_value(value: str) -> None:
    """Rejection message names the field and hints the ``720h`` syntax.

    FR-004 makes the message contract part of the requirement: the error has
    to stay actionable after the config validators wrap it into an
    ``Invalid*ContextError``, which means the hint must live in the message
    itself rather than in the exception type.
    """
    with pytest.raises(ValueError) as exc_info:
        validate_backup_ttl(value)

    message = str(exc_info.value)
    assert "backup_ttl" in message
    assert "720h" in message


@pytest.mark.parametrize("model", CONFIG_MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("value", VALID_BACKUP_TTLS)
def test_config_models_accept_valid_backup_ttl(model: type, value: str) -> None:
    """Cluster, environment, and deployment scopes accept the same values."""
    config = model(backup_ttl=value)
    assert config.backup_ttl == value


@pytest.mark.parametrize("model", CONFIG_MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("value", INVALID_BACKUP_TTLS)
def test_config_models_reject_invalid_backup_ttl(model: type, value: str) -> None:
    """Every scope rejects malformed retention, with the hint intact.

    This is the boundary that all five GraphQL input surfaces cross via
    ``validate_cluster_config`` / ``validate_environment_config`` /
    ``validate_deployment_config``, so a rejection here means nothing
    malformed is ever persisted (SC-003).
    """
    with pytest.raises(ValidationError) as exc_info:
        model(backup_ttl=value)

    payload = str(exc_info.value)
    assert "backup_ttl" in payload
    assert "720h" in payload


@pytest.mark.parametrize("model", CONFIG_MODELS, ids=lambda m: m.__name__)
def test_config_models_accept_unset_backup_ttl(model: type) -> None:
    """``None`` means "no policy at this scope" and skips validation entirely."""
    assert model().backup_ttl is None
    assert model(backup_ttl=None).backup_ttl is None


# ---------------------------------------------------------------------------
# 016 fix F5 — magnitudes Go's duration parser cannot represent
# ---------------------------------------------------------------------------


def test_validate_backup_ttl_accepts_the_largest_representable_duration() -> None:
    """The ceiling itself is accepted — the bound is inclusive.

    ``MAX_BACKUP_TTL_HOURS`` is Go's int64-nanosecond limit rounded *down* to
    whole hours, so the boundary value is safely inside what
    ``time.ParseDuration`` decodes and must not be rejected.
    """
    value = f"{MAX_BACKUP_TTL_HOURS}h"
    assert validate_backup_ttl(value) == value


@pytest.mark.parametrize("value", TOO_LARGE_BACKUP_TTLS)
def test_validate_backup_ttl_rejects_durations_go_cannot_represent(
    value: str,
) -> None:
    """Overflowing durations are refused at submission, not by Velero later.

    FR-004 / SC-003: a value Velero cannot decode must be rejected when it is
    submitted. Without the ceiling these match the syntax, persist, and only
    fail asynchronously when Velero unmarshals ``spec.ttl``.
    """
    with pytest.raises(ValueError) as exc_info:
        validate_backup_ttl(value)

    message = str(exc_info.value)
    assert "backup_ttl" in message
    assert str(MAX_BACKUP_TTL_HOURS) in message


@pytest.mark.parametrize("model", CONFIG_MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("value", TOO_LARGE_BACKUP_TTLS)
def test_config_models_reject_backup_ttl_go_cannot_represent(
    model: type, value: str
) -> None:
    """Every scope enforces the ceiling, so nothing overflowing is persisted."""
    with pytest.raises(ValidationError) as exc_info:
        model(backup_ttl=value)

    assert "backup_ttl" in str(exc_info.value)
