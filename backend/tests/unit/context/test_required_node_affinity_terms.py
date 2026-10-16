"""A required node affinity term without expressions is rejected on save (#496).

Such a term renders as no node selector term (the pods run on any node) or an
empty one (no node matches it). Saving an environment or deployment config that
holds one fails with an error that names the term; configs stored before #496
still load, resolve and render.
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.context.exceptions import (
    InvalidDeploymentContextError,
    InvalidEnvironmentContextError,
)
from styrmin_backend.context.models.config import DeploymentConfig, EnvironmentConfig
from styrmin_backend.context.resolvers import _resolve_scheduling_config
from styrmin_backend.context.validators import (
    validate_deployment_config,
    validate_environment_config,
)
from styrmin_backend.services.context import _extract_scheduling
from styrmin_backend.services.scheduling.patch_builder import (
    build_node_affinity_patches,
)

VALIDATORS = (
    (validate_environment_config, InvalidEnvironmentContextError),
    (validate_deployment_config, InvalidDeploymentContextError),
)

TERMS_WITHOUT_EXPRESSIONS = {
    "empty label selector": {"label_selector": {}},
    "empty match_expressions": {"label_selector": {"match_expressions": []}},
    "empty match_labels": {"label_selector": {"match_labels": {}}},
    "both empty": {"label_selector": {"match_expressions": [], "match_labels": {}}},
    "deployment_ref": {"deployment_ref": {"deployment_name": "api"}},
}

TERM_WITH_EXPRESSION = {
    "topology_key": "",
    "label_selector": {
        "match_expressions": [{"key": "pool", "operator": "In", "values": ["apps"]}]
    },
}

ERROR = (
    "a required node affinity term must set at least one entry in "
    "label_selector.match_expressions or label_selector.match_labels"
)


def _node_affinity(required: list[dict[str, Any]], **block: Any) -> dict[str, Any]:
    return {"scheduling": {"node_affinity": {"required": required, **block}}}


def _validator_id(value: Any) -> str:
    return getattr(value, "__name__", str(value))


@pytest.mark.parametrize(("validate", "error_type"), VALIDATORS, ids=_validator_id)
@pytest.mark.parametrize(
    "selector", TERMS_WITHOUT_EXPRESSIONS.values(), ids=TERMS_WITHOUT_EXPRESSIONS
)
def test_save_rejects_required_term_without_expressions(
    validate: Any, error_type: type[Exception], selector: dict[str, Any]
) -> None:
    config = _node_affinity([TERM_WITH_EXPRESSION, {"topology_key": "", **selector}])

    with pytest.raises(error_type) as excinfo:
        validate(config)

    assert str(excinfo.value) == f"scheduling.node_affinity.required.1: {ERROR}"


@pytest.mark.parametrize(("validate", "error_type"), VALIDATORS, ids=_validator_id)
def test_error_names_every_term_without_expressions(
    validate: Any, error_type: type[Exception]
) -> None:
    empty = {"topology_key": "", "label_selector": {}}
    config = _node_affinity([empty, TERM_WITH_EXPRESSION, empty])

    with pytest.raises(error_type) as excinfo:
        validate(config)

    assert str(excinfo.value) == (
        f"scheduling.node_affinity.required.0: {ERROR}; "
        f"scheduling.node_affinity.required.2: {ERROR}"
    )


@pytest.mark.parametrize(
    "validate", [validate for validate, _ in VALIDATORS], ids=_validator_id
)
@pytest.mark.parametrize(
    "config",
    [
        _node_affinity([TERM_WITH_EXPRESSION]),
        _node_affinity(
            [{"topology_key": "", "label_selector": {"match_labels": {"pool": "apps"}}}]
        ),
        _node_affinity([], replace=True),
        # Preferred node affinity terms and pod affinity terms are out of scope.
        {
            "scheduling": {
                "node_affinity": {
                    "preferred": [
                        {
                            "weight": 1,
                            "term": {"topology_key": "", "label_selector": {}},
                        }
                    ]
                }
            }
        },
        {
            "scheduling": {
                "pod_affinity": {
                    "required": [
                        {"topology_key": "kubernetes.io/hostname", "label_selector": {}}
                    ]
                }
            }
        },
    ],
    ids=[
        "match_expressions",
        "match_labels",
        "replace without terms",
        "preferred term",
        "pod affinity term",
    ],
)
def test_save_accepts(validate: Any, config: dict[str, Any]) -> None:
    validate(config)


@pytest.mark.parametrize("level", ["environment", "deployment"])
@pytest.mark.parametrize(
    "selector", TERMS_WITHOUT_EXPRESSIONS.values(), ids=TERMS_WITHOUT_EXPRESSIONS
)
def test_stored_config_still_loads_resolves_and_renders(
    level: str, selector: dict[str, Any]
) -> None:
    stored = _node_affinity([{"topology_key": "", **selector}])
    model = EnvironmentConfig if level == "environment" else DeploymentConfig

    model.model_validate(stored)
    scheduling = _extract_scheduling(stored, path=f"{level}.config.scheduling")
    resolved, _ = _resolve_scheduling_config(
        env=scheduling if level == "environment" else None,
        dep=scheduling if level == "deployment" else None,
        comp=None,
    )

    assert resolved.node_affinity is not None
    assert len(resolved.node_affinity.required) == 1
    assert build_node_affinity_patches(resolved)
