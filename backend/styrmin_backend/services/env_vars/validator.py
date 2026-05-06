"""Validator stubs for deployment environment variables.

Real validation logic lands in T047. This module exists so that future
imports such as ``from styrmin_backend.services.env_vars.validator import ...``
resolve while the package skeleton is in place.
"""

# Placeholder pattern; the real regex (POSIX env-var name rules) is introduced
# alongside the validator implementation in T047.
_ENV_VAR_NAME_RE: object | None = None
