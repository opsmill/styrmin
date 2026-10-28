"""User story 3 and FR-011: ``diff`` compares values, not text."""

from pathlib import Path

import yaml
from styrmin_sdk.driver_format.diff import compare_values

from .conftest import EXAMPLES


def _render_to(run_cli, driver: Path, target: Path) -> dict:
    result = run_cli("render", str(driver))
    assert result.code == 0, result.err
    target.write_text(result.out, encoding="utf-8")
    return yaml.safe_load(result.out)


def test_same_values_give_exit_code_0_and_no_output(tmp_path: Path, run_cli) -> None:
    base = tmp_path / "base.yml"
    _render_to(run_cli, EXAMPLES / "simple-app", base)

    result = run_cli("diff", str(EXAMPLES / "simple-app"), "--base", str(base))

    assert result.code == 0
    assert not result.out


def test_other_key_order_indentation_and_quoting_are_not_differences(tmp_path: Path, run_cli) -> None:
    base = tmp_path / "base.yml"
    values = _render_to(run_cli, EXAMPLES / "simple-app", base)
    reordered = dict(reversed(list(values.items())))
    base.write_text(yaml.safe_dump(reordered, sort_keys=False, indent=4, default_style='"'), encoding="utf-8")

    result = run_cli("diff", str(EXAMPLES / "simple-app"), "--base", str(base))

    assert result.code == 0, result.out


def test_a_changed_type_is_a_difference() -> None:
    lines = compare_values({"port": "8080"}, {"port": 8080}, base_label="base.yml", rendered_label="rendered")

    assert lines
    assert "-port: '8080'\n" in lines
    assert "+port: 8080\n" in lines


def test_a_changed_template_value_shows_a_unified_diff_and_exit_code_1(example_copy, tmp_path: Path, run_cli) -> None:
    driver = example_copy("simple-app")
    base = tmp_path / "base.yml"
    _render_to(run_cli, driver, base)
    (driver / "values.j2.yml").write_text((driver / "values.j2.yml").read_text() + "extra_value: 42\n")

    result = run_cli("diff", str(driver), "--base", str(base))

    assert result.code == 1
    assert result.out.startswith(f"--- {base}\n+++ rendered {driver}\n")
    assert "+extra_value: 42\n" in result.out


def test_a_base_file_that_does_not_exist_exits_with_2(tmp_path: Path, run_cli) -> None:
    result = run_cli("diff", str(EXAMPLES / "simple-app"), "--base", str(tmp_path / "missing.yml"))

    assert result.code == 2
    assert "the base values file cannot be read" in result.err


def test_a_base_file_that_is_not_yaml_exits_with_2(tmp_path: Path, run_cli) -> None:
    base = tmp_path / "base.yml"
    base.write_text("a: [unclosed\n", encoding="utf-8")

    result = run_cli("diff", str(EXAMPLES / "simple-app"), "--base", str(base))

    assert result.code == 2
    assert "the base values file is not valid YAML" in result.err


def test_a_missing_base_option_exits_with_2(run_cli) -> None:
    assert run_cli("diff", str(EXAMPLES / "simple-app")).code == 2


def test_a_base_file_that_is_not_utf8_exits_with_2(tmp_path: Path, run_cli) -> None:
    base = tmp_path / "base.yml"
    base.write_bytes(b"a: \xff\n")

    result = run_cli("diff", str(EXAMPLES / "simple-app"), "--base", str(base))

    assert result.code == 2
    assert "the base values file is not valid UTF-8" in result.err
