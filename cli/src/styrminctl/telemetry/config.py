"""Telemetry configuration: endpoint resolution and the latency budget.

Defines the default production endpoint, the ``STYRMIN_TELEMETRY_ENDPOINT``
override, and the single tunable latency-budget constant.

See ``specs/015-styrminctl-telemetry/data-model.md`` (Configuration inputs) and
``specs/015-styrminctl-telemetry/research.md`` (R6) for the rationale.
"""

from __future__ import annotations

import os
from typing import Final

#: Default production ingestion endpoint. Overridable via the
#: ``STYRMIN_TELEMETRY_ENDPOINT`` environment variable (tests / local sinks).
DEFAULT_TELEMETRY_ENDPOINT: Final[str] = "https://telemetry-endpoints.cloudflare-096.workers.dev/styrminctl"

#: Name of the environment variable that overrides the destination endpoint.
ENDPOINT_ENV_VAR: Final[str] = "STYRMIN_TELEMETRY_ENDPOINT"

#: Hard latency cap (milliseconds) for the best-effort dispatch. The telemetry
#: side-channel must never add more than this to a command's wall-clock time;
#: this is the single tunable knob (FR-003, FR-018).
TELEMETRY_BUDGET_MS: Final[int] = 200


def resolve_endpoint() -> str:
    """Return the effective telemetry endpoint URL.

    Resolves the ``STYRMIN_TELEMETRY_ENDPOINT`` override at call time so tests
    and local sinks can redirect dispatch without restarting the process; falls
    back to :data:`DEFAULT_TELEMETRY_ENDPOINT` when unset or blank.
    """
    override = os.environ.get(ENDPOINT_ENV_VAR)
    if override and override.strip():
        return override.strip()
    return DEFAULT_TELEMETRY_ENDPOINT
