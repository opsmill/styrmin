"""Guard the image-tag defaults shared by the Styrmin Helm charts.

Both charts resolve their image with ``.Values.image.tag | default
.Chart.AppVersion``, so an untouched install pulls the image built for the
chart's own release instead of a floating ``:latest``. Two invariants keep
that true, and neither is enforced by ``helm lint``:

* ``image.tag`` must stay empty in the shipped defaults -- any literal value
  wins over the ``default`` fallback and pins every install to it;
* the agent subchart's ``appVersion`` must match the parent chart's, because
  a subchart's ``.Chart.AppVersion`` is its *own*, not the parent's. The
  release workflow bumps both (``.github/workflows/release.yml``); this test
  fails if a release, or a hand-edit, moves only one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

STYRMIN_CHART = REPO_ROOT / "helm" / "styrmin" / "Chart.yaml"
AGENT_CHART = REPO_ROOT / "helm" / "agent" / "Chart.yaml"

VALUES_FILES = (
    "helm/styrmin/values.yaml",
    "helm/agent/values.yaml",
)


def _load(path: Path) -> dict:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} not found"
    return yaml.safe_load(path.read_text()) or {}


@pytest.mark.parametrize("relative_path", VALUES_FILES)
def test_image_tag_defaults_to_app_version(relative_path: str) -> None:
    """The shipped defaults must leave ``image.tag`` empty."""
    document = _load(REPO_ROOT / relative_path)

    tag = document.get("image", {}).get("tag")
    assert tag == "", (
        f"{relative_path} sets image.tag={tag!r}. Leave it empty so the chart "
        "falls back to .Chart.AppVersion -- a hardcoded tag (notably 'latest') "
        "makes every install ignore the released image."
    )


def test_agent_app_version_matches_styrmin_chart() -> None:
    """The agent subchart's appVersion must track the parent chart's."""
    styrmin_app_version = _load(STYRMIN_CHART).get("appVersion")
    agent_app_version = _load(AGENT_CHART).get("appVersion")

    assert agent_app_version == styrmin_app_version, (
        f"helm/agent/Chart.yaml appVersion is {agent_app_version!r} but "
        f"helm/styrmin/Chart.yaml is {styrmin_app_version!r}. The agent chart's "
        "appVersion is its default image tag, so a drift silently deploys a "
        "mismatched agent image. See .github/workflows/release.yml."
    )
