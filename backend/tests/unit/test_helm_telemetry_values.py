"""Telemetry settings of the Styrmin Helm chart and of the development and test installs.

Spec 020: FR-004, FR-011, FR-017, FR-020; research D11, D18.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

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


@pytest.fixture
def chart(tmp_path: Path) -> Path:
    if shutil.which("helm") is None:
        pytest.skip(
            "helm is not on PATH; this test renders the chart with `helm template`"
        )
    # The subcharts in helm/styrmin/charts/ are not committed, so render a copy without them.
    chart_yaml = yaml.safe_load((CHART_DIR / "Chart.yaml").read_text())
    chart_yaml.pop("dependencies", None)
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml, sort_keys=False))
    for relative in CHART_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CHART_DIR / relative, destination)
    return tmp_path


def _set_arguments(set_values: tuple[str, ...]) -> list[str]:
    """``--set`` for each value; a value that starts with ``string:`` uses ``--set-string``."""
    arguments: list[str] = []
    for value in set_values:
        if value.startswith("string:"):
            arguments += ["--set-string", value.removeprefix("string:")]
        else:
            arguments += ["--set", value]
    return arguments


def _render_configmap(
    chart: Path, *set_values: str
) -> subprocess.CompletedProcess[str]:
    command = ["helm", "template", "t", str(chart)]
    command += ["--show-only", "templates/configmap.yaml", *_set_arguments(set_values)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _configmap_data(chart: Path, *set_values: str) -> dict[str, object]:
    result = _render_configmap(chart, *set_values)
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)["data"]


def _install_notes(chart: Path, *set_values: str) -> str:
    # `helm template` skips NOTES.txt and Helm 3's `helm install --dry-run` needs a cluster,
    # so render the NOTES.txt text as a named template inside a ConfigMap.
    notes = (chart / "templates" / "NOTES.txt").read_text()
    (chart / "templates" / "notes-under-test.yaml").write_text(
        '{{ define "notes-under-test" }}' + notes + "{{ end }}\n"
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: notes-under-test\n"
        'data:\n  notes: {{ include "notes-under-test" . | toJson }}\n'
    )
    command = ["helm", "template", "styrmin", str(chart), "--namespace", "styrmin"]
    command += ["--show-only", "templates/notes-under-test.yaml"]
    command += _set_arguments(set_values)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)["data"]["notes"]


def test_install_notes_say_telemetry_is_on_and_how_to_view_and_turn_it_off(
    chart: Path,
) -> None:
    notes = _install_notes(chart)
    version = yaml.safe_load((CHART_DIR / "Chart.yaml").read_text())["version"]

    assert (
        "Telemetry is on: Styrmin sends one anonymous report a day to OpsMill.\n"
        "\n"
        "To view the report, run:\n"
        "  kubectl exec --namespace styrmin deploy/styrmin-server -c styrmin-server"
        " -- styrmin telemetry show\n"
        "\n"
        "To turn telemetry off, run:\n"
        f"  helm upgrade styrmin <chart> --version {version} --namespace styrmin"
        " --reuse-values --set styrmin.telemetry.enabled=false\n"
    ) in notes
    assert "Telemetry is off" not in notes


def test_install_notes_name_the_endpoint_value(chart: Path) -> None:
    notes = _install_notes(chart, "styrmin.telemetry.endpoint=http://sink/report")

    assert (
        "Telemetry is on: Styrmin sends one anonymous report a day to http://sink/report."
        in notes
    )


def test_install_notes_say_telemetry_is_off(chart: Path) -> None:
    notes = _install_notes(chart, "styrmin.telemetry.enabled=false")

    assert (
        "Telemetry is off (styrmin.telemetry.enabled=false). Styrmin sends no reports."
        in notes
    )
    assert "Telemetry is on" not in notes
    assert "styrmin telemetry show" not in notes


# A release installed from a chart without styrmin.telemetry, upgraded with --reuse-values.
NO_TELEMETRY_MAP = "styrmin.telemetry=null"


def test_install_notes_render_without_the_telemetry_map(chart: Path) -> None:
    notes = _install_notes(chart, NO_TELEMETRY_MAP)

    assert (
        "Telemetry is on: Styrmin sends one anonymous report a day to OpsMill." in notes
    )


def test_configmap_renders_without_the_telemetry_map(chart: Path) -> None:
    data = _configmap_data(chart, NO_TELEMETRY_MAP)

    assert data["STYRMIN_TELEMETRY_ENABLED"] == "true"
    assert "STYRMIN_TELEMETRY_ENDPOINT" not in data


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_set_string_false_values_agree_in_the_notes_and_the_configmap(
    chart: Path, value: str
) -> None:
    set_value = f"string:styrmin.telemetry.enabled={value}"

    notes = _install_notes(chart, set_value)
    data = _configmap_data(chart, set_value)

    assert "Telemetry is off (styrmin.telemetry.enabled=false)." in notes
    assert data["STYRMIN_TELEMETRY_ENABLED"] == "false"


def test_unknown_enabled_value_fails_the_render(chart: Path) -> None:
    result = _render_configmap(chart, "string:styrmin.telemetry.enabled=disabled")

    assert result.returncode != 0
    assert "styrmin.telemetry.enabled must be true or false" in result.stderr


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


def test_docker_compose_turns_telemetry_off_in_the_server_and_the_task_worker() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())

    for service in ("server", "task-worker"):
        environment = compose["services"][service]["environment"]
        assert environment["STYRMIN_TELEMETRY_ENABLED"] == "false", service


def test_local_demo_values_turn_telemetry_off() -> None:
    values = yaml.safe_load(
        (REPO_ROOT / "dev" / "local" / "demo-values.yaml").read_text()
    )

    assert values["styrmin"]["telemetry"]["enabled"] is False


def test_e2e_values_send_reports_to_an_in_cluster_sink() -> None:
    values_file = (
        REPO_ROOT / "backend" / "tests" / "e2e" / "fixtures" / "styrmin-values.yaml"
    )
    endpoint = urlsplit(
        yaml.safe_load(values_file.read_text())["styrmin"]["telemetry"]["endpoint"]
    )

    assert endpoint.scheme == "http"
    assert (endpoint.hostname or "").endswith(".svc.cluster.local"), endpoint.geturl()
