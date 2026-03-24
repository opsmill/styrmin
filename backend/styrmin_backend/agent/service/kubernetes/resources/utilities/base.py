from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import PostRenderers
from styrmin_backend.context.models.contexts import GlobalContext


@dataclass
class Utility(ABC):
    kind: str
    values_template_file: str

    @abstractmethod
    def build_app_post_rendering_patches(
        self, context: GlobalContext, release_reference: str
    ) -> list[TargetPatch]: ...

    @abstractmethod
    def build_extra_spec(self, context: GlobalContext) -> list[PostRenderers]: ...

    @abstractmethod
    def build_resources(
        self, context: GlobalContext, release_reference: str, namespace: str
    ) -> list[dict[str, Any]]: ...
