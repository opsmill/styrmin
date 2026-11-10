"""E2E test: a service ingress override moves only the overridden service (#598, T025).

User story 1 of ``specs/033-service-ingress-override/spec.md``:

1. Scenario 1: an override on ``task-manager`` (class ``tailscale``, suffix
   ``tailnet.example.ts.net``) changes the Ingress that Styrmin builds for that
   service, and the chart Ingress of the ``infrahub`` service is identical before and
   after (FR-004, FR-013, SC-002). The service address that the deployment reports
   and the Prefect UI API address use the new host (FR-006).
2. Scenario 2: clearing the override gives the cluster's class and suffix back.
3. Scenario 3: the session cluster has ``dedicated_ingress``, so every deployment of
   the session environment is served by a dedicated ingress controller. The Ingresses
   without an override keep the dedicated-controller rule (no ``spec.ingressClassName``,
   the annotation set to the controller implementation), and the overridden one gets
   the override's class fields instead (FR-008).

The test asserts objects on the vCluster, not traffic: no ingress controller of the
override class (Tailscale) runs in the fixtures, and the Prefect UI path through the
dedicated Traefik is covered by ``test_infrahub_services.py``.

Deployment reuse
----------------
This test only changes the config of the Infrahub stack that
``test_infrahub_enterprise_backup_and_restore_lifecycle`` and
``test_infrahub_services.py`` already boot in the ``shard_infrahub`` shard
(``deployed_infrahub_enterprise_app``), and restores the config in a ``finally`` block.
It does not consume ``deployed_infrahub_app`` (the community stack), whose only other
consumer is skipped (``dev/guides/e2e-deployment-sharing.md``, "Reuse before you boot").

Variants
--------
The test runs under both variants. The deployment is changed through
``scenario_driver.update_deployment(config={"services": ...})``. The API driver sends the
typed input. The UI driver fills the ingress class and FQDN suffix fields of the Services
section in the Settings edit drawer and applies through Review & apply
(``DeploymentDetailPage.set_service_ingress_overrides``). Everything else (the baseline,
the assertions on the objects, the restore) is the same in both variants.

Two steps exist only in the ``[ui-chromium]`` variant (T042):

* the deploy form offers the ingress override fields for ``task-manager`` and not for
  ``infrahub`` (``DeployFormPage.read_service_ingress_fields``; the form is not submitted,
  so no second stack boots);
* the Networking summary of the Settings tab lists the class and host of ``task-manager``
  marked overridden or inherited, before the override, with it and after it is cleared
  (``DeploymentDetailPage.read_service_ingress_summary``; FR-016).

The UI steps and the page-object methods they call were written before the frontend that
they drive (T043 to T047) and ran against it in T048. The labels and roles that the page
objects use are listed in the comment above
``DeploymentDetailPage.set_service_ingress_overrides`` and in the docstring of
``DeployFormPage.read_service_ingress_fields``. The deploy form step opens the form
(``DeployFormPage.goto``) before it selects the driver version.

Refused changes (user story 4)
------------------------------
``test_service_ingress_override_refusals_name_the_service`` is ``api_only``: every action goes
through the SDK and the Kubernetes API, and the UI shows the same typed errors in the same
form (T053). It uses the same ``deployed_infrahub_enterprise_app`` stack and boots nothing:

1. An override on ``infrahub`` (``scope: internal``) returns ``SERVICE_INGRESS_NOT_BUILT``
   (FR-009). Nothing is stored and no task starts.
2. With an override stored on ``task-manager``, a version change to a second build of the
   ``infrahub-enterprise`` driver that declares ``task-manager`` internal returns
   ``SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`` (FR-010), both without ``input`` and with
   the ``input`` that ``styrminctl deployments apply`` sends (ADR-065). No task starts, no
   pod is replaced, the deployment stays on its driver version and the override is still
   stored.

The second build is pushed to the in-cluster git server as a branch and supports only
application versions ``>=1.7.0,<1.8``, so no other test resolves to it by mistake. The
refusal comes before any rollout, so no ``1.7.0`` image is pulled. The upgrade that this
refusal prevents, and the one that a clearing request allows, run in the functional tests
(``test_service_ingress_validation.py``), because an Infrahub upgrade takes too long here.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import kr8s.asyncio
import pytest
import yaml
from dulwich import porcelain
from kr8s.asyncio.objects import Deployment as AsyncDeployment
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import OperationFailedError
from styrmin_sdk.models import ServiceConfigInput, UpdateDeploymentInput

from tests.e2e.conftest import _portforward
from tests.e2e.drivers import ScenarioDriver
from tests.e2e.drivers.api_driver import ApiScenarioDriver
from tests.e2e.pages.deploy_form import DeployFormPage
from tests.e2e.pages.deployment_detail import DeploymentDetailPage

pytestmark = [
    pytest.mark.shard_infrahub,
]

# Set by the session fixtures (conftest ``styrmin_resources``).
_ENVIRONMENT_NAME = "test-environment"
_CLUSTER_SUFFIX = "styrmin.com"
_EXTERNAL_URL_SCHEME = "http"
_EXTERNAL_URL_PORT = 8080
_CLUSTER_INGRESS_CLASS = "traefik"
_DEDICATED_IMPLEMENTATION = "traefik"

_OVERRIDE_CLASS = "tailscale"
_OVERRIDE_SUFFIX = "tailnet.example.ts.net"
_OVERRIDE = {
    "task-manager": {"ingress_class": _OVERRIDE_CLASS, "fqdn_suffix": _OVERRIDE_SUFFIX}
}

_SERVICE_NAME_LABEL = "styrmin.io/service-name"
_OPERATOR_BOOKKEEPING_PREFIX = "kopf.zalando.org/"
_TASK_MANAGER_INGRESS = "styrmin-svc-task-manager"
_TASK_MANAGER_WORKLOAD = "styrmin-task-manager"
_TASK_MANAGER_CONTAINER = "prefect-server"

# The annotations of an Ingress without an override (ADR-071, research D-006), in the
# session cluster: dedicated controller, ``external_dns_endpoints_type: NodeExternalIP``,
# no ``ip_whitelist``.
_DEFAULT_ANNOTATION_KEYS = {
    "traefik.ingress.kubernetes.io/router.entrypoints",
    "external-dns.alpha.kubernetes.io/hostname",
    "external-dns.alpha.kubernetes.io/cloudflare-proxied",
    "external-dns.alpha.kubernetes.io/endpoints-type",
    "kubernetes.io/ingress.class",
}

RECONCILE_TIMEOUT_SECONDS = 480.0


def _readable_host(service_name: str, suffix: str) -> str:
    return f"{service_name}-{_ENVIRONMENT_NAME}.{suffix}"


# Marks of the Networking summary (FR-016).
_OVERRIDDEN = "Overridden"
_INHERITED = "Inherited"


def _summary_row(ingress_class: str, host: str, mark: str) -> dict[str, str]:
    """What the Networking summary shows for ``task-manager``: both values carry ``mark``."""
    return {
        "ingress_class": ingress_class,
        "ingress_class_mark": mark,
        "host": host,
        "host_mark": mark,
    }


async def _task_manager_summary(
    page: Any, *, environment_id: str, deployment_id: str
) -> dict[str, str]:
    """Open the deployment's Settings tab and read the ``task-manager`` group of the
    Networking summary (UI variant only)."""
    detail = DeploymentDetailPage(page)
    await detail.goto(environment_id=environment_id, deployment_id=deployment_id)
    summary = await detail.read_service_ingress_summary()
    assert "task-manager" in summary, sorted(summary)
    return summary["task-manager"]


def _prefect_ui_api_url(host: str) -> str:
    return f"{_EXTERNAL_URL_SCHEME}://{host}:{_EXTERNAL_URL_PORT}/api"


async def _ingresses(kr8s_api: Any, namespace: str) -> dict[str, dict[str, Any]]:
    """The Ingress objects of the namespace, by name, as the API server returns them."""
    return {
        ing.name: dict(ing.raw)
        async for ing in AsyncIngress.list(namespace=namespace, api=kr8s_api)
        if isinstance(ing, AsyncIngress)
    }


def _annotations(ingress: dict[str, Any]) -> dict[str, str]:
    """The annotations that Styrmin sets on an Ingress.

    The operator watches the Ingress that Styrmin builds, so kopf adds its own bookkeeping
    annotation (``kopf.zalando.org/last-handled-configuration``). It is not an annotation
    that Styrmin's ingress rules set, so it is left out of every comparison below.
    """
    return {
        key: value
        for key, value in ingress["metadata"].get("annotations", {}).items()
        if not key.startswith(_OPERATOR_BOOKKEEPING_PREFIX)
    }


def _hosts(ingress: dict[str, Any]) -> list[str]:
    return [rule["host"] for rule in ingress["spec"].get("rules", []) if "host" in rule]


def _comparable(ingress: dict[str, Any]) -> dict[str, Any]:
    """What an operator sees of an Ingress: labels, annotations and spec.

    Leaves out the fields that the API server and the controllers change on their own
    (resource version, generation, managed fields, status) and the operator's own
    bookkeeping annotation.
    """
    metadata = ingress["metadata"]
    return {
        "labels": metadata.get("labels", {}),
        "annotations": _annotations(ingress),
        "spec": ingress["spec"],
    }


def _split(
    ingresses: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(task_manager, infrahub_chart)``: the Ingress that Styrmin builds for
    ``task-manager``, and the one other Ingress of the namespace, which is the chart
    Ingress of the ``infrahub`` service."""
    assert _TASK_MANAGER_INGRESS in ingresses, sorted(ingresses)
    task_manager = ingresses[_TASK_MANAGER_INGRESS]
    others = {
        name: ing for name, ing in ingresses.items() if name != _TASK_MANAGER_INGRESS
    }
    assert len(others) == 1, (
        "Expected exactly one other Ingress (the chart Ingress of the infrahub "
        f"service, the Prefect chart Ingress is off): {sorted(others)}"
    )
    (infrahub_chart,) = others.values()
    assert _SERVICE_NAME_LABEL not in infrahub_chart["metadata"].get("labels", {})
    return task_manager, infrahub_chart


async def _task_ids(client: StyrminClient, deployment_id: str) -> set[str]:
    return {
        str(e.task.id) for e in await client.deployments.get_timeline(deployment_id)
    }


async def _wait_for_new_task_succeeded(
    client: StyrminClient, deployment_id: str, known: set[str]
) -> str:
    """Wait for the one task created after ``known`` to end; assert it succeeded.

    ``Deployment.status`` stays ``running`` through an update, so only the task result
    tells that the rollout ended.
    """
    deadline = time.monotonic() + RECONCILE_TIMEOUT_SECONDS
    new: list[Any] = []
    while time.monotonic() < deadline:
        timeline = await client.deployments.get_timeline(deployment_id)
        new = [e.task for e in timeline if str(e.task.id) not in known]
        assert len(new) <= 1, [(str(t.id), t.type_, t.result.value) for t in new]
        if new and new[0].result.value != "RUNNING":
            task = new[0]
            assert task.result.value == "SUCCEEDED", (
                f"task {task.id} ({task.type_}) ended {task.result.value}: "
                f"{[(step.name, step.status, step.error) for step in task.steps]}"
            )
            return str(task.id)
        await asyncio.sleep(2)
    raise TimeoutError(
        f"No new task on deployment {deployment_id} ended within "
        f"{RECONCILE_TIMEOUT_SECONDS}s: {[(str(t.id), t.result.value) for t in new]}"
    )


async def _change_services(
    scenario_driver: ScenarioDriver,
    client: StyrminClient,
    deployment_id: str,
    services: dict[str, dict[str, str]],
) -> None:
    """Replace the service overrides of the deployment and wait for the update task."""
    known = await _task_ids(client, deployment_id)
    await scenario_driver.update_deployment(
        deployment_id=deployment_id, config={"services": services}
    )
    await _wait_for_new_task_succeeded(client, deployment_id, known)


async def _prefect_ui_api_urls(kr8s_api: Any, namespace: str) -> set[str]:
    """Every value of the ``prefect-server`` container env that is a Prefect UI API address.

    Read from the desired pod template, so it does not wait for the pod to restart. The
    chart's name for the variable is not asserted, only the value.
    """
    workload = await AsyncDeployment.get(
        _TASK_MANAGER_WORKLOAD, namespace=namespace, api=kr8s_api
    )
    (container,) = [
        c
        for c in workload.spec["template"]["spec"]["containers"]
        if c["name"] == _TASK_MANAGER_CONTAINER
    ]
    return {
        entry["value"]
        for entry in container.get("env", [])
        if str(entry.get("value", "")).endswith("/api")
        and str(entry.get("value", "")).startswith(f"{_EXTERNAL_URL_SCHEME}://")
    }


def _assert_default_task_manager_ingress(ingress: dict[str, Any]) -> None:
    """No override: the resolved suffix and the dedicated-controller rule (FR-003, FR-008)."""
    assert _hosts(ingress) == [_readable_host("task-manager", _CLUSTER_SUFFIX)]
    assert ingress["spec"].get("ingressClassName") is None
    annotations = _annotations(ingress)
    assert set(annotations) == _DEFAULT_ANNOTATION_KEYS, annotations
    assert annotations["kubernetes.io/ingress.class"] == _DEDICATED_IMPLEMENTATION
    assert "tls" not in ingress["spec"]


def _assert_overridden_task_manager_ingress(ingress: dict[str, Any]) -> None:
    """Override: its class and suffix, and nothing else (FR-004, FR-008)."""
    assert _hosts(ingress) == [_readable_host("task-manager", _OVERRIDE_SUFFIX)]
    assert ingress["spec"]["ingressClassName"] == _OVERRIDE_CLASS
    assert _annotations(ingress) == {"kubernetes.io/ingress.class": _OVERRIDE_CLASS}, (
        "An overridden Ingress carries no entry-point, external-dns, Cloudflare or allow-list annotation"
    )
    assert "tls" not in ingress["spec"]


@pytest.mark.ci
async def test_service_ingress_override_moves_only_the_overridden_service(
    deployed_infrahub_enterprise_app: dict,
    styrmin_resources: dict,
    scenario_driver: ScenarioDriver,
    vcluster: dict,
    driver_mode: str,
    session_ui_page: Any,
) -> None:
    """Set and clear an override on ``task-manager``; the ``infrahub`` Ingress never changes."""
    deployment_id = deployed_infrahub_enterprise_app["deployment_id"]
    environment_id = styrmin_resources["environment_id"]
    namespace = deployed_infrahub_enterprise_app["namespace"]
    client: StyrminClient = styrmin_resources["client"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
    # The fixture created the deployment through the session driver, so the driver of
    # this test needs the environment (the UI driver navigates with it).
    scenario_driver.attach_to_deployment(environment_id=environment_id)

    try:
        if driver_mode == "ui":
            # The deploy form offers the override fields for the external service
            # only (spec User Story 3, scenario 2; FR-009 is prevented in the UI).
            # The form is not submitted.
            deploy_form = DeployFormPage(session_ui_page)
            await deploy_form.goto(environment_id=environment_id)
            assert await deploy_form.read_service_ingress_fields(
                driver="infrahub-enterprise"
            ) == ["task-manager"]

        # --- Before: no override ------------------------------------------------
        before = await _ingresses(kr8s_api, namespace)
        task_manager_before, infrahub_before = _split(before)
        _assert_default_task_manager_ingress(task_manager_before)
        # The chart Ingress keeps the dedicated-controller rule as well (scenario 3).
        assert infrahub_before["spec"].get("ingressClassName") is None
        assert (
            _annotations(infrahub_before)["kubernetes.io/ingress.class"]
            == _DEDICATED_IMPLEMENTATION
        )
        # The same rules feed both Ingresses (FR-003): the external-dns host name of the
        # Ingress that Styrmin builds is the one that the chart patch sets, release
        # reference included.
        dns_hostname = "external-dns.alpha.kubernetes.io/hostname"
        assert (
            _annotations(task_manager_before)[dns_hostname]
            == _annotations(infrahub_before)[dns_hostname]
        )
        deployment = await client.deployments.get(deployment_id)
        services_before = {
            s.driver_service_name: s for s in deployment.deployed_services
        }
        assert services_before["task-manager"].human_readable_fqdn == _readable_host(
            "task-manager", _CLUSTER_SUFFIX
        )
        assert await _prefect_ui_api_urls(kr8s_api, namespace) == {
            _prefect_ui_api_url(_readable_host("task-manager", _CLUSTER_SUFFIX))
        }
        inherited_summary = _summary_row(
            _CLUSTER_INGRESS_CLASS,
            _readable_host("task-manager", _CLUSTER_SUFFIX),
            _INHERITED,
        )
        if driver_mode == "ui":
            # Spec User Story 3, scenario 3: no override, so class and host are shown
            # and marked inherited.
            assert (
                await _task_manager_summary(
                    session_ui_page,
                    environment_id=environment_id,
                    deployment_id=deployment_id,
                )
                == inherited_summary
            )

        # --- Scenario 1 and 3: set the override ----------------------------------
        await _change_services(scenario_driver, client, deployment_id, _OVERRIDE)

        after = await _ingresses(kr8s_api, namespace)
        assert set(after) == set(before), (set(after), set(before))
        task_manager_after, infrahub_after = _split(after)
        _assert_overridden_task_manager_ingress(task_manager_after)
        # SC-002, FR-013: the other service's Ingress is identical before and after.
        assert _comparable(infrahub_after) == _comparable(infrahub_before)

        deployment = await client.deployments.get(deployment_id)
        services_after = {
            s.driver_service_name: s for s in deployment.deployed_services
        }
        overridden_host = _readable_host("task-manager", _OVERRIDE_SUFFIX)
        # FR-006: the address that the deployment reports for the service is the new host.
        assert services_after["task-manager"].human_readable_fqdn == overridden_host
        assert (
            services_after["task-manager"].human_readable_url
            == f"{_EXTERNAL_URL_SCHEME}://{overridden_host}:{_EXTERNAL_URL_PORT}"
        )
        # The application address and the other service keep the resolved suffix.
        for name, service in services_after.items():
            assert service.primary_fqdn == services_before[name].primary_fqdn
            if name != "task-manager":
                assert (
                    service.human_readable_fqdn
                    == services_before[name].human_readable_fqdn
                )
        # The driver reads the override host: the Prefect UI calls its API there.
        assert await _prefect_ui_api_urls(kr8s_api, namespace) == {
            _prefect_ui_api_url(overridden_host)
        }
        if driver_mode == "ui":
            # Spec User Story 3, scenario 1: the Networking summary lists task-manager
            # at the new host under the new class, marked overridden (FR-016).
            assert await _task_manager_summary(
                session_ui_page,
                environment_id=environment_id,
                deployment_id=deployment_id,
            ) == _summary_row(_OVERRIDE_CLASS, overridden_host, _OVERRIDDEN)

        # --- Scenario 2: clear the override --------------------------------------
        await _change_services(scenario_driver, client, deployment_id, {})

        cleared = await _ingresses(kr8s_api, namespace)
        assert set(cleared) == set(before)
        task_manager_cleared, infrahub_cleared = _split(cleared)
        _assert_default_task_manager_ingress(task_manager_cleared)
        assert _comparable(task_manager_cleared) == _comparable(task_manager_before)
        assert _comparable(infrahub_cleared) == _comparable(infrahub_before)
        deployment = await client.deployments.get(deployment_id)
        assert not (deployment.config or {}).get("services")
        assert await _prefect_ui_api_urls(kr8s_api, namespace) == {
            _prefect_ui_api_url(_readable_host("task-manager", _CLUSTER_SUFFIX))
        }
        if driver_mode == "ui":
            assert (
                await _task_manager_summary(
                    session_ui_page,
                    environment_id=environment_id,
                    deployment_id=deployment_id,
                )
                == inherited_summary
            )
    finally:
        # The deployment is shared with the other Infrahub tests of the shard.
        deployment = await client.deployments.get(deployment_id)
        if (deployment.config or {}).get("services"):
            await _change_services(ApiScenarioDriver(client), client, deployment_id, {})


# ---------------------------------------------------------------------------
# User story 4: refused changes name the service (FR-009, FR-010, SC-004)
# ---------------------------------------------------------------------------

_INTERNAL_BUILD_BRANCH = "task-manager-internal"
# Only this application version resolves to the second build (see the module docstring).
_INTERNAL_BUILD_SUPPORTED_VERSIONS = ">=1.7.0,<1.8"
_INTERNAL_BUILD_APPLICATION_VERSION = "1.7.0"

_TASK_MANAGER_OVERRIDE_INPUT = ServiceConfigInput(
    name="task-manager", ingress_class=_OVERRIDE_CLASS, fqdn_suffix=_OVERRIDE_SUFFIX
)


async def _publish_task_manager_internal_build(
    *, vcluster: dict, tmp_path: Path
) -> str:
    """Push a second build of the ``infrahub-enterprise`` driver that declares ``task-manager``
    ``scope: internal``, as a branch of the in-cluster git server. Return the branch name.

    Clones the repository that the session pushed, so the rest of the driver is identical.
    ``spec.version`` is the next integer, and ``supported_versions`` is narrowed to
    ``_INTERNAL_BUILD_SUPPORTED_VERSIONS`` so that no other test resolves to this build.
    """
    repo_dir = tmp_path / "infrahub-enterprise-internal"
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
    git_svc = await AsyncService.get("git-server", namespace="default", api=kr8s_api)
    async with _portforward(git_svc, remote_port=9418) as local_port:
        local_url = f"git://localhost:{local_port}/infrahub-enterprise.git"
        await asyncio.to_thread(porcelain.clone, local_url, str(repo_dir))

        spec_path = repo_dir / "driver.styrmin.yml"
        spec = yaml.safe_load(spec_path.read_text())
        spec["spec"]["version"] = str(int(spec["spec"]["version"]) + 1)
        spec["spec"]["supported_versions"] = _INTERNAL_BUILD_SUPPORTED_VERSIONS
        (task_manager,) = [
            s for s in spec["spec"]["services"] if s["name"] == "task-manager"
        ]
        assert task_manager["scope"] == "external", task_manager
        task_manager["scope"] = "internal"
        spec_path.write_text(yaml.dump(spec, default_flow_style=False))

        await asyncio.to_thread(
            porcelain.add, str(repo_dir), paths=["driver.styrmin.yml"]
        )
        await asyncio.to_thread(
            porcelain.commit,
            str(repo_dir),
            message=b"declare task-manager internal",
            author=b"test <test@test.com>",
            committer=b"test <test@test.com>",
        )
        await asyncio.to_thread(
            porcelain.push,
            str(repo_dir),
            remote_location=local_url,
            refspecs=[f"HEAD:refs/heads/{_INTERNAL_BUILD_BRANCH}".encode()],
        )
    return _INTERNAL_BUILD_BRANCH


async def _rollout_state(kr8s_api: Any, namespace: str) -> dict[str, Any]:
    """What a pod change would alter: each pod's uid and restart counts, and the generation
    of the ``task-manager`` workload, which changes when its pod template changes."""
    pods = {
        pod.name: (
            pod.raw["metadata"]["uid"],
            tuple(
                status["restartCount"]
                for status in pod.raw.get("status", {}).get("containerStatuses", [])
            ),
        )
        async for pod in AsyncPod.list(namespace=namespace, api=kr8s_api)
    }
    workload = await AsyncDeployment.get(
        _TASK_MANAGER_WORKLOAD, namespace=namespace, api=kr8s_api
    )
    return {
        "pods": pods,
        "task_manager_generation": workload.raw["metadata"]["generation"],
    }


@pytest.mark.ci
@pytest.mark.api_only(
    reason="Every action goes through the SDK and the Kubernetes API; the UI shows the "
    "same typed errors (T053) and the dual-entrypoint scenario is the test above"
)
async def test_service_ingress_override_refusals_name_the_service(
    deployed_infrahub_enterprise_app: dict,
    styrmin_resources: dict,
    git_server: dict[str, str],
    vcluster: dict,
    tmp_path: Path,
) -> None:
    """An override on an internal service, and a version change that would drop an override,
    are refused with an error that names the service. Nothing changes in the cluster."""
    deployment_id = deployed_infrahub_enterprise_app["deployment_id"]
    namespace = deployed_infrahub_enterprise_app["namespace"]
    client: StyrminClient = styrmin_resources["client"]
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])

    try:
        config_before = (await client.deployments.get(deployment_id)).config
        known = await _task_ids(client, deployment_id)
        state_before = await _rollout_state(kr8s_api, namespace)

        # --- Scenario 1 (FR-009): an override on the internal ``infrahub`` service ---
        with pytest.raises(OperationFailedError) as not_built:
            await client.deployments.update(
                deployment_id,
                input=UpdateDeploymentInput(
                    services=[
                        ServiceConfigInput(
                            name="infrahub", ingress_class=_OVERRIDE_CLASS
                        )
                    ]
                ),
            )
        assert not_built.value.typename == "SERVICE_INGRESS_NOT_BUILT", not_built.value
        assert not_built.value.extensions["service_name"] == "infrahub"
        assert not_built.value.extensions["scope"] == "internal"
        assert "'infrahub'" in str(not_built.value)
        assert "does not build" in str(not_built.value)
        assert await _task_ids(client, deployment_id) == known
        assert (await client.deployments.get(deployment_id)).config == config_before
        assert await _rollout_state(kr8s_api, namespace) == state_before

        # --- Scenario 2 (FR-010): a version change that makes task-manager internal ---
        branch = await _publish_task_manager_internal_build(
            vcluster=vcluster, tmp_path=tmp_path
        )
        internal_build = await client.drivers.load_version(
            git_server["infrahub-enterprise"], branch
        )
        deployment = await client.deployments.get(deployment_id)
        bound_driver_version = str(deployment.application_driver_version_id)
        bound_version = deployment.application_driver_version.version
        assert bound_driver_version != str(internal_build.id)

        await _change_services(
            ApiScenarioDriver(client), client, deployment_id, _OVERRIDE
        )
        stored_config = (await client.deployments.get(deployment_id)).config
        assert stored_config["services"] == _OVERRIDE, stored_config
        known = await _task_ids(client, deployment_id)
        state_before = await _rollout_state(kr8s_api, namespace)

        # Without ``input``, and with the ``input`` that ``apply`` sends (ADR-065).
        for input_ in (
            None,
            UpdateDeploymentInput(services=[_TASK_MANAGER_OVERRIDE_INPUT]),
        ):
            with pytest.raises(OperationFailedError) as dropped:
                await client.deployments.update_version(
                    deployment_id,
                    _INTERNAL_BUILD_APPLICATION_VERSION,
                    driver_version_id=str(internal_build.id),
                    input=input_,
                )
            error = dropped.value
            assert error.typename == "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED", error
            assert error.extensions["service_name"] == "task-manager", error.extensions
            assert error.extensions["reason"] == "internal", error.extensions
            assert error.extensions["current_version"] == bound_version, (
                error.extensions
            )
            assert error.extensions["target_version"] == internal_build.version, (
                error.extensions
            )
            assert bound_version != internal_build.version
            assert "'task-manager'" in str(error)

            # No task, no pod change, same driver version, override still stored.
            assert await _task_ids(client, deployment_id) == known
            assert await _rollout_state(kr8s_api, namespace) == state_before
            deployment = await client.deployments.get(deployment_id)
            assert str(deployment.application_driver_version_id) == bound_driver_version
            assert deployment.application_version == "1.6.0"
            assert deployment.config == stored_config
    finally:
        # The deployment is shared with the other Infrahub tests of the shard.
        deployment = await client.deployments.get(deployment_id)
        if (deployment.config or {}).get("services"):
            await _change_services(ApiScenarioDriver(client), client, deployment_id, {})
