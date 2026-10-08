"""Telemetry values of the Styrmin Helm chart (spec 020, FR-004, FR-020, research D11)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = REPO_ROOT / "helm" / "styrmin"
CHART_FILES = (
    "values.yaml",
    "templates/_helpers.tpl",
    "templates/configmap.yaml",
    "templates/NOTES.txt",
)

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="helm is not on PATH; this test renders the chart with `helm template`",
)


@pytest.fixture
def chart(tmp_path: Path) -> Path:
    # The subcharts in helm/styrmin/charts/ are not committed, so render a copy without them.
    chart_yaml = yaml.safe_load((CHART_DIR / "Chart.yaml").read_text())
    chart_yaml.pop("dependencies", None)
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml, sort_keys=False))
    for relative in CHART_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CHART_DIR / relative, destination)
    return tmp_path


def _configmap_data(chart: Path, *set_values: str) -> dict[str, object]:
    command = ["helm", "template", "t", str(chart)]
    command += ["--show-only", "templates/configmap.yaml"]
    for value in set_values:
        command += ["--set", value]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)["data"]


def test_default_values_turn_telemetry_on_without_an_endpoint(chart: Path) -> None:
    data = _configmap_data(chart)

    assert data["STYRMIN_TELEMETRY_ENABLED"] == "true"
    assert "STYRMIN_TELEMETRY_ENDPOINT" not in data


def test_enabled_false_renders_false(chart: Path) -> None:
    data = _configmap_data(chart, "styrmin.telemetry.enabled=false")

    assert data["STYRMIN_TELEMETRY_ENABLED"] == "false"


def test_endpoint_value_renders_the_endpoint(chart: Path) -> None:
    data = _configmap_data(chart, "styrmin.telemetry.endpoint=http://sink/report")

    assert data["STYRMIN_TELEMETRY_ENDPOINT"] == "http://sink/report"
    assert data["STYRMIN_TELEMETRY_ENABLED"] == "true"
