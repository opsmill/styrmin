"""Shared FQDN computation and DNS sanitization utilities.

Single source of truth for FQDN assembly, used by both context generation
(driver templates) and the GraphQL API layer (frontend).
"""

from __future__ import annotations

import re
from uuid import UUID


def to_fqdn_label(value: str) -> str:
    """Sanitize a string into a valid DNS label (RFC 1035).

    1. Convert to lowercase
    2. Replace non-alphanumeric characters (except hyphens) with hyphens
    3. Collapse consecutive hyphens to a single hyphen
    4. Strip leading and trailing hyphens
    5. Truncate to 63 characters
    """
    value = value.lower()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    return value[:63]


def compute_primary_fqdn(
    app_name: str,
    deployment_id: str | UUID,
    fqdn_suffix: str | None,
) -> str | None:
    """Compute the UUID-based primary FQDN for a deployment.

    Pattern: ``{sanitized-app-name}-{deployment-id}.{fqdn-suffix}``

    Returns ``None`` when *fqdn_suffix* is not configured.
    """
    if not fqdn_suffix:
        return None
    label = to_fqdn_label(app_name)
    return f"{label}-{deployment_id}.{fqdn_suffix}"


def compute_human_readable_fqdn(
    service_host: str,
    environment_name: str,
    fqdn_suffix: str | None,
) -> str | None:
    """Compute the environment-name-based human-readable FQDN.

    Pattern: ``{sanitized-host}-{sanitized-env}.{fqdn-suffix}``

    Returns ``None`` when *fqdn_suffix* is not configured.
    """
    if not fqdn_suffix:
        return None
    host_label = to_fqdn_label(service_host)
    env_label = to_fqdn_label(environment_name)
    return f"{host_label}-{env_label}.{fqdn_suffix}"
