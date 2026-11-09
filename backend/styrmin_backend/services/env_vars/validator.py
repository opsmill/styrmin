"""Re-export of ``styrmin_sdk.driver_format.context.validation.env_vars.validator``.

The module moved to the SDK, which the server, the agent and styrmin-driver share
(ADR-0089). This path keeps the backend's imports working.
"""

from styrmin_sdk.driver_format.context.validation.env_vars.validator import (
    _ENV_VAR_NAME_RE,
    _RISKY_ENV_VAR_NAME_RE,
    PER_SCOPE_BYTE_CAP,
    PER_SCOPE_ENTRY_CAP,
    PER_VALUE_BYTE_CAP,
    _extract_name_value,
    _serialised_dict_bytes,
    _utf8_bytes,
    logger,
    validate_env_var_name,
    validate_env_var_value,
    validate_env_vars_dict,
    validate_env_vars_input_list,
)

__all__ = [
    "PER_SCOPE_BYTE_CAP",
    "PER_SCOPE_ENTRY_CAP",
    "PER_VALUE_BYTE_CAP",
    "logger",
    "validate_env_var_name",
    "validate_env_var_value",
    "validate_env_vars_dict",
    "validate_env_vars_input_list",
    "_ENV_VAR_NAME_RE",
    "_RISKY_ENV_VAR_NAME_RE",
    "_extract_name_value",
    "_serialised_dict_bytes",
    "_utf8_bytes",
]
