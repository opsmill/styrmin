"""Demo 2's registration and the Semaphore image it sets as an override (FR-015)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e.demos.catalog import DEMOS
from tests.e2e.demos.scenarios import component_overrides
from tests.e2e.drivers.errors import ScenarioActionError

DEMOS_DIRECTORY = Path(component_overrides.__file__).parents[1]
REPOSITORY_ROOT = DEMOS_DIRECTORY.parents[3]


def test_demo_2_is_registered_with_its_environment() -> None:
    demo = next(demo for demo in DEMOS if demo.slug == "component-overrides")

    assert demo.number == 2
    assert demo.environment_names == ("network-lab-overrides",)
    assert demo.setup is component_overrides.setup
    assert demo.record is component_overrides.record


def test_the_override_image_is_the_one_the_record_task_builds() -> None:
    task_source = (REPOSITORY_ROOT / "tasks" / "demo.py").read_text()

    match = re.search(r'^SEMAPHORE_DEMO_IMAGE = "([^"]+)"$', task_source, re.MULTILINE)
    assert match is not None
    assert component_overrides.SEMAPHORE_IMAGE == match.group(1)


def test_the_image_is_built_on_the_semaphore_version_the_setup_deploys() -> None:
    dockerfile = (DEMOS_DIRECTORY / "semaphore" / "Dockerfile").read_text()

    assert (
        f"FROM semaphoreui/semaphore:v{component_overrides.SEMAPHORE_VERSION}\n"
        in dockerfile
    )


def test_check_override_accepts_a_row_that_shows_the_value() -> None:
    component_overrides.check_override(
        "server\nimage\nstyrmin-demo/semaphore:v2.16.47\napplied",
        "styrmin-demo/semaphore:v2.16.47",
        deployment="semaphore",
    )


def test_check_override_names_the_deployment_and_what_the_row_shows() -> None:
    with pytest.raises(ScenarioActionError) as raised:
        component_overrides.check_override(
            "server\n  replicas\n1 (driver default)",
            "2 (override)",
            deployment="infrahub",
        )

    assert str(raised.value) == (
        "The server row of infrahub shows 'server replicas 1 (driver default)', "
        "not '2 (override)'"
    )
