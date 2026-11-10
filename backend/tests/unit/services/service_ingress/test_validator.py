"""Unit tests for ``validate_service_ingress_overrides`` (#598, T049; FR-009, FR-010, SC-004).

An override that is added or changed must name a service the driver version declares with
``scope: external``: an undeclared service raises ``UNKNOWN_SERVICE_INGRESS_OVERRIDE`` and an
internal one raises ``SERVICE_INGRESS_NOT_BUILT``. When the driver version changes, a stored
override that the target version removes or makes internal raises
``SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED``, also when the config sends it again. Differs from
the replica validator on purpose: an orphaned override is never kept (research D-008). Clearing
an override in the same request is always accepted (SC-004).

Written before the validator (T051). Source: ``specs/033-service-ingress-override/spec.md`` and
``contracts/graphql-and-manifest.md`` (typed errors).
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.services.driver.models.resources.services import ServiceScope
from styrmin_backend.services.service_ingress.exceptions import (
    ServiceIngressNotBuiltError,
    ServiceIngressOverrideWouldBeDroppedError,
    UnknownServiceIngressOverrideError,
)
from styrmin_backend.services.service_ingress.validator import (
    has_service_ingress_overrides,
    validate_service_ingress_overrides,
)

CHECKED_AGAINST = "driver infrahub version 2.0.0 (application version 1.9.0)"
CURRENT_VERSION = "1.0.0"
TARGET_VERSION = "2.0.0"

# What the driver version declares: ``infrahub`` is internal, the others are external.
SERVICES = {
    "infrahub": ServiceScope.INTERNAL,
    "task-manager": ServiceScope.EXTERNAL,
    "api": ServiceScope.EXTERNAL,
}

OVERRIDE = {"ingress_class": "tailscale", "fqdn_suffix": "tailnet.example.ts.net"}


def _config(**blocks: dict[str, Any] | None) -> dict[str, Any]:
    """A config with a ``services`` map: the service name (underscores for hyphens) -> block."""
    return {
        "services": {name.replace("_", "-"): block for name, block in blocks.items()}
    }


def _validate(
    config: dict[str, Any] | None,
    *,
    stored: dict[str, Any] | None = None,
    services: dict[str, ServiceScope] | None = None,
    version_change: bool = False,
) -> None:
    """Run the validator; ``version_change`` passes the current driver version label."""
    validate_service_ingress_overrides(
        config,
        services=SERVICES if services is None else services,
        stored_config=stored,
        checked_against=CHECKED_AGAINST,
        current_version=CURRENT_VERSION if version_change else None,
        target_version=TARGET_VERSION,
    )


# ---------------------------------------------------------------------------
# Setting an override: the service must be declared and external (FR-009)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored",
    [None, {}, _config(ghost=OVERRIDE), _config(ghost={"ingress_class": "other"})],
    ids=["no-stored-config", "no-stored-override", "same-stored", "changed-stored"],
)
def test_override_on_an_unknown_service_is_rejected(
    stored: dict[str, Any] | None,
) -> None:
    with pytest.raises(UnknownServiceIngressOverrideError) as excinfo:
        _validate(_config(ghost=OVERRIDE), stored=stored)

    assert excinfo.value.error_code == "UNKNOWN_SERVICE_INGRESS_OVERRIDE"
    assert excinfo.value.error_metadata == {
        "service_name": "ghost",
        "known_services": ["api", "infrahub", "task-manager"],
        "checked_against": CHECKED_AGAINST,
    }
    assert "'ghost'" in str(excinfo.value)
    assert CHECKED_AGAINST in str(excinfo.value)


@pytest.mark.parametrize(
    "stored",
    [None, _config(infrahub=OVERRIDE)],
    ids=["added", "same-stored"],
)
def test_override_on_an_internal_service_is_rejected(
    stored: dict[str, Any] | None,
) -> None:
    with pytest.raises(ServiceIngressNotBuiltError) as excinfo:
        _validate(_config(infrahub=OVERRIDE), stored=stored)

    assert excinfo.value.error_code == "SERVICE_INGRESS_NOT_BUILT"
    assert excinfo.value.error_metadata == {
        "service_name": "infrahub",
        "scope": "internal",
        "checked_against": CHECKED_AGAINST,
    }
    message = str(excinfo.value)
    assert "'infrahub'" in message
    assert "does not build" in message
    assert "Ingress" in message


def test_override_on_an_external_service_is_accepted() -> None:
    _validate(_config(task_manager=OVERRIDE, api={"ingress_class": "traefik"}))


def test_a_one_field_override_is_accepted_on_an_external_service() -> None:
    _validate(_config(task_manager={"ingress_class": None, "fqdn_suffix": "a.example"}))


def test_the_offending_service_is_named_when_others_are_valid() -> None:
    with pytest.raises(ServiceIngressNotBuiltError) as excinfo:
        _validate(_config(api=OVERRIDE, infrahub=OVERRIDE, task_manager=OVERRIDE))

    assert excinfo.value.error_metadata["service_name"] == "infrahub"


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"services": None},
        {"services": {}},
        {"components": {"server": {"replicas": 2}}},
    ],
    ids=["no-config", "empty-config", "null-services", "no-blocks", "other-keys-only"],
)
def test_a_config_without_overrides_is_accepted(config: dict[str, Any] | None) -> None:
    _validate(config, stored=_config(infrahub=OVERRIDE, ghost=OVERRIDE))
    assert not has_service_ingress_overrides(config)


@pytest.mark.parametrize(
    "block",
    [{}, {"ingress_class": None, "fqdn_suffix": None}],
    ids=["empty-block", "both-null"],
)
def test_a_block_with_no_field_set_is_no_override(block: dict[str, Any]) -> None:
    """A block with both fields null is dropped when stored, so it names no override."""
    config = _config(infrahub=block, ghost=block)

    assert not has_service_ingress_overrides(config)
    _validate(config)


def test_has_service_ingress_overrides_sees_a_set_field() -> None:
    assert has_service_ingress_overrides(_config(api={"fqdn_suffix": "a.example"}))


# ---------------------------------------------------------------------------
# Clearing an override is always accepted (FR-010, SC-004)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version_change", [False, True], ids=["same-version", "new-version"]
)
@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"services": None},
        _config(),
        _config(task_manager=None),
        _config(task_manager={"ingress_class": None, "fqdn_suffix": None}),
    ],
    ids=[
        "no-config",
        "empty-config",
        "null",
        "list-without-it",
        "null-block",
        "both-null",
    ],
)
def test_clearing_a_stale_override_is_accepted(
    config: dict[str, Any] | None, version_change: bool
) -> None:
    """The stored override targets a service that the driver version no longer declares, and
    the request clears it (or sends no override), so nothing is dropped silently."""
    stored = _config(ghost=OVERRIDE, infrahub=OVERRIDE)

    _validate(config, stored=stored, version_change=version_change)


# ---------------------------------------------------------------------------
# A driver version change must not drop a stored override silently (FR-010)
# ---------------------------------------------------------------------------


def test_a_version_that_removes_the_service_is_refused() -> None:
    """The stored override is kept when the request carries it, so the change is refused."""
    stored = _config(ghost=OVERRIDE)

    with pytest.raises(ServiceIngressOverrideWouldBeDroppedError) as excinfo:
        _validate(stored, stored=stored, version_change=True)

    assert excinfo.value.error_code == "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED"
    assert excinfo.value.error_metadata == {
        "service_name": "ghost",
        "current_version": CURRENT_VERSION,
        "target_version": TARGET_VERSION,
        "reason": "removed",
    }
    message = str(excinfo.value)
    assert "'ghost'" in message
    assert CURRENT_VERSION in message
    assert TARGET_VERSION in message


def test_a_version_that_makes_the_service_internal_is_refused() -> None:
    stored = _config(task_manager=OVERRIDE)
    target_services = {**SERVICES, "task-manager": ServiceScope.INTERNAL}

    with pytest.raises(ServiceIngressOverrideWouldBeDroppedError) as excinfo:
        _validate(stored, stored=stored, services=target_services, version_change=True)

    assert excinfo.value.error_metadata == {
        "service_name": "task-manager",
        "current_version": CURRENT_VERSION,
        "target_version": TARGET_VERSION,
        "reason": "internal",
    }
    assert "'task-manager'" in str(excinfo.value)


def test_a_stored_override_without_a_config_write_is_refused() -> None:
    """``updateDeploymentVersion`` without ``input`` checks the stored config itself."""
    stored = _config(task_manager=OVERRIDE)
    target_services = {
        name: scope for name, scope in SERVICES.items() if name != "task-manager"
    }

    with pytest.raises(ServiceIngressOverrideWouldBeDroppedError) as excinfo:
        _validate(stored, stored=stored, services=target_services, version_change=True)

    assert excinfo.value.error_metadata["reason"] == "removed"


def test_a_stored_one_field_override_is_refused_too() -> None:
    stored = _config(ghost={"ingress_class": "tailscale", "fqdn_suffix": None})

    with pytest.raises(ServiceIngressOverrideWouldBeDroppedError):
        _validate(stored, stored=stored, version_change=True)


def test_a_version_that_keeps_the_service_external_is_allowed() -> None:
    stored = _config(task_manager=OVERRIDE, api={"ingress_class": "traefik"})

    _validate(stored, stored=stored, version_change=True)


def test_a_new_override_on_a_removed_service_is_not_reported_as_dropped() -> None:
    """The override is not stored yet, so nothing is dropped: the operator sets an override the
    target version cannot honour, which is the unknown-service error."""
    with pytest.raises(UnknownServiceIngressOverrideError):
        _validate(_config(ghost=OVERRIDE), stored=None, version_change=True)


def test_a_changed_override_on_an_internal_service_is_not_reported_as_dropped() -> None:
    """The stored override differs from the one sent, so the request sets a new one."""
    stored = _config(infrahub={"ingress_class": "old"})

    with pytest.raises(ServiceIngressNotBuiltError):
        _validate(_config(infrahub=OVERRIDE), stored=stored, version_change=True)


def test_the_other_overrides_do_not_hide_the_one_that_would_be_dropped() -> None:
    stored = _config(api=OVERRIDE, ghost=OVERRIDE, task_manager=OVERRIDE)

    with pytest.raises(ServiceIngressOverrideWouldBeDroppedError) as excinfo:
        _validate(stored, stored=stored, version_change=True)

    assert excinfo.value.error_metadata["service_name"] == "ghost"
