"""User story 1: ``check`` reports the errors it finds with their file and line (FR-001, FR-007 to FR-010, FR-012)."""

import os
from pathlib import Path

import pytest

from .conftest import edit_spec


def _insert_template_line(driver: Path, line_number: int, text: str) -> None:
    path = driver / "values.j2.yml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines.insert(line_number - 1, text + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _rename_upgrade_function(data: dict) -> None:
    for action in data["spec"]["actions"]:
        if action["name"] == "upgrade":
            action["location"] = "actions.py::upgrade_missing"


def _spec_line(driver: Path, text: str) -> int:
    for number, line in enumerate((driver / "driver.styrmin.yml").read_text().splitlines(), start=1):
        if text in line:
            return number
    raise AssertionError(text)


def test_undefined_variable_on_line_12_names_the_file_the_line_and_the_variable(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    _insert_template_line(driver, 12, "# admin: {{ parameters.admn_email }}")

    result = run_cli("check", str(driver))

    assert f"{driver}/values.j2.yml:12: error: undefined variable 'parameters.admn_email'\n" in result.out
    assert result.code == 1


def test_missing_action_function_names_the_line_of_its_location(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    edit_spec(driver, _rename_upgrade_function)
    line = _spec_line(driver, "actions.py::upgrade_missing")

    result = run_cli("check", str(driver))

    assert (
        f"{driver}/driver.styrmin.yml:{line}: error: Missing entrypoint for action upgrade: upgrade_missing\n"
        in result.out
    )
    assert result.code == 1


def test_both_errors_are_reported_in_one_run_and_the_fixed_driver_passes(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    original_template = (driver / "values.j2.yml").read_text()
    original_spec = (driver / "driver.styrmin.yml").read_text()
    _insert_template_line(driver, 12, "# admin: {{ parameters.admn_email }}")
    edit_spec(driver, _rename_upgrade_function)

    broken = run_cli("check", str(driver))
    (driver / "values.j2.yml").write_text(original_template)
    (driver / "driver.styrmin.yml").write_text(original_spec)
    fixed = run_cli("check", str(driver))

    assert broken.out.count(" error: ") == 2
    assert broken.out.endswith(f"{driver}: 2 errors, 1 warning\n")
    assert broken.code == 1
    assert fixed.code == 0


def test_an_invalid_field_and_a_missing_action_function_are_reported_together(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")

    def change(data: dict) -> None:
        data["spec"]["info"]["license"] = 1
        _rename_upgrade_function(data)

    edit_spec(driver, change)

    result = run_cli("check", str(driver))

    assert "error: spec.info.license: Input should be a valid string (found 1)" in result.out
    assert "error: Missing entrypoint for action upgrade: upgrade_missing" in result.out
    assert result.out.count(" error: ") == 2
    assert result.code == 1


def test_errors_of_the_checks_across_fields_do_not_stop_the_render(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")

    def change(data: dict) -> None:
        data["spec"]["components"]["database"]["backup"] = {"enabled": True, "kind": "action"}
        data["spec"]["env_vars"][1]["components"] = ["ghost"]

    edit_spec(driver, change)
    _insert_template_line(driver, 12, "# admin: {{ parameters.admn_email }}")

    result = run_cli("check", str(driver))

    assert "error: Component 'database': action backup requires action hooks" in result.out
    assert "error: env var doc 'DB_POOL_SIZE' references component 'ghost'" in result.out
    assert f"{driver}/values.j2.yml:12: error: undefined variable 'parameters.admn_email'\n" in result.out
    assert result.out.count(" error: ") == 3
    assert result.code == 1


def test_every_invalid_field_is_reported_on_its_own_line(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")

    def change(data: dict) -> None:
        data["spec"]["info"]["license"] = 1
        data["spec"]["info"]["authors"] = "fatih"

    edit_spec(driver, change)

    result = run_cli("check", str(driver))

    assert (
        f"{driver}/driver.styrmin.yml:{_spec_line(driver, 'authors:')}: error: "
        "spec.info.authors: Input should be a valid list (found 'fatih')\n" in result.out
    )
    assert (
        f"{driver}/driver.styrmin.yml:{_spec_line(driver, 'license:')}: error: "
        "spec.info.license: Input should be a valid string (found 1)\n" in result.out
    )


@pytest.mark.parametrize(
    ("template", "line", "message"),
    [
        ("a: 1\nb: 2\nc: {{ wrong\n", 3, "unexpected end of template, expected 'end of print statement'."),
        ("a: 1\n{% if x %}\nb: 2\n", 2, "Unexpected end of template. Jinja was looking for the following tags:"),
    ],
    ids=["unclosed expression", "unclosed if"],
)
def test_template_syntax_error_names_the_file_and_the_line(
    template: str, line: int, message: str, example_copy, run_cli
) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text(template)

    result = run_cli("check", str(driver))

    assert f"{driver}/values.j2.yml:{line}: error: {message}" in result.out
    assert result.code == 1


def test_retired_filter_is_reported_with_its_line_and_the_load_message(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    _insert_template_line(driver, 2, "# {{ components | component_command }}")

    result = run_cli("check", str(driver))

    assert (
        f"{driver}/values.j2.yml:2: error: values.j2.yml line 2 calls the 'component_command' template filter"
        in result.out
    )
    assert result.code == 1


def test_actions_file_syntax_error_is_reported_with_its_line(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "actions.py").write_text("def upgrade(:\n    pass\n")

    result = run_cli("check", str(driver))

    assert f"{driver}/actions.py:1: error: invalid Python:" in result.out
    assert result.code == 1


def test_invalid_icon_is_a_warning_and_the_exit_code_is_zero(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    edit_spec(driver, lambda data: data["spec"]["info"].update({"icon": "http://example.com/logo.png"}))

    result = run_cli("check", str(driver))

    assert f"{driver}/driver.styrmin.yml:{_spec_line(driver, 'icon:')}: warning: " in result.out
    assert "The icon was not stored." in result.out
    assert result.code == 0


def test_directory_without_driver_spec_file_exits_with_1(tmp_path: Path, run_cli) -> None:
    result = run_cli("check", str(tmp_path))

    assert f"{tmp_path}/driver.styrmin.yml: error: The driver specification file could not be found:" in result.out
    assert result.code == 1


def test_path_that_does_not_exist_exits_with_2(tmp_path: Path, run_cli) -> None:
    result = run_cli("check", str(tmp_path / "nowhere"))

    assert result.code == 2
    assert "the driver directory does not exist" in result.err
    assert not result.out


def test_rendered_text_that_is_not_yaml_exits_with_1(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text("key: [unclosed\n")

    result = run_cli("check", str(driver))

    assert "error: The chart values are not valid YAML:" in result.out
    assert result.code == 1


def test_yaml_syntax_error_in_the_driver_spec_file_names_its_line(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "driver.styrmin.yml").write_text("apiVersion: styrmin.io/v1\nkind: [unclosed\n")

    result = run_cli("check", str(driver))

    assert f"{driver}/driver.styrmin.yml:3: error: Error while parsing the driver resource file:" in result.out
    assert result.code == 1


def test_a_template_that_is_not_utf8_is_an_error_with_its_line(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_bytes(b"a: 1\nb: \xff\n")

    result = run_cli("check", str(driver))

    assert f"{driver}/values.j2.yml:2: error: The file is not valid UTF-8:" in result.out
    assert result.code == 1
    assert not result.err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_a_template_that_cannot_be_read_is_an_error(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    template = driver / "values.j2.yml"
    template.chmod(0)
    try:
        result = run_cli("check", str(driver))
    finally:
        template.chmod(0o644)

    assert f"{driver}/values.j2.yml: error: The file cannot be read:" in result.out
    assert result.code == 1


def test_a_render_failure_is_an_error_with_its_line_and_the_undefined_uses_before_it(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text("a: '{{ parameters.typo }}'\nb: '{{ 1 + \"x\" }}'\n")

    result = run_cli("check", str(driver))

    assert f"{driver}/values.j2.yml:1: error: undefined variable 'parameters.typo'\n" in result.out
    assert f"{driver}/values.j2.yml:2: error: Chart values template rendering failed: TypeError:" in result.out
    assert result.code == 1
    assert not result.err


def test_a_missing_action_function_names_its_own_line_when_another_action_is_invalid(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")

    def change(data: dict) -> None:
        data["spec"]["actions"][0] = {"name": "broken", "hook": "upgrade"}
        data["spec"]["actions"][1]["location"] = "actions.py::gone"

    edit_spec(driver, change)
    line = _spec_line(driver, "actions.py::gone")

    result = run_cli("check", str(driver))

    assert f"{driver}/driver.styrmin.yml:{line}: error: Missing entrypoint for action pre_setup: gone\n" in result.out


def test_a_template_that_is_not_rendered_because_of_spec_errors_says_so(example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    edit_spec(driver, lambda data: data["spec"].update(version=1))

    result = run_cli("check", str(driver))

    assert (
        f"{driver}/values.j2.yml: warning: not rendered, because driver.styrmin.yml has errors; "
        "its undefined variables are not checked\n" in result.out
    )
    assert result.code == 1
