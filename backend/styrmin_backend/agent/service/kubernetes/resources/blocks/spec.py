from dataclasses import dataclass, field
from typing import Any

from .base import KeyedBlock, TerminalBlock
from .patches import TargetPatch


@dataclass
class SpecBlock(KeyedBlock): ...


@dataclass
class Interval(SpecBlock, TerminalBlock):
    _key: str = field(init=False, default="interval")

    @classmethod
    def one_hour(cls) -> "Interval":
        return cls(value="1h")


@dataclass
class Timeout(SpecBlock, TerminalBlock):
    _key: str = field(init=False, default="timeout")


@dataclass
class ReleaseName(SpecBlock, TerminalBlock):
    _key: str = field(init=False, default="releaseName")


@dataclass
class Remediation(SpecBlock):
    retries: int
    _key: str = field(init=False, default="remediation")

    def render_value(self) -> dict[str, int]:
        return {"retries": self.retries}


@dataclass
class Install(SpecBlock):
    remediation: Remediation
    _key: str = field(init=False, default="install")

    def render_value(self) -> dict[str, dict[str, int]]:
        return {self.remediation.key: self.remediation.render_value()}


@dataclass
class Upgrade(SpecBlock):
    remediation: Remediation
    _key: str = field(init=False, default="upgrade")

    def render_value(self) -> dict[str, dict[str, int]]:
        return {self.remediation.key: self.remediation.render_value()}


@dataclass
class ChartRef(SpecBlock):
    name: str
    namespace: str
    kind: str = field(init=False, default="HelmChart")
    _key: str = field(init=False, default="chartRef")

    def render_value(self) -> dict[str, str]:
        return {"name": self.name, "namespace": self.namespace, "kind": self.kind}


@dataclass
class Values(SpecBlock, TerminalBlock):
    _key: str = field(init=False, default="values")


@dataclass
class PostRenderers(SpecBlock):
    _key: str = field(init=False, default="postRenderers")
    target_patches: list[TargetPatch]

    def render_value(self) -> list[dict[str, dict[str, list[Any]]]]:
        return [
            {
                "kustomize": {
                    "patches": [patch.render_value() for patch in self.target_patches]
                }
            }
        ]
