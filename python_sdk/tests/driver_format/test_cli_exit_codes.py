"""FR-012: the exit codes of every command (0 passed, 1 driver errors or values differ, 2 cannot run)."""

from pathlib import Path

import pytest
import yaml
from styrmin_sdk.driver_format.context.models.contexts import GlobalContext

from .conftest import EXAMPLES, edit_spec

COMMANDS = ("check", "render", "diff", "context")


def _argv(command: str, driver: Path, base: Path) -> list[str]:
    return [command, str(driver), "--base", str(base)] if command == "diff" else [command, str(driver)]


@pytest.fixture
def base(tmp_path: Path, run_cli) -> Path:
    path = tmp_path / "base.yml"
    path.write_text(run_cli("render", str(EXAMPLES / "simple-app")).out, encoding="utf-8")
    return path


@pytest.mark.parametrize("command", COMMANDS)
def test_exit_code_0_for_a_valid_driver(command: str, base: Path, run_cli) -> None:
    assert run_cli(*_argv(command, EXAMPLES / "simple-app", base)).code == 0


@pytest.mark.parametrize("command", COMMANDS)
def test_exit_code_1_for_a_driver_with_errors(command: str, example_copy, base: Path, run_cli) -> None:
    driver = example_copy("simple-app")
    edit_spec(driver, lambda data: data["spec"]["info"].update(license=1))

    assert run_cli(*_argv(command, driver, base)).code == 1


@pytest.mark.parametrize(("command", "expected"), [("check", 1), ("render", 1), ("diff", 1), ("context", 0)])
def test_a_template_error_fails_every_command_but_context(
    command: str, expected: int, example_copy, base: Path, run_cli
) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text("a: '{{ parameters.missing }}'\n")

    assert run_cli(*_argv(command, driver, base)).code == expected


@pytest.mark.parametrize("command", COMMANDS)
def test_exit_code_2_for_a_directory_that_does_not_exist(command: str, tmp_path: Path, base: Path, run_cli) -> None:
    assert run_cli(*_argv(command, tmp_path / "nowhere", base)).code == 2


@pytest.mark.parametrize("command", COMMANDS)
def test_exit_code_2_for_an_unknown_option(command: str, base: Path, run_cli) -> None:
    assert run_cli(*_argv(command, EXAMPLES / "simple-app", base), "--bogus").code == 2


@pytest.mark.parametrize("command", COMMANDS)
def test_exit_code_2_for_a_context_file_that_cannot_be_read(command: str, tmp_path: Path, base: Path, run_cli) -> None:
    argv = [*_argv(command, EXAMPLES / "simple-app", base), "--context", str(tmp_path / "missing.yml")]

    assert run_cli(*argv).code == 2


def test_exit_code_1_for_a_directory_without_driver_spec_file(tmp_path: Path, run_cli) -> None:
    assert run_cli("check", str(tmp_path)).code == 1


def test_exit_code_2_without_a_command(run_cli) -> None:
    assert run_cli().code == 2


@pytest.mark.parametrize("argv", [("--help",), ("--version",), ("check", "--help")])
def test_help_and_version_exit_with_0(argv: tuple[str, ...], run_cli) -> None:
    result = run_cli(*argv)

    assert result.code == 0
    assert result.out


def test_version_names_the_command_and_the_sdk_version(run_cli) -> None:
    assert run_cli("--version").out.startswith("styrmin-driver 0.1.0")


@pytest.mark.parametrize(
    "template",
    ["a: {% if x %}\n", "a: '{{ components | component_command }}'\n", "a: [unclosed\n", "a: '{{ 1 // 0 }}'\n"],
    ids=["syntax error", "retired filter", "values not YAML", "render error"],
)
def test_context_ignores_every_template_error(template: str, example_copy, run_cli) -> None:
    driver = example_copy("simple-app")
    (driver / "values.j2.yml").write_text(template)

    result = run_cli("context", str(driver))

    assert result.code == 0, result.err
    GlobalContext.model_validate(yaml.safe_load(result.out))
    assert "values.j2.yml" not in result.err


def test_an_unexpected_exception_exits_with_2_as_an_internal_error(monkeypatch: pytest.MonkeyPatch, run_cli) -> None:
    def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("styrmin_sdk.driver_format.cli.run_checks", crash)

    result = run_cli("check", str(EXAMPLES / "simple-app"))

    assert result.code == 2
    assert "styrmin-driver: internal error: RuntimeError: boom" in result.err
