"""``node_selector`` was removed from the config models because no pod ever received it (#472)."""

import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.config import ClusterConfig, DeploymentConfig
from styrmin_backend.context.models.contexts import GlobalContext

from tests.unit.counterpart_crd_fixtures import make_context


@pytest.mark.parametrize("model", [ClusterConfig, DeploymentConfig])
def test_config_models_reject_node_selector(model: type) -> None:
    with pytest.raises(ValidationError, match="node_selector"):
        model(node_selector="pool=apps")


def test_stored_context_with_node_selector_still_loads() -> None:
    """A StyrminDeployment written before the removal keeps the key in ``spec.context``."""
    context = make_context(
        deployment_id=uuid4(), namespace="styrmin-a", release_reference="styrmin-a"
    )
    stored = context.model_dump(mode="json", exclude_none=True)
    for scope in ("cluster", "deployment", "instance"):
        stored[scope]["config"]["node_selector"] = "pool=apps"
    original = copy.deepcopy(stored)

    loaded = GlobalContext.model_validate(stored)

    assert loaded == context
    assert stored == original
