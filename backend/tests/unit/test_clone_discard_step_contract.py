"""Pin the clone "discarded" signal to the two surfaces that decode it.

``EnvironmentClone.cloneErrors`` renders each recorded event as
``f"{entry.step}: {entry.error}"`` and flattens the ``fatal`` flag away, so
"this clone was discarded by deleting the environment it created" is only
recoverable downstream by string-matching the step prefix. Two consumers do
exactly that, each with its own hardcoded copy of the string:

* ``frontend/.../EnvironmentClonesSection.tsx`` — ``DISCARD_STEP_PREFIX``, which
  drives the "Discarded" badge;
* ``backend/tests/e2e/drivers/api_driver.py`` — ``_CLONE_DISCARD_STEP_PREFIX``,
  which is how the API entrypoint reaches the same boolean the UI driver reads
  off ``data-environment-clone-discarded``.

Neither imports :data:`CLONE_STEP_CREATED_ENVIRONMENT_DELETED` (one cannot; the
other is a different language), so renaming the step is a silent, green
breakage: the badge stops appearing and the E2E's discard assertion starts
reading "not discarded" for a clone that was. This test is the missing link —
it fails on the rename instead.

The literals are read out of the files rather than imported so the TypeScript
side is covered by the same assertion as the Python side.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from styrmin_backend.services.backup.clone import (
    CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: ``(path, declaration pattern)`` for every surface that decodes the signal by
#: prefix. The pattern must capture the string literal.
CONSUMERS: tuple[tuple[str, str], ...] = (
    (
        "frontend/src/components/environment/EnvironmentClonesSection.tsx",
        r"""const\s+DISCARD_STEP_PREFIX\s*=\s*["'](?P<literal>[^"']+)["']""",
    ),
    (
        "backend/tests/e2e/drivers/api_driver.py",
        r"""_CLONE_DISCARD_STEP_PREFIX\s*=\s*["'](?P<literal>[^"']+)["']""",
    ),
)


def _expected_prefix() -> str:
    """What ``cloneErrors`` actually emits ahead of the message.

    Mirrors ``EnvironmentClone.clone_errors``' ``f"{entry.step}: {entry.error}"``
    — the consumers match on ``step + ":"``, so the colon belongs to the
    contract, not to the step name.
    """
    return f"{CLONE_STEP_CREATED_ENVIRONMENT_DELETED}:"


@pytest.mark.parametrize(("relative_path", "pattern"), CONSUMERS)
def test_the_discard_prefix_matches_the_step_constant(
    relative_path: str, pattern: str
) -> None:
    path = REPO_ROOT / relative_path
    assert path.is_file(), (
        f"{relative_path} moved; the discard-signal consumer it declares is "
        "now unpinned — point this test at the new location"
    )
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    assert match is not None, (
        f"no discard-prefix declaration found in {relative_path}; if the "
        "consumer stopped string-matching the step, remove it from CONSUMERS"
    )
    assert match.group("literal") == _expected_prefix(), (
        f"{relative_path} decodes the discard signal as "
        f"{match.group('literal')!r}, but the backend writes "
        f"{_expected_prefix()!r} — the 'Discarded' badge and the API driver's "
        "discard flag would silently read false"
    )


def test_the_rendered_event_actually_starts_with_the_pinned_prefix() -> None:
    """Ties the prefix to the renderer, not just to the step name.

    Pinning ``step + ":"`` is only meaningful while ``cloneErrors`` renders
    ``"<step>: <error>"``. If the separator ever changed, every consumer's
    ``startsWith`` would fail while both halves of the test above still agreed.
    """
    from styrmin_backend.api.definitions.backup.environment_clone import (
        EnvironmentClone as EnvironmentCloneType,
    )
    from styrmin_backend.db.models import EnvironmentClone as EnvironmentCloneModel

    model = EnvironmentCloneModel(
        name="prod-rehearsal",
        source_environment_id=None,
        clone_errors=[
            {
                "step": CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
                "error": "the environment this clone created was deleted",
                "fatal": False,
            }
        ],
    )
    rendered = EnvironmentCloneType.from_instance(model).clone_errors()

    assert len(rendered) == 1
    assert rendered[0].startswith(_expected_prefix()), rendered
