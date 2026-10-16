"""A cluster config does not take ``scheduling``, because no pod gets the cluster's value (#482)."""

import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import GlobalContext

from tests.unit.counterpart_crd_fixtures import make_context

TOLERATION = {"tolerations": [{"key": "dedicated", "operator": "Exists"}]}


@pytest.mark.parametrize("scheduling", [TOLERATION, {}], ids=["toleration", "empty"])
def test_cluster_config_rejects_scheduling(scheduling: dict) -> None:
    with pytest.raises(ValidationError, match="environment or the deployment"):
        ClusterConfig.model_validate({"scheduling": scheduling})


def test_cluster_config_accepts_null_scheduling() -> None:
    assert ClusterConfig.model_validate({"scheduling": None}).scheduling is None


@pytest.mark.parametrize("model", [DeploymentConfig, ResolvedConfig])
def test_configs_that_inherit_cluster_config_take_scheduling(model: type) -> None:
    assert model.model_validate({"scheduling": TOLERATION}).scheduling is not None


def test_stored_context_with_cluster_scheduling_still_loads() -> None:
    """A StyrminDeployment written before #482 can keep the cluster value in ``spec.context``."""
    context = make_context(
        deployment_id=uuid4(), namespace="styrmin-a", release_reference="styrmin-a"
    )
    stored = context.model_dump(mode="json", exclude_none=True)
    stored["cluster"]["config"]["scheduling"] = TOLERATION
    stored["instance"]["config"]["scheduling"] = TOLERATION
    original = copy.deepcopy(stored)

    loaded = GlobalContext.model_validate(stored)

    assert loaded.cluster.config.scheduling is None
    assert loaded.instance.config.scheduling is not None
    assert stored == original
