"""Demo 3's registration, the image it deploys, and the checks that fail the demo on a wrong result."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e.demos.catalog import DEMOS
from tests.e2e.demos.scenarios import backup_restore
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import (
    EnvironmentBackupConstituentRef,
    EnvironmentBackupRef,
    EnvironmentRestoreRef,
    EnvironmentRestoreSkipRef,
)

REPOSITORY_ROOT = Path(backup_restore.__file__).parents[5]


def constituent(name: str, outcome: str) -> EnvironmentBackupConstituentRef:
    return EnvironmentBackupConstituentRef(
        deployment_id=f"id-{name}",
        deployment_name=name,
        outcome=outcome,
        backup_id=None,
        backup_status=None,
        error=None,
    )


def backup(status: str, **outcomes: str) -> EnvironmentBackupRef:
    return EnvironmentBackupRef(
        id="backup-1",
        name="network-lab-backup-1",
        status=status,
        constituents=tuple(
            constituent(name, value) for name, value in outcomes.items()
        ),
    )


def test_demo_3_is_registered_with_its_environment() -> None:
    demo = next(demo for demo in DEMOS if demo.slug == "backup-restore")

    assert demo.number == 3
    assert demo.environment_names == ("network-lab-backup",)
    assert demo.setup is backup_restore.setup
    assert demo.record is backup_restore.record


def test_the_semaphore_image_is_the_one_the_record_task_builds() -> None:
    task_source = (REPOSITORY_ROOT / "tasks" / "demo.py").read_text()

    match = re.search(r'^SEMAPHORE_DEMO_IMAGE = "([^"]+)"$', task_source, re.MULTILINE)
    assert match is not None
    image = f"{backup_restore.SEMAPHORE_IMAGE_REPOSITORY}:v{backup_restore.SEMAPHORE_VERSION}"
    assert image == match.group(1)


def test_check_backup_accepts_a_completed_backup_of_both_deployments() -> None:
    backup_restore.check_backup(
        backup("COMPLETED", infrahub="completed", semaphore="completed"),
        ("infrahub", "semaphore"),
    )


@pytest.mark.parametrize(
    "ref",
    [
        backup("PARTIAL", infrahub="completed", semaphore="failed"),
        backup("COMPLETED", infrahub="completed"),
    ],
    ids=["partial", "semaphore-not-in-the-backup"],
)
def test_check_backup_fails_unless_every_deployment_completed(
    ref: EnvironmentBackupRef,
) -> None:
    with pytest.raises(
        ScenarioActionError, match=r"not COMPLETED for infrahub, semaphore"
    ):
        backup_restore.check_backup(ref, ("infrahub", "semaphore"))


def test_check_backup_lists_each_constituent_outcome() -> None:
    with pytest.raises(ScenarioActionError) as raised:
        backup_restore.check_backup(
            backup("PARTIAL", semaphore="failed", infrahub="completed"),
            ("infrahub", "semaphore"),
        )

    assert str(raised.value) == (
        "The environment backup ended PARTIAL, not COMPLETED for infrahub, semaphore "
        "(constituents: infrahub: completed, semaphore: failed)"
    )


def test_check_restore_accepts_a_completed_restore_with_no_skip() -> None:
    backup_restore.check_restore(
        EnvironmentRestoreRef(
            id="r", status="COMPLETED", restore_ids=("a", "b"), skipped=()
        )
    )


def test_check_restore_names_each_skipped_deployment_and_its_reason() -> None:
    skip = EnvironmentRestoreSkipRef(
        deployment_id="id-semaphore",
        deployment_name="semaphore",
        reason="backup deleted",
    )

    with pytest.raises(ScenarioActionError) as raised:
        backup_restore.check_restore(
            EnvironmentRestoreRef(
                id="r", status="PARTIAL", restore_ids=("a",), skipped=(skip,)
            )
        )

    assert str(raised.value) == (
        "The environment restore ended PARTIAL and skipped semaphore (backup deleted)"
    )


def test_check_restore_fails_a_failed_restore() -> None:
    with pytest.raises(
        ScenarioActionError, match=r"^The environment restore ended FAILED$"
    ):
        backup_restore.check_restore(
            EnvironmentRestoreRef(
                id="r", status="FAILED", restore_ids=("a",), skipped=()
            )
        )


def test_check_listed_passes_when_the_list_matches() -> None:
    backup_restore.check_listed(["sw1", "sw2"], "sw2", listed=True, where="Infrahub")
    backup_restore.check_listed(["sw1"], "sw2", listed=False, where="Infrahub")


def test_check_listed_names_what_the_list_shows() -> None:
    with pytest.raises(ScenarioActionError) as missing:
        backup_restore.check_listed(["sw1"], "sw2", listed=True, where="Infrahub")
    with pytest.raises(ScenarioActionError) as still_there:
        backup_restore.check_listed(
            ["List network devices"],
            "List network devices",
            listed=False,
            where="Semaphore",
        )
    with pytest.raises(ScenarioActionError) as empty:
        backup_restore.check_listed(
            [], "List network devices", listed=True, where="Semaphore"
        )

    assert str(missing.value) == "Infrahub does not list 'sw2'; it lists: sw1"
    assert str(still_there.value) == (
        "Semaphore still lists 'List network devices'; it lists: List network devices"
    )
    assert str(empty.value) == (
        "Semaphore does not list 'List network devices'; it lists: nothing"
    )
