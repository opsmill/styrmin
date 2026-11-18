"""``DeploymentStatusType`` reads the stored ``lastTransitionTime`` of each condition (#548)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from styrmin_backend.api.definitions.deployment_status.model import DeploymentStatusType
from styrmin_backend.db.models import DeploymentStatus


def _transition_time(value: Any) -> datetime | None:
    condition: dict[str, Any] = {"type": "Ready", "status": "True"}
    if value is not None:
        condition["lastTransitionTime"] = value
    row = DeploymentStatus(
        deployment_id=uuid4(),
        phase="Ready",
        conditions=[condition],
        last_polled_at=None,
    )
    return DeploymentStatusType.from_instance(row).conditions[0].last_transition_time


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("2026-10-22T10:00:05+00:00", datetime(2026, 10, 22, 10, 0, 5, tzinfo=UTC)),
        ("2026-10-22T12:00:05+02:00", datetime(2026, 10, 22, 10, 0, 5, tzinfo=UTC)),
        # A time without an offset is read as UTC.
        ("2026-10-22T10:00:05", datetime(2026, 10, 22, 10, 0, 5, tzinfo=UTC)),
        (None, None),
        ("", None),
        ("not a time", None),
        (12345, None),
    ],
)
def test_condition_transition_time(stored: Any, expected: datetime | None) -> None:
    assert _transition_time(stored) == expected
