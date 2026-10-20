"""Demo 4's registration, the image it deploys, and the checks that fail the demo on a wrong result."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e.demos.catalog import DEMOS
from tests.e2e.demos.scenarios import clone
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import (
    EnvironmentCloneDeploymentResultRef,
    EnvironmentCloneRef,
)

REPOSITORY_ROOT = Path(clone.__file__).parents[5]

# The end of a Semaphore task log of demos/semaphore/ansible/list_hosts.yml, after strip_ansi.
LOG = """\
TASK [Print the devices in the inventory] **************************************
ok: [sw1] => {
    "msg": [
        "Devices in the inventory: 2",
        "Device names: sw1, sw2"
    ]
}

PLAY RECAP *********************************************************************
sw1                        : ok=1    changed=0    unreachable=0    failed=0
"""


def result(
    name: str, outcome: str, counterpart: str | None = None, reason: str | None = None
) -> EnvironmentCloneDeploymentResultRef:
    return EnvironmentCloneDeploymentResultRef(
        deployment_id=f"id-{name}",
        deployment_name=name,
        outcome=outcome,
        reason=reason,
        counterpart_deployment_id=counterpart,
        restore_id=None,
    )


def clone_ref(
    status: str,
    *results: EnvironmentCloneDeploymentResultRef,
    errors: tuple[str, ...] = (),
) -> EnvironmentCloneRef:
    return EnvironmentCloneRef(
        id="clone-1",
        name="network-lab-clone",
        status=status,
        created_environment_id="env-clone",
        environment_backup_id="backup-1",
        discarded=False,
        deployment_results=results,
        clone_errors=errors,
    )


def test_demo_4_is_registered_with_the_clone_first() -> None:
    demo = next(demo for demo in DEMOS if demo.slug == "clone")

    assert demo.number == 4
    assert demo.environment_names == ("network-lab-clone", "network-lab")
    assert demo.setup is clone.setup
    assert demo.record is clone.record


def test_the_semaphore_image_is_the_one_the_record_task_builds() -> None:
    task_source = (REPOSITORY_ROOT / "tasks" / "demo.py").read_text()

    match = re.search(r'^SEMAPHORE_DEMO_IMAGE = "([^"]+)"$', task_source, re.MULTILINE)
    assert match is not None
    image = f"{clone.SEMAPHORE_IMAGE_REPOSITORY}:v{clone.SEMAPHORE_VERSION}"
    assert image == match.group(1)


def test_the_count_pattern_matches_the_line_the_playbook_prints() -> None:
    playbook = (
        REPOSITORY_ROOT / "backend/tests/e2e/demos/semaphore/ansible/list_hosts.yml"
    ).read_text()

    assert "Devices in the inventory: {{ groups['all'] | length }}" in playbook


def test_device_count_reads_the_count_of_the_playbook_output() -> None:
    assert clone.device_count(LOG) == 2
    assert clone.device_count(LOG.replace(": 2", ": 13")) == 13


def test_device_count_names_a_log_without_a_count_and_shows_its_last_lines() -> None:
    log = "PLAY [List the network devices] ****\nskipping: no hosts matched\n"

    with pytest.raises(ScenarioActionError) as raised:
        clone.device_count(log)

    assert str(raised.value) == (
        "The Semaphore task output gives no device count. Last lines of its log:\n"
        "PLAY [List the network devices] ****\nskipping: no hosts matched"
    )


def test_device_count_refuses_two_different_counts() -> None:
    log = LOG + LOG.replace(": 2", ": 3")

    with pytest.raises(
        ScenarioActionError, match=r"gives several device counts \[2, 3\]"
    ):
        clone.device_count(log)


def test_check_device_count_names_where_the_count_was_wrong() -> None:
    clone.check_device_count(LOG, 2, where="The source Semaphore")

    with pytest.raises(ScenarioActionError) as raised:
        clone.check_device_count(LOG, 3, where="The clone's Semaphore")

    assert str(raised.value) == (
        "The clone's Semaphore lists 2 devices in its inventory, not 3"
    )


def test_check_clone_returns_the_counterpart_of_each_deployment() -> None:
    ref = clone_ref(
        "COMPLETED",
        result("infrahub", "CLONED", "c-infrahub"),
        result("semaphore", "CLONED", "c-semaphore"),
    )

    assert clone.check_clone(ref, ("infrahub", "semaphore")) == {
        "infrahub": "c-infrahub",
        "semaphore": "c-semaphore",
    }


@pytest.mark.parametrize(
    "ref",
    [
        clone_ref(
            "PARTIAL",
            result("infrahub", "CLONED", "c-infrahub"),
            result("semaphore", "FAILED", reason="restore failed"),
        ),
        clone_ref("COMPLETED", result("infrahub", "CLONED", "c-infrahub")),
        clone_ref(
            "COMPLETED",
            result("infrahub", "CLONED", "c-infrahub"),
            result("semaphore", "CLONED"),
        ),
    ],
    ids=["partial", "semaphore-not-cloned", "no-counterpart"],
)
def test_check_clone_fails_unless_every_deployment_was_cloned(
    ref: EnvironmentCloneRef,
) -> None:
    with pytest.raises(
        ScenarioActionError, match=r"not COMPLETED with infrahub, semaphore cloned"
    ):
        clone.check_clone(ref, ("infrahub", "semaphore"))


def test_check_clone_lists_each_outcome_its_reason_and_the_clone_errors() -> None:
    ref = clone_ref(
        "PARTIAL",
        result("semaphore", "FAILED", reason="restore failed"),
        result("infrahub", "CLONED", "c-infrahub"),
        errors=("restore: timed out",),
    )

    with pytest.raises(ScenarioActionError) as raised:
        clone.check_clone(ref, ("infrahub", "semaphore"))

    assert str(raised.value) == (
        "The environment clone ended PARTIAL, not COMPLETED with infrahub, semaphore "
        "cloned (deployments: infrahub: CLONED, semaphore: FAILED (restore failed)); "
        "errors: restore: timed out"
    )
