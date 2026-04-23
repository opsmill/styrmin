"""Driver-neutral error hierarchy for ScenarioDriver implementations.

Drivers normalise underlying exceptions (SDK StyrminError, Playwright
TimeoutError, UI-level validation errors) into this single hierarchy so
scenario assertions are identical across entrypoints.
"""

from __future__ import annotations


class ScenarioActionError(Exception):
    """Raised by a driver when an action fails at the entrypoint level."""


class ResourceNotFound(ScenarioActionError):
    """Raised when a lookup returns nothing (e.g. get_backup after delete)."""
