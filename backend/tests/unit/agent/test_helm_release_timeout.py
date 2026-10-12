"""The HelmRelease timeout comes from ``STYRMIN_OPERATOR_HELM_RELEASE_TIMEOUT``."""

import pytest

from styrmin_backend import config
from styrmin_backend.agent.service.kubernetes.resources.builders.base import (
    build_minimal_helm_release,
    flux_duration,
)


@pytest.mark.parametrize(
    ("seconds", "duration"),
    [(300, "5m"), (120, "2m"), (90, "90s"), (1, "1s")],
)
def test_flux_duration(seconds: int, duration: str) -> None:
    assert flux_duration(seconds) == duration


@pytest.mark.parametrize(("seconds", "duration"), [(300, "5m"), (150, "150s")])
def test_helm_release_timeout_follows_the_setting(
    monkeypatch: pytest.MonkeyPatch, seconds: int, duration: str
) -> None:
    monkeypatch.setattr(config.SETTINGS.operator, "helm_release_timeout", seconds)

    spec = build_minimal_helm_release(
        release_reference="rel-1", chart_reference="chart-1"
    ).render()["spec"]

    assert spec["timeout"] == duration
