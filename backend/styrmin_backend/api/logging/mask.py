"""Masking of GraphQL variables for the request log.

The request log keeps the structure of the variables and the values that
cannot be secrets: the string value of a key that names an id (``id``,
``deploymentId``, ``userIds``, ...) or a name (``name``), booleans and
``null``. Every other value, string or number, becomes ``"***"``.

A mask by variable name misses secrets: a password sent in a variable named
``p``, the value of an env var, the ``secretAccessKey`` of a backup storage
location (#573). Keeping only the values that are known to be safe covers
the fields that the schema adds later too.

See ``specs/011-admin-user-group-mgmt/research.md`` §D13 and FR-029.
"""

from __future__ import annotations

import re
from typing import Any

# Sentinel string substituted in place of any masked value. Tests assert
# the literal ``"***"`` is present and the cleartext is not, so keep this
# in sync with those assertions if it ever changes.
MASK_PLACEHOLDER = "***"

# A key whose string value is kept: an id (``id``, ``deploymentId``, ``user_ids``)
# or a name, such as an env var name or a deployment name.
_KEPT_STRING_KEY = re.compile(r"^(?:ids?|.*(?:Ids?|_ids?)|name)$")
# An id of a credential, such as the ``accessKeyId`` of a backup storage location,
# which the API never returns: masked although its key ends in ``Id``.
_CREDENTIAL_KEY = re.compile(r"(?i)key|secret|token|password|passwd|credential")


def _mask(value: Any, key: str | None) -> Any:  # noqa: ANN401 - any JSON value
    if isinstance(value, dict):
        return {k: _mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(item, key) for item in value]
    if value is None or isinstance(value, bool):
        return value
    if (
        isinstance(value, str)
        and key is not None
        and _KEPT_STRING_KEY.match(key)
        and not _CREDENTIAL_KEY.search(key)
    ):
        return value
    return MASK_PLACEHOLDER


def mask_variables(variables: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``variables`` with every value that can be a secret masked.

    The original ``variables`` mapping is **not** mutated — callers
    typically log the masked copy while still passing the original to
    the executor. ``None`` (no variables) maps to ``{}`` so call sites do
    not need to special-case it.
    """
    if variables is None:
        return {}
    return {key: _mask(value, key) for key, value in variables.items()}
