"""Write-time checks of per-service ingress overrides (#598, research D-008).

Runs on the raw config dict on ``deploy``, ``updateDeployment`` and ``updateDeploymentVersion``
(which ``apply`` calls, ADR-065), against the driver version the deployment is bound to after
the write, before any task, flow run or ingress dispatch.

Differs from the replica validator (ADR-070) on purpose. An override on a component that the
driver version no longer declares is kept as an orphan, and is harmless. An ingress override on
a service that Styrmin no longer builds an Ingress for would silently stop applying, so a driver
version change that would leave one is refused (FR-010). A request that clears the override, by
leaving it out of the config, is always accepted (SC-004).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from styrmin_backend.services.driver.models.resources.services import ServiceScope
from styrmin_backend.services.service_ingress.exceptions import (
    ServiceIngressNotBuiltError,
    ServiceIngressOverrideWouldBeDroppedError,
    UnknownServiceIngressOverrideError,
)


def has_service_ingress_overrides(config: dict[str, Any] | None) -> bool:
    """Whether any service block of ``config`` sets an ingress class or an FQDN suffix."""
    return next(_service_overrides(config), None) is not None


def _service_overrides(
    config: dict[str, Any] | None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(service, block)`` for every service block that sets at least one field.

    A block with both fields ``None`` is not an override: it is dropped when stored, so sending
    it is the same as clearing it. The fields that are ``None`` are left out of the yielded block.
    """
    services = (config or {}).get("services")
    if not isinstance(services, dict):
        return
    for name in sorted(services):
        block = services[name]
        if not isinstance(block, dict):
            continue
        set_fields: dict[str, Any] = {
            str(key): value for key, value in block.items() if value is not None
        }
        if set_fields:
            yield str(name), set_fields


def validate_service_ingress_overrides(
    config: dict[str, Any] | None,
    *,
    services: Mapping[str, ServiceScope],
    stored_config: dict[str, Any] | None,
    checked_against: str,
    current_version: str | None = None,
    target_version: str = "",
) -> None:
    """Reject ingress overrides that the driver version cannot apply.

    ``services`` maps each service the driver version declares to its scope. ``config`` is the
    config the deployment holds after the write: the submitted one, or the stored one when the
    request carries no config. ``current_version`` is the driver version the deployment is bound
    to now when the write changes the driver version, and ``None`` otherwise.

    Raises:
        ServiceIngressOverrideWouldBeDroppedError: The driver version changes, and an override
            that is stored and sent again targets a service that the target version removes or
            declares internal.
        UnknownServiceIngressOverrideError: An override that is added or changed targets a
            service the driver version does not declare.
        ServiceIngressNotBuiltError: An override that is added or changed targets a service
            that the driver version declares with a scope other than ``external``.
    """
    stored = dict(_service_overrides(stored_config))
    for name, block in _service_overrides(config):
        scope = services.get(name)
        if scope == ServiceScope.EXTERNAL:
            continue
        if current_version is not None and stored.get(name) == block:
            raise ServiceIngressOverrideWouldBeDroppedError(
                service_name=name,
                current_version=current_version,
                target_version=target_version,
                reason="removed" if scope is None else "internal",
            )
        if scope is None:
            raise UnknownServiceIngressOverrideError(
                service_name=name,
                known_services=list(services),
                checked_against=checked_against,
            )
        raise ServiceIngressNotBuiltError(
            service_name=name,
            scope=scope.value,
            checked_against=checked_against,
        )
