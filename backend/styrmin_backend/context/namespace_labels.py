"""The labels of a deployment's namespace."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


NAMESPACE_LABEL_PREFIX = "styrmin"


def build_namespace_labels(
    labels: Mapping[str, Any], label_prefix: str = NAMESPACE_LABEL_PREFIX
) -> dict[str, str]:
    """Build the labels of a namespace from the ``labels`` of a deployment's context.

    Every key gets the prefix, so ``environment_id`` becomes
    ``styrmin/environment_id``. Network policies select namespaces by these
    labels.
    """
    return {f"{label_prefix}/{key}": str(value) for key, value in labels.items()}
