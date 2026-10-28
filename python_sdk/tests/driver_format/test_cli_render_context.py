"""User story 2: ``render`` writes only the Helm values; ``context`` writes the example context."""

from pathlib import Path

import yaml
from styrmin_sdk.driver_format.context.models.contexts import GlobalContext

from .conftest import EXAMPLES


def test_render_writes_only_the_values_to_standard_output(run_cli) -> None:
    result = run_cli("render", str(EXAMPLES / "generic-app"))

    values = yaml.safe_load(result.out)
    assert result.code == 0
    assert isinstance(values, dict)
    assert yaml.safe_dump(values, sort_keys=False, default_flow_style=False) == result.out
    assert "warning:" in result.err


def test_render_with_an_undefined_variable_writes_nothing_to_standard_output(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text("a: '{{ parameters.missing }}'\n")

    result = run_cli("render", str(driver))

    assert result.code == 1
    assert not result.out
    assert "error: undefined variable 'parameters.missing'" in result.err


def test_render_does_not_check_actions(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "actions.py").write_text("")

    assert run_cli("render", str(driver)).code == 0
    assert run_cli("check", str(driver)).code == 1


def test_context_writes_yaml_that_validates_against_the_context_model(run_cli) -> None:
    result = run_cli("context", str(EXAMPLES / "simple-app"))

    data = yaml.safe_load(result.out)
    assert result.code == 0
    GlobalContext.model_validate(data)
    assert set(data["services"]) == {"simple-app"}
    assert data["parameters"] == {}


def test_context_of_generic_app_holds_the_parameter_defaults_and_a_placeholder(run_cli) -> None:
    result = run_cli("context", str(EXAMPLES / "generic-app"))

    data = yaml.safe_load(result.out)
    assert data["parameters"]["health_path"] == ""  # noqa: PLC1901 - the default is exactly the empty string
    assert data["parameters"]["image_repository"] == "example-image_repository"
    assert "parameter 'image_repository' has no default" in result.err


def test_check_with_a_context_file_renders_with_it(example_copy, tmp_path: Path, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text("a: '{{ parameters.extra }}'\n")
    context = tmp_path / "ctx.yml"
    context.write_text("parameters:\n  extra: 'set'\n")

    without = run_cli("check", str(driver))
    with_file = run_cli("check", str(driver), "--context", str(context))

    assert without.code == 1
    assert with_file.code == 0
