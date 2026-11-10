"""Shared FQDN computation and DNS sanitization utilities.

Single source of truth for FQDN assembly, used by both context generation
(driver templates) and the GraphQL API layer (frontend).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from styrmin_backend.context.models.config import ResolvedConfig, ServiceConfigBlock

_DNS_MAX_LABEL_LENGTH = 63


def to_fqdn_label(value: str) -> str:
    """Sanitize a string into a valid DNS label (RFC 1035).

    1. Convert to lowercase
    2. Replace non-alphanumeric characters (except hyphens) with hyphens
    3. Collapse consecutive hyphens to a single hyphen
    4. Strip leading and trailing hyphens
    5. Truncate to 63 characters and strip any hyphen exposed by truncation
    """
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    return value[:_DNS_MAX_LABEL_LENGTH].rstrip("-")


def _combine_labels(prefix: str, suffix: str) -> str:
    """Join two already-sanitized labels with ``-``, fitting within the DNS limit.

    The suffix is preserved intact whenever possible (it carries the
    uniqueness or environment identity); the prefix is truncated as needed.
    Returns an empty string when no valid combined label can be produced.
    """
    if not prefix and not suffix:
        return ""
    if not prefix:
        return suffix[:_DNS_MAX_LABEL_LENGTH].rstrip("-")
    if not suffix:
        return prefix[:_DNS_MAX_LABEL_LENGTH].rstrip("-")

    if len(suffix) >= _DNS_MAX_LABEL_LENGTH:
        return suffix[:_DNS_MAX_LABEL_LENGTH].rstrip("-")

    available_for_prefix = _DNS_MAX_LABEL_LENGTH - 1 - len(suffix)
    if available_for_prefix <= 0:
        return suffix

    truncated_prefix = prefix[:available_for_prefix].rstrip("-")
    if not truncated_prefix:
        return suffix
    return f"{truncated_prefix}-{suffix}"


def compute_primary_fqdn(
    app_name: str,
    deployment_id: str | UUID,
    fqdn_suffix: str | None,
) -> str | None:
    """Compute the UUID-based primary FQDN for a deployment.

    Pattern: ``{sanitized-app-name}-{deployment-id}.{fqdn-suffix}``

    Returns ``None`` when *fqdn_suffix* is not configured or no valid
    left-hand label can be constructed.
    """
    if not fqdn_suffix:
        return None
    deployment_label = to_fqdn_label(str(deployment_id))
    app_label = to_fqdn_label(app_name)
    label = _combine_labels(app_label, deployment_label)
    if not label:
        return None
    return f"{label}.{fqdn_suffix}"


def compute_human_readable_fqdn(
    service_host: str,
    environment_name: str,
    fqdn_suffix: str | None,
) -> str | None:
    """Compute the environment-name-based human-readable FQDN.

    Pattern: ``{sanitized-host}-{sanitized-env}.{fqdn-suffix}``

    Returns ``None`` when *fqdn_suffix* is not configured or no valid
    left-hand label can be constructed.
    """
    if not fqdn_suffix:
        return None
    host_label = to_fqdn_label(service_host)
    env_label = to_fqdn_label(environment_name)
    label = _combine_labels(host_label, env_label)
    if not label:
        return None
    return f"{label}.{fqdn_suffix}"


@dataclass(frozen=True)
class ServiceAddress:
    """The effective ingress class, suffix and hosts of one service.

    ``overridden`` is ``True`` when the deployment stores a service ingress override
    with at least one field set for the service (#598).
    """

    ingress_class: str | None
    fqdn_suffix: str | None
    human_readable_fqdn: str | None
    primary_fqdn: str | None
    overridden: bool


def compute_service_address(
    config: ResolvedConfig,
    override: ServiceConfigBlock | None,
    *,
    service_host: str,
    environment_name: str,
    app_name: str,
    deployment_id: str | UUID,
) -> ServiceAddress:
    """Compute the effective address of a service, with or without an override.

    The override class and suffix replace the resolved ones for this service only, and a
    field left as ``None`` falls back to the resolved value. The primary FQDN always uses
    the resolved suffix: the application address stays with the resolved configuration.
    """
    overridden = override is not None and not override.is_empty
    ingress_class = config.ingress_class
    fqdn_suffix = config.fqdn_suffix
    if override is not None:
        ingress_class = override.ingress_class or ingress_class
        fqdn_suffix = override.fqdn_suffix or fqdn_suffix
    return ServiceAddress(
        ingress_class=ingress_class,
        fqdn_suffix=fqdn_suffix,
        human_readable_fqdn=compute_human_readable_fqdn(
            service_host, environment_name, fqdn_suffix
        ),
        primary_fqdn=compute_primary_fqdn(app_name, deployment_id, config.fqdn_suffix),
        overridden=overridden,
    )


_DEFAULT_PORTS = {"http": 80, "https": 443}


def compute_external_url(
    fqdn: str | None,
    scheme: str | None,
    port: int | None,
) -> str | None:
    """Build a user-facing URL from an FQDN, scheme, and port.

    Returns ``None`` when *fqdn* is ``None``. ``scheme`` defaults to
    ``"https"``. ``port`` is omitted from the URL when it matches the
    default for the scheme (80 for http, 443 for https).
    """
    if not fqdn:
        return None
    resolved_scheme = scheme or "https"
    if port is None or port == _DEFAULT_PORTS.get(resolved_scheme):
        return f"{resolved_scheme}://{fqdn}"
    return f"{resolved_scheme}://{fqdn}:{port}"
