"""The agent chart applies its CRDs in a hook, and the test fixtures match the chart (#432, #433).

Helm never updates ``crds/``, so ``templates/crd-upgrade.yaml`` runs ``styrmin agent apply-crds``
on the chart's CRD files before every install and upgrade. The integration fixtures install the
same FluxCD CRDs and controllers, with the same arguments, as the chart. The chart runs
helm-controller with Helm v4 defaults, without the ``UseHelm3Defaults`` feature gate (#435).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = REPO_ROOT / "helm" / "agent"
FIXTURES_DIR = REPO_ROOT / "backend" / "tests" / "integration" / "fixtures"
HOOK = "pre-install,pre-upgrade"


def _render(*set_values: str) -> list[dict[str, Any]]:
    if shutil.which("helm") is None:
        pytest.skip(
            "helm is not on PATH; this test renders the chart with `helm template`"
        )
    command = ["helm", "template", "t", str(CHART_DIR), "--namespace", "styrmin"]
    for value in set_values:
        command += ["--set", value]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _hook_documents(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        doc["kind"]: doc
        for doc in documents
        if doc["metadata"].get("name") == "t-styrmin-agent-crd-upgrade"
    }


def test_hook_applies_every_crd_of_the_chart() -> None:
    hook = _hook_documents(_render())

    assert set(hook) == {
        "ServiceAccount",
        "ClusterRole",
        "ClusterRoleBinding",
        "ConfigMap",
        "Job",
    }
    for document in hook.values():
        assert document["metadata"]["annotations"]["helm.sh/hook"] == HOOK
    crd_files = sorted(CHART_DIR.glob("crds/*.yaml"))
    assert hook["ConfigMap"]["data"] == {
        path.name: path.read_text().rstrip("\n") for path in crd_files
    }
    pod = hook["Job"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["command"] == ["styrmin", "agent", "apply-crds", "/crds"]
    assert pod["serviceAccountName"] == "t-styrmin-agent-crd-upgrade"
    assert pod["volumes"] == [
        {"name": "crds", "configMap": {"name": "t-styrmin-agent-crd-upgrade"}}
    ]
    assert hook["ClusterRoleBinding"]["subjects"][0]["namespace"] == "styrmin"


def test_hook_is_left_out_when_disabled() -> None:
    assert _hook_documents(_render("crdUpgrade.enabled=false")) == {}


def test_operator_can_list_events() -> None:
    """The operator reads FluxCD's failure events of a HelmRelease that FluxCD reports in sync."""
    roles = {
        doc["metadata"]["name"]: doc
        for doc in _render()
        if doc["kind"] == "ClusterRole"
    }
    rules = roles["t-styrmin-agent-manager-role"]["rules"]
    assert any(
        "events" in rule["resources"] and "list" in rule["verbs"] for rule in rules
    )


@pytest.mark.parametrize(
    "path",
    sorted((FIXTURES_DIR / "crds").glob("*.yaml")),
    ids=lambda path: path.name,
)
def test_fixture_crds_match_the_chart(path: Path) -> None:
    assert path.read_text() == (CHART_DIR / "crds" / path.name).read_text()


def _controller_container(path: Path) -> dict[str, Any]:
    # The chart's template lines do not change the container block.
    text = "\n".join(line for line in path.read_text().splitlines() if "{{" not in line)
    return yaml.safe_load(text)["spec"]["template"]["spec"]["containers"][0]


@pytest.mark.parametrize("controller", ["helm-controller", "source-controller"])
def test_fixture_controllers_run_the_chart_images(controller: str) -> None:
    chart = _controller_container(
        CHART_DIR / "templates" / controller / "deployment.yaml"
    )
    fixture = _controller_container(
        FIXTURES_DIR / "templates" / controller / "deployment.yaml"
    )
    assert (fixture["image"], fixture["args"]) == (chart["image"], chart["args"])


def test_helm_controller_runs_with_helm_v4_defaults() -> None:
    template = CHART_DIR / "templates" / "helm-controller" / "deployment.yaml"
    args = _controller_container(template)["args"]

    assert args
    assert not [arg for arg in args if "UseHelm3Defaults" in arg]
    assert not [arg for arg in args if arg.startswith("--feature-gates")]
    # Also catch a gate added through a templated line, which the parse above drops.
    chart_text = "\n".join(
        path.read_text()
        for path in [
            template,
            CHART_DIR / "values.yaml",
            REPO_ROOT / "helm" / "styrmin" / "values.yaml",
        ]
    )
    assert "UseHelm3Defaults" not in chart_text
    assert "feature-gates" not in chart_text
