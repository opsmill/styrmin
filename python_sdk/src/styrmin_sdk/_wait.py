"""Shared polling constants for SDK ``--wait``-style helpers.

Centralises the timeout / poll-interval pair used by every SDK call that
blocks on a terminal state (``apply(wait=True)`` today, ``create(wait=True)``
when it lands). Keeping the constants in one module guarantees the same
ceiling across surfaces — so a test that expects a 300s budget for one
SDK call sees the same budget for every other.

The poll target is ``Deployment.status``, the canonical user-visible
state enum (``PENDING / DEPLOYING / RUNNING / FAILED / …``). This matches
the user contract for ``--wait`` ("block until the deployment is
RUNNING") and the existing E2E driver helper
``backend/tests/e2e/drivers/api_driver.py::wait_for_deployment_running``.
Polling the per-submission ``Task`` is too early (its ``SUCCESS``
transition deliberately doesn't flip ``Deployment.status`` — see
``services/tasks.py:78-80``); polling ``ApplicationInstance.status`` is
racy because other reconciliation paths (CRD reporter, drift correction)
can touch it.
"""

from __future__ import annotations

#: Maximum seconds to spend polling a deployment for its terminal state.
WAIT_TIMEOUT_SECONDS: float = 300.0

#: Sleep interval between successive ``get`` polls during ``--wait``.
WAIT_POLL_INTERVAL_SECONDS: float = 10.0

#: ``Deployment.status`` values (compared case-insensitively) that mean
#: reconciliation has settled successfully and the deployment is usable.
TERMINAL_SUCCESS_STATUSES: frozenset[str] = frozenset({"running"})

#: ``Deployment.status`` values (compared case-insensitively) that mean
#: reconciliation terminated unsuccessfully.
TERMINAL_FAILURE_STATUSES: frozenset[str] = frozenset({"failed"})


def is_terminal_success(status: str | None) -> bool:
    """Return True if ``status`` is a terminal "success" value."""
    return status is not None and status.lower() in TERMINAL_SUCCESS_STATUSES


def is_terminal_failure(status: str | None) -> bool:
    """Return True if ``status`` is a terminal "failure" value."""
    return status is not None and status.lower() in TERMINAL_FAILURE_STATUSES
