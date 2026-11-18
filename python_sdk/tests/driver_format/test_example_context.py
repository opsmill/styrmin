"""FR-002, FR-005, research R-006 and R-007: the example context of a driver."""

import os
import subprocess  # noqa: S404 - spawns a trusted, fixed-argv child interpreter
import sys
from uuid import UUID

import pytest
from styrmin_sdk.driver_format.context.models.contexts import GlobalContext, UtilityKind
from styrmin_sdk.driver_format.example_context import (
    EXAMPLE_DEPLOYMENT_ID,
    build_example_context,
    example_application_version,
    placeholder_value,
)
from styrmin_sdk.driver_format.models.resources.parameters import DriverParameterDefinition
from styrmin_sdk.driver_format.models.structure.directory import DriverDirectory
from styrmin_sdk.driver_format.reading.files import get_resource_file_loader

from .conftest import EXAMPLES


def _build(name: str):
    spec = get_resource_file_loader(DriverDirectory(EXAMPLES / name).driver_spec).load()
    template = (EXAMPLES / name / "values.j2.yml").read_text(encoding="utf-8")
    return spec, build_example_context(spec, template)


def test_simple_app_context_holds_its_services_components_and_utilities() -> None:
    spec, example = _build("simple-app")
    context = example.context

    GlobalContext.model_validate(context.model_dump(mode="json"))
    dumped = context.model_dump(exclude_none=True)
    for key in ("app", "cluster", "environment", "deployment", "instance", "labels", "parameters", "services"):
        assert key in dumped
    assert set(context.services) == {service.name for service in spec.spec.services}
    assert context.services["simple-app"]["port"] == 8000
    assert set(context.components.root) == {"server", "database"}
    assert [u.kind for u in context.utilities] == [UtilityKind.INGRESS, UtilityKind.SERVICE_DISCOVERY]
    assert context.instance.namespace == f"styrmin-{EXAMPLE_DEPLOYMENT_ID}"
    assert context.app.name == "simple-app"
    assert context.app.helm.chart.values_template == (EXAMPLES / "simple-app" / "values.j2.yml").read_text()


def test_two_builds_give_the_same_context() -> None:
    _spec, first = _build("simple-app")
    _spec, second = _build("simple-app")

    assert first.context.model_dump(mode="json") == second.context.model_dump(mode="json")


def test_a_parameter_without_default_gets_a_placeholder_and_a_warning() -> None:
    _spec, example = _build("generic-app")

    assert example.context.parameters["image_repository"] == "example-image_repository"
    assert example.context.parameters["image_pull_policy"] == "IfNotPresent"
    placeholders = [w for w in example.warnings if "has no default" in w.message]
    assert len(placeholders) == 1
    assert placeholders[0].path[:2] == ("spec", "parameters")


@pytest.mark.parametrize(
    ("kind", "values", "expected"),
    [("string", None, "example-p"), ("integer", None, 0), ("boolean", None, False), ("enum", ["b", "a"], "b")],
)
def test_placeholder_value_by_kind(kind: str, values: list[str] | None, expected: object) -> None:
    definition = DriverParameterDefinition(name="p", label="P", kind=kind, values=values)

    assert placeholder_value(definition) == expected


def test_the_application_version_is_default_version_or_the_lower_bound() -> None:
    _spec, semaphore = _build("semaphore")
    _spec, simple_app = _build("simple-app")

    assert semaphore.context.app.version == "2.16.47"
    assert simple_app.context.app.version == "0.1"
    assert any("no default_version" in w.message for w in simple_app.warnings)
    assert not semaphore.warnings


@pytest.mark.parametrize(
    ("specifier", "expected"),
    [
        (">=0.1,<1.0", "0.1"),
        (">=0", "0"),
        ("==2.3.4", "2.3.4"),
        ("~=1.4", "1.4"),
        ("<2.0", "0.0.0"),
        ("==2.*", "0.0.0"),
    ],
)
def test_example_application_version(specifier: str, expected: str) -> None:
    assert example_application_version(specifier) == expected


@pytest.mark.parametrize(("specifier", "expected"), [(">=1.0,~=1.4,<2", "1.0"), ("~=1.4,>=1.0,<2", "1.4")])
def test_the_application_version_follows_the_written_order_in_every_process(specifier: str, expected: str) -> None:
    code = (
        "from styrmin_sdk.driver_format.example_context import example_application_version; "
        f"print(example_application_version({specifier!r}))"
    )
    results = {
        subprocess.run(  # noqa: S603 - fixed argv, no shell, no untrusted input
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
        ).stdout.strip()
        for seed in range(8)
    }

    assert results == {expected}


def test_labels_use_the_fixed_identifiers() -> None:
    _spec, example = _build("simple-app")

    assert example.context.labels["deployment_id"] == EXAMPLE_DEPLOYMENT_ID
    assert isinstance(example.context.labels["environment_id"], UUID)
