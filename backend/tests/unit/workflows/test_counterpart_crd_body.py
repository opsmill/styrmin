"""Unit tests for ``_build_counterpart_crd_body`` (010 research D2.4).

A cross-target restore lands the source's ``StyrminDeployment`` CR — source
name, source identity — inside the counterpart's namespace. This helper is what
produces the body that replaces it. It sits on both sides of a contract nothing
else joined:

* upstream it is ``AsyncMock``-ed in
  ``test_restore_workflow_failure_handler.py``, so what it actually renders was
  never checked there;
* downstream ``test_restore_recovery_cross_target.py`` used to hand-write the
  body it consumes — that fixture now calls this same producer
  (``tests.unit.counterpart_crd_fixtures.build_counterpart_body``).

That is the exact shape of the ``create_restore`` stub that let a real
contradiction ship green in this feature, so the helper is exercised directly
here — including the two ``RuntimeError`` guards, which are the difference
between a failed restore and a namespace left carrying the *source's* identity.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.workflows.templates.backup import _build_counterpart_crd_body

from tests.unit.counterpart_crd_fixtures import (
    COUNTERPART_DEPLOYMENT_ID,
    COUNTERPART_NAMESPACE,
    SOURCE_RELEASE_REFERENCE,
    StubUnitOfWork,
    build_counterpart_body,
    counterpart_deployment,
)


@pytest.mark.anyio
async def test_the_body_is_named_after_the_counterpart_namespace() -> None:
    """research D2: counterpart CR name, source Helm release name.

    The helper reads both strings off the *same* instance context, so a
    builder call that passed ``release_reference`` as the CR name (or read the
    namespace from the wrong place) produces a CR named after the source inside
    the counterpart's namespace — invisible to every other fast test.
    """
    body = await build_counterpart_body()

    assert body["metadata"]["name"] == COUNTERPART_NAMESPACE
    assert body["metadata"]["namespace"] == COUNTERPART_NAMESPACE
    assert body["spec"]["releaseReference"] == SOURCE_RELEASE_REFERENCE
    assert body["spec"]["releaseReference"] != body["metadata"]["name"], (
        "the counterpart fixture must keep the two names distinct"
    )
    assert body["spec"]["deploymentId"] == str(COUNTERPART_DEPLOYMENT_ID)


@pytest.mark.anyio
async def test_the_body_carries_the_deployment_internal_flag() -> None:
    """``internal`` comes off the deployment row, not the context."""
    assert (await build_counterpart_body(internal=True))["spec"]["internal"] is True
    assert (await build_counterpart_body(internal=False))["spec"]["internal"] is False


@pytest.mark.anyio
async def test_a_missing_counterpart_deployment_raises() -> None:
    """Guard 1: without the row there is nothing to rename the namespace to.

    Failing loudly is the point — silently skipping the reapply would leave the
    restored namespace carrying the *source's* CR identity, which the operator
    would then reconcile as the source.
    """
    with pytest.raises(RuntimeError, match="not found"):
        await _build_counterpart_crd_body(
            deployment_id=uuid4(), uow=StubUnitOfWork(None)
        )


@pytest.mark.anyio
async def test_a_counterpart_without_an_active_instance_raises() -> None:
    """Guard 2: the CR body is rendered from the active instance's context."""
    deployment = counterpart_deployment(with_instance=False)
    assert deployment.active_instance is None

    with pytest.raises(RuntimeError, match="no active instance"):
        await _build_counterpart_crd_body(
            deployment_id=deployment.id, uow=StubUnitOfWork(deployment)
        )
