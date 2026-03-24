from dataclasses import dataclass, field
from typing import Any

from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import (
    MetadataBlock,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import SpecBlock


@dataclass
class CustomResource:
    apiVersion: str
    _kind: str
    metadata: list[MetadataBlock] = field(default_factory=list)
    spec: list[SpecBlock] = field(default_factory=list)

    def add_spec(self, block: SpecBlock) -> None:
        self.spec.append(block)

    def add_metadata(self, block: MetadataBlock) -> None:
        self.metadata.append(block)

    @property
    def kind(self) -> str:
        return self._kind

    def render(self) -> dict[str, Any]:
        return {
            "apiVersion": self.apiVersion,
            "kind": self._kind,
            "metadata": {block.key: block.render_value() for block in self.metadata},
            "spec": {block.key: block.render_value() for block in self.spec},
        }


@dataclass
class HelmRelease(CustomResource):
    """A HelmRelease custom resource.

    Example:
        >>> rh = HelmRelease(
        ...     apiVersion="helm.toolkit.fluxcd.io/v2",
        ...     metadata=[
        ...         Name(value="my-release")
        ...     ],
        ...     spec=[
        ...         Interval.one_hour(),
        ...         Timeout(value="5m"),
        ...         ChartRef(name="my-chart", namespace="styrmin"),
        ...         ReleaseName(value="my-release"),
        ...         Install(remediation=Remediation(retries=3)),
        ...         Upgrade(remediation=Remediation(retries=3)),
        ...     ],
        ... )
        >>> print(yaml.dump(rh.render()))
        apiVersion: helm.toolkit.fluxcd.io/v2
        kind: HelmRelease
        metadata:
        name: my-release
        spec:
        chartRef:
            kind: HelmChart
            name: my-chart
            namespace: styrmin
        install:
            remediation:
            retries: 3
        interval: 1h
        releaseName: my-release
        timeout: 5m
        upgrade:
            remediation:
            retries: 3
    """

    _kind: str = field(init=False, default="HelmRelease")
