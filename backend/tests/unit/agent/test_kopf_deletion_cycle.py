"""kopf removes a deleted StyrminDeployment's finalizer once the CR's timer run ends (#446, #461).

These tests run kopf's own event processing with the agent's kopf settings and delete handler.
The fix depends on how kopf waits for a timer run, which is private kopf behaviour, so a kopf
upgrade that changes it fails here. Patches and sleeps are recorded instead of sent or slept.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import kopf
import pytest
from kopf._cogs.structs import ephemera, references
from kopf._core.actions import application, lifecycles
from kopf._core.engines import indexing
from kopf._core.reactor import inventory, processing
from pytest_mock import MockerFixture

from styrmin_backend.entrypoint import combined
from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION
from styrmin_backend.operator.crd.schema import DeploymentPhase
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module

FINALIZER = "styrmin.io/kopf-finalizer"
TOUCH_ANNOTATION = "styrmin.io/touch-dummy"
RESOURCE = references.Resource(
    group=CRD_GROUP,
    version=CRD_VERSION,
    plural=CRD_PLURAL,
    kind="StyrminDeployment",
    namespaced=True,
)


class _Operator:
    """Runs kopf's event processing for one CR and records what kopf sends."""

    def __init__(self, settings: kopf.OperatorSettings, mocker: MockerFixture) -> None:
        self.settings = settings
        self.registry = kopf.OperatorRegistry()
        self.memories = inventory.ResourceMemories()
        self.timer_run_started = asyncio.Event()
        self.timer_run_may_end = asyncio.Event()
        self.patches: list[kopf.Patch] = []
        self.sleeps: list[float] = []

        @kopf.timer(
            CRD_GROUP, CRD_VERSION, CRD_PLURAL, interval=3600, registry=self.registry
        )
        async def slow_timer(**_: Any) -> None:
            self.timer_run_started.set()
            await self.timer_run_may_end.wait()

        kopf.on.delete(CRD_GROUP, CRD_VERSION, CRD_PLURAL, registry=self.registry)(
            handlers_module.kopf_on_styrmin_deployment_delete
        )
        mocker.patch.object(handlers_module, "_teardown_owned_resources", autospec=True)
        mocker.patch.object(application, "patch_and_check", self._patch_and_check)
        mocker.patch.object(application.aiotime, "sleep", self._sleep)

    async def _patch_and_check(
        self, *, patch: kopf.Patch, **_: Any
    ) -> tuple[None, None]:
        self.patches.append(copy.deepcopy(patch))
        return None, None

    async def _sleep(self, delay: float, **_: Any) -> None:
        self.sleeps.append(delay)

    async def process(self, body: dict[str, Any]) -> None:
        """Run one kopf processing cycle for a watch event that carries ``body``."""
        self.patches.clear()
        self.sleeps.clear()
        await processing.process_resource_event(
            lifecycle=lifecycles.all_at_once,
            indexers=indexing.OperatorIndexers(),
            registry=self.registry,
            settings=self.settings,
            memories=self.memories,
            memobase=ephemera.AnyMemo(kopf.Memo()),
            resource=RESOURCE,
            raw_event={"type": "MODIFIED", "object": copy.deepcopy(body)},
            event_queue=asyncio.Queue(),
            no_throttling=True,
        )

    async def end_timer_run(self, body: dict[str, Any]) -> None:
        self.timer_run_may_end.set()
        memory = await self.memories.recall(body)
        await asyncio.wait(
            [d.task for d in memory.daemons_memory.running_daemons.values()]
        )

    def finalizers_after_patches(self, body: dict[str, Any]) -> list[str]:
        patched = copy.deepcopy(body)
        for patch in self.patches:
            for fn in patch.fns:
                fn(patched)
        return patched.get("metadata", {}).get("finalizers", [])

    def touched(self) -> bool:
        return any(
            TOUCH_ANNOTATION in patch.get("metadata", {}).get("annotations", {})
            for patch in self.patches
        )


def _cr(*, phase: DeploymentPhase, deleted: bool = False) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": "dep-1",
        "namespace": "styrmin-abc",
        "uid": "uid-1",
        "finalizers": [FINALIZER],
        "annotations": {
            "styrmin.io/kopf-managed": "yes",
            "kopf.zalando.org/last-handled-configuration": '{"spec":{}}\n',
        },
    }
    if deleted:
        metadata["deletionTimestamp"] = "2026-10-15T00:00:00Z"
    return {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "StyrminDeployment",
        "metadata": metadata,
        "spec": {},
        "status": {"phase": phase.value},
    }


async def _agent_settings() -> kopf.OperatorSettings:
    settings = kopf.OperatorSettings()
    await combined.on_startup(settings=settings)
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kopf_default_polling", "expected_delay"),
    [(True, 60), (False, combined.TIMER_EXIT_POLLING_SECONDS)],
)
async def test_kopf_checks_the_timer_run_again_until_it_ends(
    mocker: MockerFixture, kopf_default_polling: bool, expected_delay: float
) -> None:
    settings = await _agent_settings()
    if kopf_default_polling:
        settings.background.cancellation_polling = (
            kopf.OperatorSettings().background.cancellation_polling
        )
    operator = _Operator(settings, mocker)
    await operator.process(_cr(phase=DeploymentPhase.READY))
    await asyncio.wait_for(operator.timer_run_started.wait(), timeout=5)

    # The namespace deletion deletes the CR during the timer run.
    await operator.process(_cr(phase=DeploymentPhase.READY, deleted=True))
    assert (
        operator.patches[0].get("status", {}).get("phase")
        == DeploymentPhase.DELETING.value
    )
    assert operator.finalizers_after_patches(_cr(phase=DeploymentPhase.READY)) == [
        FINALIZER
    ]

    # The event of that patch: the handler runs again and changes nothing, so kopf sleeps and
    # then touches the CR, whose event starts the next check.
    deleting = _cr(phase=DeploymentPhase.DELETING, deleted=True)
    deleting["status"]["message"] = "Cleaning up resources"
    await operator.process(deleting)
    assert operator.sleeps == [expected_delay]
    assert operator.touched()
    assert operator.finalizers_after_patches(deleting) == [FINALIZER]

    await operator.end_timer_run(deleting)
    await operator.process(deleting)
    assert operator.finalizers_after_patches(deleting) == []


@pytest.mark.asyncio
async def test_a_restarted_agent_removes_the_finalizer_an_earlier_agent_kept(
    mocker: MockerFixture,
) -> None:
    """A new agent process has no timer run for the CR, so the first check removes the finalizer."""
    operator = _Operator(await _agent_settings(), mocker)
    stuck = _cr(phase=DeploymentPhase.DELETING, deleted=True)

    await operator.process(stuck)

    assert operator.finalizers_after_patches(stuck) == []
