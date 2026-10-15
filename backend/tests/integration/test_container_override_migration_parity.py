"""Stored ``command``/``args`` give the same container after the move to a migrated driver (022 T022).

SC-005 (research D-011): renders one stored config twice, with the pre-migration
``values.j2.yml`` in ``fixtures/legacy_drivers/`` plus a copy of the retired filters, and with
the migrated driver template plus the post-render patches. ``simple-app`` compares the rendered
container after ``helm template`` and ``kubectl kustomize``. The infrahub charts are not in the
repository, so their test compares the list the old template sent to the chart with the list in
the merge patch, which spec assumption A-002 makes equivalent.
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
    ContainerMergePatch,
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
    SilentUndefined,
    get_jinja_environment,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ComponentContext,
    ComponentsContext,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
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
from styrmin_backend.services.component_container.patch_builder import (
    build_component_container_patches,
)
from styrmin_backend.services.context import _populate_component_container_overrides
from styrmin_backend.services.driver.deserializers import DriverSpecDeserializer

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLES_DIR = _REPO_ROOT / "driver" / "examples"
_LEGACY_DIR = Path(__file__).resolve().parent / "fixtures" / "legacy_drivers"
_SIMPLE_APP_CHART = _EXAMPLES_DIR / "simple-app" / "src" / "helm"


# ---------------------------------------------------------------------------
# Copy of the retired filters, as they were before 022 T024 replaced them.
# ---------------------------------------------------------------------------


def _legacy_resolved_container_override(components: object, name: str) -> dict | None:
    if not isinstance(components, dict):
        return None
    component = components.get(name)
    if not isinstance(component, dict):
        return None
    override = component.get("container_override")
    if not isinstance(override, dict):
        return None
    return override


def _legacy_component_command(components: object, name: str) -> list[str]:
    override = _legacy_resolved_container_override(components, name)
    if override is None:
        return []
    command = override.get("command")
    if not isinstance(command, list):
        return []
    return command


def _legacy_component_args(components: object, name: str) -> list[str]:
    override = _legacy_resolved_container_override(components, name)
    if override is None:
        return []
    args = override.get("args")
    if not isinstance(args, list):
        return []
    return args


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _context(driver: str, stored: dict[str, dict[str, list[str]]]) -> GlobalContext:
    """A context built from the migrated driver's components and the stored ``components`` config."""
    spec = DriverSpecDeserializer().deserialize(
        data=yaml.safe_load((_EXAMPLES_DIR / driver / "driver.styrmin.yml").read_text())
    )
    assert spec.spec.components is not None
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    context = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name=driver,
            version="1.2.3",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name=driver, version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        parameters={
            "replicas_server": 1,
            "replicas_task_worker": 1,
            "database_storage_size": 10,
            "enable_analytics": False,
        },
        services={
            name: {
                "primary_fqdn": f"{name}.example.test",
                "human_readable_fqdn": f"{name}-hr.example.test",
            }
            for name in ("simple-app", "infrahub", "task-manager")
        },
        components=ComponentsContext(
            root={
                name: ComponentContext.model_validate(
                    {"name": name, "enabled": True, "config": config}
                )
                for name, config in spec.spec.components.model_dump().items()
            }
        ),
    )
    _populate_component_container_overrides(
        context=context, deployment_config={"components": stored}
    )
    return context


def _render_legacy(driver: str, context: GlobalContext) -> dict[str, Any]:
    """Values the pre-migration template sent to the chart.

    ``None`` is pruned as the operator does before applying the HelmRelease (ADR-045 §5),
    so a ``null`` marker reads as "no value", which lets the chart default apply.
    """
    environment = get_jinja_environment(undefined=SilentUndefined)
    environment.filters["component_command"] = _legacy_component_command
    environment.filters["component_args"] = _legacy_component_args
    template = (_LEGACY_DIR / driver / "values.j2.yml").read_text()
    rendered = environment.from_string(template).render(
        context.model_dump(exclude_none=True)
    )
    return _prune_none(yaml.safe_load(rendered))


def _render_migrated(driver: str, context: GlobalContext) -> dict[str, Any]:
    """Values the migrated template sends, through the production Jinja environment."""
    template = (_EXAMPLES_DIR / driver / "values.j2.yml").read_text()
    values = ApplicationHelmReleaseBuilder.render_value_template.fn(
        values_template=template, context=context
    )
    return _prune_none(values)


def _value_at(values: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = values
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _merge_patch_container(context: GlobalContext, component: str) -> dict[str, Any]:
    """The container entry of the component's merge patch, as it lands in ``postRenderers``.

    Empty when no merge patch is built for the component.
    """
    assert context.components is not None
    selector = context.components.root[
        component
    ].config.identifier.label.label_selectable()
    bodies = [
        yaml.safe_load(tp.patch.render_value())["spec"]["template"]["spec"][
            "containers"
        ][0]
        for tp in build_component_container_patches(context)
        if isinstance(tp.patch, ContainerMergePatch)
        and tp.target.label_selector == selector
    ]
    if not bodies:
        return {}
    # One merge patch per workload kind, all with the same container body.
    assert all(body == bodies[0] for body in bodies), bodies
    return bodies[0]


# ---------------------------------------------------------------------------
# infrahub and infrahub-enterprise: value sent to the chart vs merge patch
# ---------------------------------------------------------------------------

# Slots the pre-migration templates wired, with their path under the community chart values.
_INFRAHUB_WIRED_SLOTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("server", "args"): ("infrahubServer", "infrahubServer", "args"),
    ("task-worker", "args"): ("infrahubTaskWorker", "infrahubTaskWorker", "args"),
    ("task-manager", "command"): ("prefect-server", "server", "command"),
    ("task-manager", "args"): ("prefect-server", "server", "args"),
}
# infrahub-enterprise nests the community chart values under `infrahub:`.
_INFRAHUB_CHART_ROOT: dict[str, tuple[str, ...]] = {
    "infrahub": (),
    "infrahub-enterprise": ("infrahub",),
}
_INFRAHUB_STORED: dict[str, dict[str, dict[str, list[str]]]] = {
    "every-wired-slot": {
        "server": {"args": ["gunicorn", "--workers", "4", "--timeout", "120"]},
        "task-worker": {"args": ["prefect", "worker", "start", "--pool", "infra"]},
        "task-manager": {
            "command": ["/usr/bin/tini", "-g", "--"],
            "args": ["uvicorn", "--port", "4200", "--log-level", "debug"],
        },
    },
    "task-manager-command-only": {"task-manager": {"command": ["/bin/sh", "-c"]}},
    "task-manager-args-only": {"task-manager": {"args": ["uvicorn", "--port", "80"]}},
    "nothing-stored": {},
}


@pytest.mark.parametrize("driver", ["infrahub", "infrahub-enterprise"])
@pytest.mark.parametrize(
    "stored", list(_INFRAHUB_STORED.values()), ids=list(_INFRAHUB_STORED)
)
def test_infrahub_merge_patch_carries_what_the_old_template_sent(
    driver: str, stored: dict[str, dict[str, list[str]]]
) -> None:
    context = _context(driver, stored)
    root = _INFRAHUB_CHART_ROOT[driver]
    legacy = _value_at(_render_legacy(driver, context), root)
    migrated = _value_at(_render_migrated(driver, context), root)

    for (component, slot), path in _INFRAHUB_WIRED_SLOTS.items():
        sent_to_chart = _value_at(legacy, path)
        # Guards against a vacuous None == None comparison.
        assert sent_to_chart == stored.get(component, {}).get(slot), (component, slot)
        # The migrated template sends nothing, so only the merge patch sets the list.
        assert _value_at(migrated, path) is None, (component, slot)
        patched = _merge_patch_container(context, component).get(slot)
        assert patched == sent_to_chart, (component, slot)


# ---------------------------------------------------------------------------
# simple-app: full container after helm template and kubectl kustomize
# ---------------------------------------------------------------------------

_SIMPLE_APP_STORED: dict[str, dict[str, list[str]]] = {
    "command-and-args": {
        "command": ["uvicorn", "simple_app.main:app"],
        "args": ["--host", "0.0.0.0", "--port", "8000", "--log-level", "yes"],
    },
    "args-only": {"args": ["--port", "8000", "--root-path", ""]},
    "command-only": {"command": ["python", "-m", "simple_app"]},
    "nothing-stored": {},
}


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
            "styrmin-parity",
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
    """Run ``kubectl kustomize`` with the patches as Flux passes them (inline, with targets)."""
    (workdir / "base.yaml").write_text(manifests)
    kustomization = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": ["base.yaml"],
        "patches": [tp.render_value() for tp in patches],
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


def _server_pod_spec(docs: list[dict[str, Any]]) -> dict[str, Any]:
    [deployment] = [
        doc
        for doc in docs
        if doc["kind"] == "Deployment"
        and doc["metadata"]["labels"].get("app.kubernetes.io/name") == "simple-app"
    ]
    return deployment["spec"]["template"]["spec"]


@pytest.mark.skipif(
    shutil.which("helm") is None or shutil.which("kubectl") is None,
    reason="helm and kubectl are required to render the simple-app chart and run kustomize",
)
@pytest.mark.parametrize(
    "stored", list(_SIMPLE_APP_STORED.values()), ids=list(_SIMPLE_APP_STORED)
)
def test_simple_app_container_is_unchanged_by_the_move(
    stored: dict[str, list[str]], tmp_path: Path
) -> None:
    context = _context("simple-app", {"server": stored} if stored else {})
    assert context.components is not None
    container_name = context.components.root["server"].config.container
    legacy_dir, migrated_dir = tmp_path / "legacy", tmp_path / "migrated"
    legacy_dir.mkdir()
    migrated_dir.mkdir()

    # Before the move the builder built no patch for a command/args-only override.
    legacy = _server_pod_spec(
        _kustomize(
            _helm_template(_render_legacy("simple-app", context), legacy_dir),
            [],
            legacy_dir,
        )
    )
    migrated = _server_pod_spec(
        _kustomize(
            _helm_template(_render_migrated("simple-app", context), migrated_dir),
            build_component_container_patches(context),
            migrated_dir,
        )
    )

    [legacy_container] = [
        c for c in legacy["containers"] if c["name"] == container_name
    ]
    [migrated_container] = [
        c for c in migrated["containers"] if c["name"] == container_name
    ]
    assert legacy_container.get("command") == stored.get("command")
    assert legacy_container.get("args") == stored.get("args")
    assert migrated_container == legacy_container
    assert migrated == legacy
