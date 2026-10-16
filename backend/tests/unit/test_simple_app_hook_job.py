"""The simple-app test chart's pre-upgrade Helm hooks, which only the ``hook-job`` E2E driver turns on (#435).

``preUpgradeHookJob.enabled`` renders a hook Job that carries the server component's identifier label
in ``metadata.labels`` (so Styrmin's scheduling patches reach it) but not in its pod template, and a
hook ConfigMap without labels (so the render checks that Styrmin's labels reach such a resource).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = REPO_ROOT / "driver" / "examples" / "simple-app" / "src" / "helm"
HOOK_ANNOTATION = "helm.sh/hook"


def _render(*set_values: str) -> list[dict[str, Any]]:
    if shutil.which("helm") is None:
        pytest.skip(
            "helm is not on PATH; this test renders the chart with `helm template`"
        )
    command = ["helm", "template", "t", str(CHART_DIR)]
    for value in set_values:
        command += ["--set", value]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _hooks(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    hooks = [
        doc
        for doc in documents
        if HOOK_ANNOTATION in (doc["metadata"].get("annotations") or {})
    ]
    by_kind = {doc["kind"]: doc for doc in hooks}
    assert len(by_kind) == len(hooks), [doc["kind"] for doc in hooks]
    return by_kind


def test_no_hook_by_default() -> None:
    assert _hooks(_render()) == {}


def test_enabled_renders_the_hook_job_and_the_unlabelled_hook_config_map() -> None:
    hooks = _hooks(_render("preUpgradeHookJob.enabled=true"))

    assert set(hooks) == {"Job", "ConfigMap"}

    job = hooks["Job"]
    assert job["apiVersion"] == "batch/v1"
    assert job["metadata"]["name"] == "t-simple-app-pre-upgrade-hook"
    assert job["metadata"]["annotations"] == {
        "helm.sh/hook": "pre-upgrade",
        "helm.sh/hook-weight": "0",
        "helm.sh/hook-delete-policy": "before-hook-creation",
    }
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == "simple-app"
    assert (
        job["metadata"]["labels"]["app.kubernetes.io/component"] == "pre-upgrade-hook"
    )
    assert job["spec"]["backoffLimit"] == 0
    assert "ttlSecondsAfterFinished" not in job["spec"]
    pod_template = job["spec"]["template"]
    assert pod_template["metadata"]["labels"] == {
        "app.kubernetes.io/component": "pre-upgrade-hook",
        "app.kubernetes.io/instance": "t",
    }
    pod = pod_template["spec"]
    assert pod["restartPolicy"] == "Never"
    [container] = pod["containers"]
    assert container["name"] == "hook"
    assert container["image"] == "simple-app:0.1.0"
    assert container["command"] == ["python", "-c", "print('pre-upgrade hook')"]
    assert container["securityContext"]["runAsNonRoot"] is True
    assert container["resources"] == {"requests": {"cpu": "10m", "memory": "32Mi"}}

    config_map = hooks["ConfigMap"]
    assert config_map["metadata"]["name"] == "t-simple-app-pre-upgrade-hook"
    assert config_map["metadata"]["annotations"] == {
        "helm.sh/hook": "pre-upgrade",
        "helm.sh/hook-weight": "-1",
        "helm.sh/hook-delete-policy": "before-hook-creation",
    }
    assert "labels" not in config_map["metadata"]
    assert config_map["data"] == {"hook": "pre-upgrade"}
