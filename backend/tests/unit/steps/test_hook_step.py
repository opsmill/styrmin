"""Unit tests for ``hook_step`` (spec 029, T008).

A missing action registration is recorded on the step of its hook and mode,
so ``hook_step`` must give the step that users view for each pair.
"""

import pytest

from styrmin_backend.domain import steps
from styrmin_backend.domain.models import StepKind
from styrmin_backend.services.driver.models.resources.actions import HookKind


@pytest.mark.parametrize(
    ("hook", "mode", "expected"),
    [
        (HookKind.SETUP, "pre", steps.SETUP_PRE_HOOK),
        (HookKind.SETUP, "post", steps.SETUP_POST_HOOK),
        (HookKind.UPGRADE, "pre", steps.UPGRADE_PRE_HOOK),
        (HookKind.UPGRADE, "core", steps.UPGRADE_CORE_HOOK),
        (HookKind.UPGRADE, "post", steps.UPGRADE_POST_HOOK),
    ],
    ids=["setup-pre", "setup-post", "upgrade-pre", "upgrade-core", "upgrade-post"],
)
def test_hook_step_returns_the_step_of_the_hook_and_mode(
    hook: HookKind, mode: str, expected: steps.StepDefinition
) -> None:
    step = steps.hook_step(hook, mode)

    assert step == expected
    assert step.key == f"hook:{hook.value}:{mode}"
    assert step.kind == StepKind.HOOK


@pytest.mark.parametrize(
    ("hook", "mode"),
    [
        (HookKind.SETUP, "core"),
        (HookKind.UPGRADE, "sideways"),
        (HookKind.SETUP, ""),
    ],
    ids=["setup-core", "unknown-mode", "empty-mode"],
)
def test_hook_step_raises_for_a_pair_without_a_step(hook: HookKind, mode: str) -> None:
    with pytest.raises(ValueError, match=f"{hook.value} hook, mode {mode}"):
        steps.hook_step(hook, mode)
