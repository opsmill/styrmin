"""Password-masking helpers for GraphQL request logging.

The masking is a name-based allow-list: any variable whose key matches a
name in :data:`MASKED_VARIABLE_NAMES` has its value replaced with
``"***"`` in the deep-copied result. Adding a new sensitive field is a
one-line change here and triggers code review by virtue of being a
diff against this set.

See ``specs/011-admin-user-group-mgmt/research.md`` §D13 and FR-029.
"""

from __future__ import annotations

import copy
from typing import Any

MASKED_VARIABLE_NAMES: frozenset[str] = frozenset(
    {"password", "newPassword", "currentPassword"}
)

# Sentinel string substituted in place of any masked value. Tests assert
# the literal ``"***"`` is present and the cleartext is not, so keep this
# in sync with those assertions if it ever changes.
MASK_PLACEHOLDER = "***"


def _mask_in_place(payload: Any) -> None:
    if isinstance(payload, dict):
        for key in list(payload):
            if key in MASKED_VARIABLE_NAMES:
                payload[key] = MASK_PLACEHOLDER
            else:
                _mask_in_place(payload[key])
    elif isinstance(payload, list):
        for item in payload:
            _mask_in_place(item)


def mask_variables(variables: dict[str, Any] | None) -> dict[str, Any]:
    """Return a deep-copied ``variables`` dict with masked field values redacted.

    The original ``variables`` mapping is **not** mutated — callers
    typically log the masked copy while still passing the original to
    the executor. ``None`` (no variables) maps to ``{}`` so call sites do
    not need to special-case it.
    """
    if variables is None:
        return {}
    masked: dict[str, Any] = copy.deepcopy(variables)
    _mask_in_place(masked)
    return masked
