import pytest
import yaml

from kubernetes_asyncio import client as kubeclient

KUBERNETES_LIST_TESTING = ["real_kubernetes", "fake_kubernetes"]


@pytest.fixture(scope="session")
def kubernetes(request: pytest.FixtureRequest) -> kubeclient.ApiClient:
    """Indirect fixture to resolve kubernetes client by name."""
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize("kubernetes", KUBERNETES_LIST_TESTING, indirect=True)
async def test_kubernetes_setup(kubernetes: kubeclient.ApiClient) -> None:
    network_api = kubeclient.NetworkingV1Api(kubernetes)
    ingress: kubeclient.V1IngressList = await network_api.list_namespaced_ingress(
        namespace="default"
    )

    assert len(ingress.items) == 0


@pytest.mark.parametrize("kubernetes", KUBERNETES_LIST_TESTING, indirect=True)
async def test_create_helm_release(kubernetes: kubeclient.ApiClient) -> None:
    obj = kubeclient.CustomObjectsApi(kubernetes)

    spec = yaml.safe_load("""
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: cloud-17f7d272-aaa9-abad-120f-c5198456b56c-extras
spec:
  chartRef:
    kind: HelmChart
    name: cloud-18057fe2-b5be-5404-1235-c51babe0514e
    namespace: opsmill-operator
  install:
    remediation:
      retries: 3
  interval: 1h
  postRenderers:
  - kustomize:
      patches:
      - patch: |
          - op: add
            path: /spec/template/spec/runtimeClassName
            value: gvisor
        target:
          kind: Deployment
          labelSelector: app.kubernetes.io/name=traefik-this-is-a-test
          name: .*
          version: v1
  releaseName: cloud-17f7d272-aaa9-abad-120f-c5198456b56c-extras
  timeout: 5m
  upgrade:
    remediation:
      retries: 3
  values:
    ingress:
      middlewares:
      - name: acl
        spec:
          ipAllowList:
            ipStrategy:
              depth: 1
            sourceRange:
            - 127.0.0.1
      - name: auth
        spec:
          basicAuth:
            removeHeader: true
            secret: ingress-auth
    networkpolicies:
    - name: default-deny-egress
      spec:
        podSelector: {}
        policyTypes:
        - Egress
    - name: default-deny-ingress
      spec:
        ingress:
        - from:
          - podSelector: {}
        podSelector: {}
        policyTypes:
        - Ingress
    - name: traefik-netpolicy-egress
      spec:
        egress:
        - ports:
          - port: 443
            protocol: TCP
        podSelector:
          matchExpressions:
          - key: app.kubernetes.io/name
            operator: In
            values:
            - traefik
        policyTypes:
        - Egress
    - name: infrahub-netpolicy-egress
      spec:
        egress:
        - ports:
          - port: 53
            protocol: UDP
          to:
          - namespaceSelector: {}
            podSelector:
              matchLabels:
                k8s-app: kube-dns
        - to:
          - ipBlock:
              cidr: 0.0.0.0/0
              except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
              - 100.64.0.0/10
""")

    await obj.create_namespaced_custom_object(
        group="helm.toolkit.fluxcd.io",
        version="v2",
        namespace="default",
        plural="helmreleases",
        body=spec,
    )

    objects = await obj.list_namespaced_custom_object(
        group="helm.toolkit.fluxcd.io",
        version="v2",
        namespace="default",
        plural="helmreleases",
    )
    assert len(objects["items"]) == 1
