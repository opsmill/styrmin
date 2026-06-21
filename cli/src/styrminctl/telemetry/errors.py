"""Outcome and error-category classification.

``categorize_error(exc)`` maps an exception (or ``None`` for success) to an
``(outcome, error_category)`` pair, keyed on exception **type** and reusing the
existing typed-error hierarchy in ``python_sdk/src/styrmin_sdk/exceptions.py``
and ``cli/src/styrminctl/errors.py``. No new exception classes (FR-011,
Constitution §IV).

Classification is by type only — never by parsing human-readable messages
(FR-011). ``outcome`` is ``"success"`` when no exception propagated or a
``SystemExit`` carried code ``0``/``None``; otherwise ``"failure"``.
``error_category`` is ``None`` exactly when ``outcome == "success"``.

See ``specs/015-styrminctl-telemetry/research.md`` (R7) for the mapping table.
"""

from __future__ import annotations

from styrmin_sdk.exceptions import (
    DeploymentRestoringError,
    OperationFailedError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
    StyrminAuthenticationError,
    StyrminAuthorizationError,
    StyrminGraphQLError,
    StyrminTransportError,
)

from styrminctl.errors import AsymmetricEnvCredentialsError, TokenStoreError

#: Type-keyed ``error_category`` mapping (research.md R7). Order matters only
#: for subclass relationships; the listed types are otherwise disjoint, so an
#: ``isinstance`` walk against this ordered sequence is unambiguous.
_CATEGORY_BY_TYPE: tuple[tuple[type[BaseException], str], ...] = (
    (StyrminAuthenticationError, "auth"),
    (StyrminAuthorizationError, "auth"),
    (StyrminTransportError, "network"),
    (ResourceNotFoundError, "not_found"),
    (ResourceAlreadyExistsError, "validation"),
    (StyrminGraphQLError, "validation"),
    (AsymmetricEnvCredentialsError, "validation"),
    (OperationFailedError, "server"),
    (DeploymentRestoringError, "server"),
    (TokenStoreError, "server"),
)


def categorize_error(exc: BaseException | None) -> tuple[str, str | None]:
    """Return ``(outcome, error_category)`` for an invocation's final outcome.

    ``exc`` is the exception that propagated out of the command (including the
    auth boundary's ``SystemExit``), or ``None`` on a clean return.
    """
    if exc is None:
        return ("success", None)

    if isinstance(exc, SystemExit):
        # Cyclopts / argparse signal usage and arg errors via SystemExit. A code
        # of 0 or None is a clean exit (e.g. --help); anything else is a usage
        # failure. ``SystemExit.code`` may be an int, None, or a string message.
        code = exc.code
        if code in {0, None}:
            return ("success", None)
        return ("failure", "usage")

    for exc_type, category in _CATEGORY_BY_TYPE:
        if isinstance(exc, exc_type):
            return ("failure", category)

    return ("failure", "unknown")
