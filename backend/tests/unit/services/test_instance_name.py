"""A new instance gets a generated name that no stored instance has (#499).

Instance names are unique across all deployments, and a generated two-word
name can repeat, so the name is checked against the stored instances.
"""

from itertools import chain, repeat

import pytest

from styrmin_backend.services import reconciliation
from styrmin_backend.services.exceptions import InstanceNameUnavailableError
from styrmin_backend.services.reconciliation import generate_instance_from_deployment
from tests.unit.services.cluster_fanout_support import build_graph, deploy


async def test_new_instance_skips_a_name_already_in_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = build_graph()
    deployment = await deploy(graph, graph.env_a, "web")
    stored = deployment.active_instance
    assert stored is not None
    await graph.uow.instances.create(stored)
    names = chain([stored.name, "calm-otter"], repeat("other-name"))
    monkeypatch.setattr(reconciliation, "generate_instance_name", lambda: next(names))

    instance = await generate_instance_from_deployment(
        deployment=deployment, uow=graph.uow
    )

    assert instance.name == "calm-otter"


async def test_new_instance_fails_with_a_typed_error_when_every_name_is_in_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = build_graph()
    deployment = await deploy(graph, graph.env_a, "web")
    stored = deployment.active_instance
    assert stored is not None
    await graph.uow.instances.create(stored)
    monkeypatch.setattr(reconciliation, "generate_instance_name", lambda: stored.name)

    with pytest.raises(InstanceNameUnavailableError):
        await generate_instance_from_deployment(deployment=deployment, uow=graph.uow)
