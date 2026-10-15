"""Ingress class after ``helm template`` and ``kubectl kustomize`` (spec 023, FR-001 to FR-006, SC-003).

Renders the ``simple-app`` example chart, applies the ingress utility's patches as the HelmRelease
passes them to Flux, and checks ``spec.ingressClassName`` and the class annotation of every Ingress.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.primitives import _prune_none
from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    PostRenderers,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.ingress import (
    IngressUtility,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None or shutil.which("kubectl") is None,
    reason="helm and kubectl are required to render the simple-app chart and run kustomize",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SIMPLE_APP_DIR = _REPO_ROOT / "driver" / "examples" / "simple-app"
_SIMPLE_APP_CHART = _SIMPLE_APP_DIR / "src" / "helm"
_SIMPLE_APP_TEMPLATE = _SIMPLE_APP_DIR / "values.j2.yml"
_FQDN_SUFFIX = "apps.example.test"
_CLASS_ANNOTATION = "kubernetes.io/ingress.class"

# (spec.ingressClassName, kubernetes.io/ingress.class) of one Ingress; None means absent.
IngressClass = tuple[str | None, str | None]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _context(*, dedicated: bool, ingress_class: str | None) -> GlobalContext:
    """A ``simple-app`` context; the cluster config and the resolved config set the ingress mode and class."""
    dedicated_ingress = DedicatedIngressConfig() if dedicated else None
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(
                ingress_class=ingress_class,
                dedicated_ingress=dedicated_ingress,
                fqdn_suffix=_FQDN_SUFFIX,
            )
        ),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(
                ingress_class=ingress_class,
                dedicated_ingress=dedicated_ingress,
                fqdn_suffix=_FQDN_SUFFIX,
            ),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name="simple-app",
            version="1.2.3",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="simple-app", version="0.1.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        services={
            "simple-app": {
                "primary_fqdn": f"simple-app.{_FQDN_SUFFIX}",
                "human_readable_fqdn": f"simple-app-hr.{_FQDN_SUFFIX}",
            }
        },
    )


def _render_values(template: str, context: GlobalContext) -> dict[str, Any]:
    """Chart values from ``template`` through the production renderer, pruned of ``None`` as the operator does."""
    values = ApplicationHelmReleaseBuilder.render_value_template.fn(
        values_template=template, context=context
    )
    return _prune_none(values)


def _ingress_patches(context: GlobalContext) -> list[TargetPatch]:
    return IngressUtility().build_app_post_rendering_patches(
        context, context.instance.release_reference
    )


def _flux_patches(patches: list[TargetPatch]) -> list[dict[str, Any]]:
    """The patches as the HelmRelease's ``postRenderers[0].kustomize.patches`` passes them to Flux."""
    [post_renderer] = PostRenderers(target_patches=patches).render_value()
    return post_renderer["kustomize"]["patches"]


def _helm_template(values: dict[str, Any], workdir: Path) -> str:
    values_file = workdir / "values.yaml"
    values_file.write_text(yaml.safe_dump(values))
    result = subprocess.run(
        [
            "helm",
            "template",
            "styrmin",
            str(_SIMPLE_APP_CHART),
            "--namespace",
            "styrmin-ingress-class",
            "--values",
            str(values_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _kustomize(
    manifests: str, patches: list[TargetPatch], workdir: Path
) -> list[dict[str, Any]]:
    """Run ``kubectl kustomize`` on ``manifests`` with ``patches`` as Flux passes them."""
    (workdir / "base.yaml").write_text(manifests)
    kustomization = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": ["base.yaml"],
        "patches": _flux_patches(patches),
    }
    (workdir / "kustomization.yaml").write_text(yaml.safe_dump(kustomization))
    result = subprocess.run(
        ["kubectl", "kustomize", str(workdir)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _post_render(
    values: dict[str, Any], context: GlobalContext, workdir: Path
) -> list[dict[str, Any]]:
    """Every document after ``helm template`` and ``kubectl kustomize`` with the context's ingress patches."""
    return _kustomize(
        _helm_template(values, workdir), _ingress_patches(context), workdir
    )


def _ingresses(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == "Ingress"]


def _classes_by_ingress(docs: list[dict[str, Any]]) -> dict[str, IngressClass]:
    return {
        ingress["metadata"]["name"]: (
            ingress.get("spec", {}).get("ingressClassName"),
            (ingress["metadata"].get("annotations") or {}).get(_CLASS_ANNOTATION),
        )
        for ingress in _ingresses(docs)
    }


# ---------------------------------------------------------------------------
# User Story 1: the migrated template gets the class of its mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dedicated", "expected"),
    [(True, (None, "traefik")), (False, ("nginx", "nginx"))],
    ids=["dedicated", "shared"],
)
def test_migrated_simple_app_template_gets_the_class_of_its_mode(
    dedicated: bool, expected: IngressClass, tmp_path: Path
) -> None:
    """FR-004, SC-002: ``simple-app`` without its class line gives the Ingress class of its mode."""
    # A resolved class in dedicated mode too, so a class set in that mode shows up as nginx.
    context = _context(dedicated=dedicated, ingress_class="nginx")
    values = _render_values(_SIMPLE_APP_TEMPLATE.read_text(), context)
    assert "className" not in values["ingress"], values["ingress"]

    classes = _classes_by_ingress(_post_render(values, context, tmp_path))

    assert classes, "the simple-app chart rendered no Ingress"
    assert classes == dict.fromkeys(classes, expected)
