from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import Name
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    ChartRef,
    Install,
    Interval,
    ReleaseName,
    Remediation,
    Timeout,
    Upgrade,
)
from styrmin_backend.agent.service.kubernetes.resources.custom_resource import (
    HelmRelease,
)


def build_minimal_helm_release(
    release_reference: str,
    chart_reference: str,
) -> HelmRelease:
    return HelmRelease(
        apiVersion="helm.toolkit.fluxcd.io/v2",
        metadata=[Name(value=release_reference)],
        spec=[
            Interval.one_hour(),
            Timeout(value="5m"),
            ChartRef(name=chart_reference, namespace="styrmin"),
            ReleaseName(value=release_reference),
            Install(remediation=Remediation(retries=3)),
            Upgrade(remediation=Remediation(retries=3)),
        ],
    )
