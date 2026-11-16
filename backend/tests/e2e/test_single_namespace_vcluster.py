"""E2E test: Styrmin in a vCluster that runs in one namespace of a host cluster.

A platform team can give a team a single namespace of a Kubernetes cluster.
Styrmin itself needs cluster-wide access (CRDs, ClusterRoles, one namespace per
deployment), so the team runs a vCluster in its namespace and installs Styrmin
in the vCluster. The session vCluster is the host cluster here:

- The test creates the tenant namespace with Pod Security ``baseline`` enforced,
  and a ServiceAccount that is ``admin`` of that namespace only, plus the rules
  of vCluster's Role that ``admin`` lacks (``fixtures/single-namespace/``).
- With that ServiceAccount's token, it installs vCluster in the namespace, then
  Styrmin in the vCluster, then two simple-apps, ``intent`` and ``executor``.

The Velero node agent is not installed: ``baseline`` rejects its host path
volumes, and in a vCluster the node's pod directories are named after the host
pods, which Velero cannot match to the virtual pods. Backups are not tested.

The deletion test runs last, because the other tests use ``intent``.
"""

import asyncio
import base64
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator

import httpx
import kr8s.asyncio
import pytest
import yaml
from kr8s.asyncio.objects import ConfigMap as AsyncConfigMap
from kr8s.asyncio.objects import Deployment as AsyncDeployment
from kr8s.asyncio.objects import Namespace as AsyncNamespace
from kr8s.asyncio.objects import NetworkPolicy as AsyncNetworkPolicy
from kr8s.asyncio.objects import Pod as AsyncPod
from kr8s.asyncio.objects import Secret as AsyncSecret
from kr8s.asyncio.objects import Service as AsyncService
from kr8s.asyncio.objects import object_from_spec
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio import config as kubeconfig
from kubernetes_asyncio.client.exceptions import ApiException as K8sApiException

from styrmin_sdk import StyrminClient

from tests.e2e.conftest import (
    FIXTURES_DIR,
    PROJECT_ROOT,
    _portforward,
    _wait_for_http,
)
from tests.e2e.drivers.api_driver import ApiScenarioDriver
from tests.e2e.helpers.ingress import wait_for_deployment_status

pytestmark = [
    pytest.mark.shard_single_namespace,
]

SINGLE_NAMESPACE_FIXTURES = FIXTURES_DIR / "single-namespace"
VCLUSTER_CHART_VERSION = "0.33.2"
VCLUSTER_RELEASE = "styrmin-vc"
# The session git server and chart server run in the host's "default" namespace.
HOST_SERVICE_NAMES = (
    "git-server.default.svc.cluster.local",
    "chart-server.default.svc.cluster.local",
)
# vCluster labels each object that it copies to the host with its virtual namespace.
VIRTUAL_NAMESPACE_LABEL = "vcluster.loft.sh/namespace"


@pytest.fixture(scope="module")
async def tenant(
    vcluster: dict, tmp_path_factory: pytest.TempPathFactory
) -> AsyncGenerator[dict[str, str], None]:
    """A host namespace, and a kubeconfig whose user is admin of that namespace only."""
    core_api = kubeclient.CoreV1Api(vcluster["api"])
    # The "styrmin" prefix makes the failure log dump of the conftest include it.
    namespace = f"styrmin-tenant-{uuid.uuid4().hex[:8]}"
    await core_api.create_namespace(
        body=kubeclient.V1Namespace(
            metadata=kubeclient.V1ObjectMeta(
                name=namespace,
                labels={"pod-security.kubernetes.io/enforce": "baseline"},
            )
        )
    )
    try:
        admin_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])
        rbac = (SINGLE_NAMESPACE_FIXTURES / "tenant-rbac.yaml").read_text()
        for doc in yaml.safe_load_all(rbac):
            if not doc:
                continue
            doc["metadata"]["namespace"] = namespace
            for subject in doc.get("subjects", []):
                subject["namespace"] = namespace
            await object_from_spec(doc, api=admin_api).create()

        token = await core_api.create_namespaced_service_account_token(
            name="tenant-admin",
            namespace=namespace,
            body=kubeclient.AuthenticationV1TokenRequest(
                spec=kubeclient.V1TokenRequestSpec(
                    audiences=[], expiration_seconds=6 * 3600
                )
            ),
        )
        host_config = yaml.safe_load(Path(vcluster["kubeconfig_path"]).read_text())
        context = next(
            entry["context"]
            for entry in host_config["contexts"]
            if entry["name"] == host_config["current-context"]
        )
        cluster = next(
            entry["cluster"]
            for entry in host_config["clusters"]
            if entry["name"] == context["cluster"]
        )
        kubeconfig_path = tmp_path_factory.mktemp("tenant") / "kubeconfig"
        kubeconfig_path.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "Config",
                    "clusters": [{"name": "host", "cluster": cluster}],
                    "users": [
                        {"name": "tenant-admin", "user": {"token": token.status.token}}
                    ],
                    "contexts": [
                        {
                            "name": "tenant",
                            "context": {
                                "cluster": "host",
                                "user": "tenant-admin",
                                "namespace": namespace,
                            },
                        }
                    ],
                    "current-context": "tenant",
                }
            )
        )
        yield {"namespace": namespace, "kubeconfig_path": str(kubeconfig_path)}
    finally:
        await core_api.delete_namespace(name=namespace)


@pytest.fixture(scope="module")
async def tenant_vcluster(
    tenant: dict[str, str], tmp_path_factory: pytest.TempPathFactory
) -> AsyncGenerator[str, None]:
    """Install vCluster in the tenant namespace as the tenant; yield its kubeconfig path."""
    namespace = tenant["namespace"]
    await asyncio.to_thread(
        subprocess.run,
        [
            "helm",
            "upgrade",
            "--install",
            VCLUSTER_RELEASE,
            "vcluster",
            "--repo",
            "https://charts.loft.sh",
            "--version",
            VCLUSTER_CHART_VERSION,
            "-n",
            namespace,
            "-f",
            str(SINGLE_NAMESPACE_FIXTURES / "vcluster.yaml"),
            "--kubeconfig",
            tenant["kubeconfig_path"],
            "--wait",
            "--timeout",
            "10m",
        ],
        check=True,
    )

    tenant_api = await kr8s.asyncio.api(kubeconfig=tenant["kubeconfig_path"])
    secret = await AsyncSecret.get(
        f"vc-{VCLUSTER_RELEASE}", namespace=namespace, api=tenant_api
    )
    virtual_config = yaml.safe_load(base64.b64decode(secret.raw["data"]["config"]))
    service = await AsyncService.get(
        VCLUSTER_RELEASE, namespace=namespace, api=tenant_api
    )
    # The kubeconfig names https://localhost:8443; the certificate is valid for localhost.
    async with _portforward(service, remote_port=8443) as local_port:
        for entry in virtual_config["clusters"]:
            entry["cluster"]["server"] = f"https://localhost:{local_port}"
        kubeconfig_path = tmp_path_factory.mktemp("tenant-vcluster") / "kubeconfig"
        kubeconfig_path.write_text(yaml.safe_dump(virtual_config))
        yield str(kubeconfig_path)


@pytest.fixture(scope="module")
async def tenant_styrmin(
    vcluster: dict,
    tenant_vcluster: str,
    styrmin_image: list[str],
    admin_credentials: tuple[str, str],
) -> AsyncGenerator[StyrminClient, None]:
    """Install Styrmin in the tenant's vCluster; yield an admin client of it."""
    virtual_api = await kr8s.asyncio.api(kubeconfig=tenant_vcluster)
    await _forward_host_services_dns(vcluster, virtual_api)

    github_pat = os.environ.get("GITHUB_PAT", "default")
    await asyncio.to_thread(
        subprocess.run,
        [
            "helm",
            "upgrade",
            "--install",
            "styrmin",
            "--create-namespace",
            "-n",
            "styrmin",
            str(PROJECT_ROOT / "helm" / "styrmin"),
            "-f",
            str(FIXTURES_DIR / "styrmin-values.yaml"),
            "--set",
            f"styrmin.driver.token={github_pat}",
            "--set",
            f"styrmin.agentSource.token={github_pat}",
            # The telemetry sink of styrmin-values.yaml runs in the host only.
            "--set",
            "styrmin.telemetry.enabled=false",
            # Pod Security "baseline" rejects the node agent's host path volumes.
            "--set",
            "velero.deployNodeAgent=false",
            *styrmin_image,
            "--kubeconfig",
            tenant_vcluster,
            "--wait",
            "--timeout",
            "10m",
        ],
        check=True,
    )

    service = await AsyncService.get(
        "styrmin-server", namespace="styrmin", api=virtual_api
    )
    async with _portforward(service, remote_port=8000) as local_port:
        styrmin_url = f"http://localhost:{local_port}"
        await _wait_for_http(f"{styrmin_url}/health", timeout=180.0)
        username, password = admin_credentials
        async with StyrminClient(server_address=styrmin_url) as bootstrap_client:
            login = await bootstrap_client.auth.login(
                username=username, password=password
            )
        async with StyrminClient(
            server_address=styrmin_url, token=login.token
        ) as client:
            yield client


@pytest.fixture(scope="module")
async def tenant_deployments(
    tenant_styrmin: StyrminClient,
    git_server: dict[str, str],
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
) -> dict[str, str]:
    """Ids of an environment of the vCluster and of its running simple-apps.

    The keys are ``environment``, ``intent`` and ``executor``.
    """
    driver = ApiScenarioDriver(tenant_styrmin)
    cluster = await driver.create_cluster(
        name="tenant-cluster",
        config={
            "fqdn_suffix": "styrmin.com",
            "external_url_scheme": "http",
            "external_url_port": 8080,
            "ingress_class": "traefik",
            # The dedicated Traefik brings the Traefik CRDs that Styrmin's
            # Middlewares need. A ClusterIP Service needs no load balancer of the host.
            "dedicated_ingress": {
                "implementation": "traefik",
                "type": "ingress",
                "service": {"type": "ClusterIP"},
            },
            "standard_storage": {"storage_class": "local-path"},
            "fast_storage": {"storage_class": "local-path"},
        },
    )
    environment = await driver.create_environment(
        name="tenant-environment", cluster_id=cluster.id, config={}
    )
    await driver.load_driver_version(git_url=git_server["simple-app"], ref="master")

    ids: dict[str, str] = {"environment": environment.id}
    for name in ("intent", "executor"):
        deployment = await driver.create_deployment(
            driver="simple-app",
            version="0.1.0",
            environment_id=environment.id,
            service_name_overrides=[
                {"driverServiceName": "simple-app", "overrideName": name}
            ],
        )
        ids[name] = deployment.id
    for name in ("intent", "executor"):
        # The first deployment also installs the dedicated ingress controller.
        await driver.wait_for_deployment_running(deployment_id=ids[name], timeout=600.0)
    return ids


@pytest.mark.api_only(
    reason="Checks the tenant's Kubernetes permissions only; the [ui-chromium] "
    "variant would run the same access reviews.",
)
@pytest.mark.ci
async def test_tenant_holds_no_cluster_wide_permissions(
    tenant: dict[str, str],
    driver_mode: str,  # noqa: ARG001 — gives the node ID its [api] / [ui] part
    browser_name: str,  # noqa: ARG001 — gives the node ID its -chromium part
) -> None:
    """The tenant can create pods in its namespace, and nothing outside it."""
    api = await kubeconfig.new_client_from_config(config_file=tenant["kubeconfig_path"])
    async with api:
        authorization_api = kubeclient.AuthorizationV1Api(api)

        async def allowed(group: str, resource: str, namespace: str | None) -> bool:
            review = await authorization_api.create_self_subject_access_review(
                body=kubeclient.V1SelfSubjectAccessReview(
                    spec=kubeclient.V1SelfSubjectAccessReviewSpec(
                        resource_attributes=kubeclient.V1ResourceAttributes(
                            group=group,
                            resource=resource,
                            verb="create",
                            namespace=namespace,
                        )
                    )
                )
            )
            return review.status.allowed

        assert await allowed("", "pods", tenant["namespace"])
        assert not await allowed("", "pods", "default")
        for group, resource in (
            ("", "namespaces"),
            ("apiextensions.k8s.io", "customresourcedefinitions"),
            ("rbac.authorization.k8s.io", "clusterroles"),
            ("rbac.authorization.k8s.io", "clusterrolebindings"),
        ):
            assert not await allowed(group, resource, None), (
                f"The tenant must not create {resource}: the test would not show "
                "that Styrmin runs with access to one namespace."
            )


@pytest.mark.api_only(
    reason="Reads namespaces and pods with kr8s only; the [ui-chromium] variant "
    "would read the same objects.",
)
@pytest.mark.ci
async def test_deployments_run_in_namespaces_of_the_vcluster(
    tenant: dict[str, str],
    tenant_vcluster: str,
    tenant_deployments: dict[str, str],
    vcluster: dict,
    driver_mode: str,  # noqa: ARG001 — gives the node ID its [api] / [ui] part
    browser_name: str,  # noqa: ARG001 — gives the node ID its -chromium part
) -> None:
    """Each deployment's namespace exists in the vCluster only; its pods run in the tenant namespace."""
    virtual_api = await kr8s.asyncio.api(kubeconfig=tenant_vcluster)
    tenant_api = await kr8s.asyncio.api(kubeconfig=tenant["kubeconfig_path"])
    host_core_api = kubeclient.CoreV1Api(vcluster["api"])

    for name in ("intent", "executor"):
        namespace = f"styrmin-{tenant_deployments[name]}"
        await AsyncNamespace.get(namespace, api=virtual_api)
        with pytest.raises(K8sApiException) as exc_info:
            await host_core_api.read_namespace(name=namespace)
        assert exc_info.value.status == 404, (
            f"Styrmin created {namespace} in the host, not in the vCluster"
        )

        pods = [
            pod
            async for pod in AsyncPod.list(
                namespace=tenant["namespace"],
                label_selector={VIRTUAL_NAMESPACE_LABEL: namespace},
                api=tenant_api,
            )
            if isinstance(pod, AsyncPod)
        ]
        assert pods, f"No pod of {namespace} runs in {tenant['namespace']}"
        assert all([await pod.ready() for pod in pods]), [pod.name for pod in pods]


@pytest.mark.api_only(
    reason="Probes the alias through a port-forward and kr8s only; the "
    "[ui-chromium] variant would send the same request.",
)
@pytest.mark.ci
async def test_service_alias_reaches_peer_deployment(
    tenant_vcluster: str,
    tenant_deployments: dict[str, str],
    driver_mode: str,  # noqa: ARG001 — gives the node ID its [api] / [ui] part
    browser_name: str,  # noqa: ARG001 — gives the node ID its -chromium part
) -> None:
    """The executor reaches ``intent`` by its short name through the alias in its namespace."""
    virtual_api = await kr8s.asyncio.api(kubeconfig=tenant_vcluster)
    intent_id = tenant_deployments["intent"]
    executor_namespace = f"styrmin-{tenant_deployments['executor']}"

    aliases = await _alias_names(virtual_api, executor_namespace, intent_id, {"intent"})
    assert aliases == {"intent"}, f"Aliases of intent in {executor_namespace}"

    executor_pods = [
        pod
        async for pod in AsyncPod.list(
            namespace=executor_namespace,
            label_selector="app.kubernetes.io/name=simple-app",
            api=virtual_api,
        )
        if isinstance(pod, AsyncPod) and await pod.ready()
    ]
    assert executor_pods, f"No ready simple-app pod in {executor_namespace}"

    async with _portforward(executor_pods[0], remote_port=8000) as local_port:
        await _wait_for_http(f"http://localhost:{local_port}/health", timeout=30.0)
        async with httpx.AsyncClient() as http_client:
            # The alias's DNS name can take a few seconds to resolve.
            deadline = time.time() + 60
            while True:
                response = await http_client.get(
                    f"http://localhost:{local_port}/probe",
                    params={"target": "http://intent:8000/health"},
                    timeout=10,
                )
                assert response.status_code == 200
                data = response.json()
                if data["status"] == 200 or time.time() >= deadline:
                    break
                await asyncio.sleep(3)
    assert data["status"] == 200, f"Probe of intent: {data}"


@pytest.mark.api_only(
    reason="Reads NetworkPolicies with kr8s only; the [ui-chromium] variant "
    "would read the same objects.",
)
@pytest.mark.ci
async def test_network_policies_are_copied_to_the_tenant_namespace(
    tenant: dict[str, str],
    tenant_deployments: dict[str, str],
    driver_mode: str,  # noqa: ARG001 — gives the node ID its [api] / [ui] part
    browser_name: str,  # noqa: ARG001 — gives the node ID its -chromium part
) -> None:
    """The host copy of ``allow-environment-to-server`` still admits only the environment.

    All virtual namespaces share one host namespace, so vCluster replaces the
    namespace selector with a pod selector on a label that it copies from the
    namespace to each pod.
    """
    tenant_api = await kr8s.asyncio.api(kubeconfig=tenant["kubeconfig_path"])
    for name in ("intent", "executor"):
        namespace = f"styrmin-{tenant_deployments[name]}"
        copies = [
            policy.raw["spec"]
            async for policy in AsyncNetworkPolicy.list(
                namespace=tenant["namespace"],
                label_selector={VIRTUAL_NAMESPACE_LABEL: namespace},
                api=tenant_api,
            )
            if isinstance(policy, AsyncNetworkPolicy)
            and policy.annotations.get("vcluster.loft.sh/object-name")
            == "allow-environment-to-server"
        ]
        assert len(copies) == 1, f"Copies of {namespace}/allow-environment-to-server"
        [rule] = copies[0]["ingress"]
        assert rule["ports"] == [{"port": 8000, "protocol": "TCP"}]
        [peer] = rule["from"]
        assert set(peer) == {"podSelector"}, peer
        assert tenant_deployments["environment"] in {
            value
            for key, value in peer["podSelector"]["matchLabels"].items()
            if key.startswith("vcluster.loft.sh/ns-label-")
        }, peer


@pytest.mark.api_only(
    reason="Deletes through the SDK and checks Services and pods with kr8s; "
    "the [ui-chromium] variant would re-run the same SDK call.",
)
@pytest.mark.ci
async def test_deleting_deployment_removes_its_alias_and_pods(
    tenant: dict[str, str],
    tenant_vcluster: str,
    tenant_styrmin: StyrminClient,
    tenant_deployments: dict[str, str],
    driver_mode: str,  # noqa: ARG001 — gives the node ID its [api] / [ui] part
    browser_name: str,  # noqa: ARG001 — gives the node ID its -chromium part
) -> None:
    """Deleting ``intent`` deletes its alias, its namespace and its pods in the tenant namespace."""
    virtual_api = await kr8s.asyncio.api(kubeconfig=tenant_vcluster)
    tenant_api = await kr8s.asyncio.api(kubeconfig=tenant["kubeconfig_path"])
    intent_id = tenant_deployments["intent"]
    intent_namespace = f"styrmin-{intent_id}"
    executor_namespace = f"styrmin-{tenant_deployments['executor']}"

    await tenant_styrmin.deployments.delete(intent_id)
    await wait_for_deployment_status(
        tenant_styrmin, intent_id, "deleted", timeout=300.0
    )

    aliases = await _alias_names(virtual_api, executor_namespace, intent_id, set())
    assert not aliases, f"Aliases of the deleted intent in {executor_namespace}"

    deadline = time.time() + 180
    while True:
        remaining = [
            pod.name
            async for pod in AsyncPod.list(
                namespace=tenant["namespace"],
                label_selector={VIRTUAL_NAMESPACE_LABEL: intent_namespace},
                api=tenant_api,
            )
        ]
        if not remaining or time.time() >= deadline:
            break
        await asyncio.sleep(5)
    assert not remaining, f"Pods of {intent_namespace} left in {tenant['namespace']}"


async def _forward_host_services_dns(
    vcluster: dict, virtual_api: kr8s.asyncio.Api
) -> None:
    """Resolve the host's git server and chart server inside the vCluster.

    The vCluster's DNS server answers every ``cluster.local`` name itself, so a
    server block in its ``coredns-custom`` ConfigMap sends these two names to
    the host's DNS server. Pods of the vCluster run in the host, so they reach
    the host Services' addresses.
    """
    host_dns = await kubeclient.CoreV1Api(vcluster["api"]).read_namespaced_service(
        name="kube-dns", namespace="kube-system"
    )
    zones = " ".join(f"{name}:1053" for name in HOST_SERVICE_NAMES)
    config_map = AsyncConfigMap(
        {
            "metadata": {"name": "coredns-custom", "namespace": "kube-system"},
            "data": {
                "host-services.server": (
                    f"{zones} {{\n    forward . {host_dns.spec.cluster_ip}\n}}\n"
                )
            },
        },
        api=virtual_api,
    )
    await config_map.create()

    # CoreDNS reads the server blocks of coredns-custom when it starts.
    coredns = await AsyncDeployment.get(
        "coredns", namespace="kube-system", api=virtual_api
    )
    await coredns.patch(
        {
            "spec": {
                "template": {
                    "metadata": {"annotations": {"styrmin.io/coredns-custom": "1"}}
                }
            }
        }
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        await coredns.refresh()
        status = coredns.raw.get("status", {})
        replicas = coredns.raw["spec"]["replicas"]
        if (
            status.get("observedGeneration", 0) >= coredns.raw["metadata"]["generation"]
            and status.get("updatedReplicas") == replicas
            and status.get("readyReplicas") == replicas
            and status.get("replicas") == replicas
        ):
            return
        await asyncio.sleep(3)
    raise TimeoutError("CoreDNS of the vCluster did not restart within 180s")


async def _alias_names(
    virtual_api: kr8s.asyncio.Api,
    namespace: str,
    deployment_id: str,
    expected: set[str],
    timeout: float = 60.0,
) -> set[str]:
    """Names of the aliases in *namespace* of the services of *deployment_id*.

    Polls until they are *expected* or *timeout* runs out, and returns the last names.
    """
    deadline = time.time() + timeout
    while True:
        names = {
            svc.name
            async for svc in AsyncService.list(
                namespace=namespace,
                label_selector={
                    "styrmin.io/service-alias": "true",
                    "styrmin.io/deployment-id": deployment_id,
                },
                api=virtual_api,
            )
            if isinstance(svc, AsyncService)
        }
        if names == expected or time.time() >= deadline:
            return names
        await asyncio.sleep(5)
